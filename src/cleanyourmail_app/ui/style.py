"""Theme helpers shared by every page.

Qt applies a stylesheet rule that depends on a dynamic property (``[active]``,
``[status]``, ``[invalid]``) only when the widget is polished again. Forgetting
the repolish leaves the visual state stale even though the property is right,
so every property change goes through :func:`set_dynamic_property`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QWidget

THEME_PATH = Path(__file__).with_name("theme.qss")


def theme_stylesheet() -> str:
    """Return the bundled QSS; a missing file is a packaging error."""
    return THEME_PATH.read_text(encoding="utf-8")


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_dynamic_property(widget: QWidget, name: str, value: object) -> None:
    """Set ``name`` on ``widget`` and repolish only when the value changed."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    repolish(widget)
