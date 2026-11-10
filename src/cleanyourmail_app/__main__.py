"""Module entry point for ``python -m cleanyourmail_app``."""

from __future__ import annotations

import sys

from cleanyourmail_app.version import __version__


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--version" in args:
        print(f"CleanYourMail app {__version__}")
        return 0

    from cleanyourmail_app.app import main as app_main

    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
