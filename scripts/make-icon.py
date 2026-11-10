#!/usr/bin/env python3
"""Convert the CleanYourMail SVG app icon into a multi-resolution Windows .ico.

The source is the brand icon from the main repository
(``brand/final-spectrum/app-icon.svg``), mirrored byte-for-byte at
``src/cleanyourmail_app/ui/resources/app-icon.svg`` for the runtime window icon.
Pass ``--source`` to render the brand file directly.

Rendering uses PySide6's QSvgRenderer; the ICO is written with uncompressed
32-bit DIB entries (no Pillow dependency) so PyInstaller and Inno Setup, and
Windows itself, read every size without PNG-icon quirks.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from pathlib import Path

# Render offscreen: the script must also work on a build agent without an
# interactive desktop. Qt must see this before PySide6 is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "src" / "cleanyourmail_app" / "ui" / "resources" / "app-icon.svg"
DEFAULT_OUTPUT = ROOT / "packaging" / "app.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _dib(image) -> bytes:
    """A 32-bit bottom-up DIB with an all-zero AND mask, as ICO expects."""
    from PySide6.QtGui import QImage

    width = image.width()
    height = image.height()
    rgba = image.convertToFormat(QImage.Format.Format_ARGB32)
    raw = bytes(rgba.bits())
    stride = rgba.bytesPerLine()

    xor = b"".join(
        raw[row * stride : row * stride + width * 4]
        for row in range(height - 1, -1, -1)
    )
    # 1bpp AND mask padded to 32-bit rows. Alpha in the XOR data carries the
    # real transparency; zeros keep legacy readers opaque rather than black.
    mask_row = ((width + 31) // 32) * 4
    mask = b"\x00" * (mask_row * height)
    header = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        height * 2,
        1,
        32,
        0,
        len(xor) + len(mask),
        0,
        0,
        0,
        0,
    )
    return header + xor + mask


def _render(svg: bytes, size: int) -> bytes:
    from PySide6.QtCore import QByteArray, QRectF
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(QByteArray(svg))
    if not renderer.isValid():
        raise ValueError("the SVG is not valid")

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        renderer.render(painter, QRectF(0, 0, size, size))
    finally:
        painter.end()
    return _dib(image)


def build_ico(svg: bytes) -> bytes:
    images = [(size, _render(svg, size)) for size in SIZES]

    offset = 6 + 16 * len(images)
    directory = []
    payload = []
    for size, data in images:
        width = 0 if size >= 256 else size
        directory.append(
            struct.pack("<BBBBHHII", width, width, 0, 0, 1, 32, len(data), offset)
        )
        payload.append(data)
        offset += len(data)

    return (
        struct.pack("<HHH", 0, 1, len(images))
        + b"".join(directory)
        + b"".join(payload)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_file():
        print(f"error: icon source not found: {source}", file=sys.stderr)
        return 1

    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication([])
    try:
        data = build_ico(source.read_bytes())
    except Exception as exc:  # Qt raises several unrelated types on bad SVG
        print(f"error: could not convert {source}: {exc}", file=sys.stderr)
        return 1
    finally:
        if QGuiApplication.instance() is app and app is not None:
            app.quit()

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    print(f"wrote {output} ({len(data)} bytes, sizes: {', '.join(map(str, SIZES))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
