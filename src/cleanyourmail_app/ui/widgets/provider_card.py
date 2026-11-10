"""One large, checkable provider card.

The card is a ``QPushButton`` so it is focusable, toggles with Space and Enter,
and gets the theme's ``#providerCard`` checked and focus rings for free. Its
visible content is built from child labels, which are transparent for mouse
events: clicking anywhere on the card still presses the button.

The status badge shows ``Tested``, ``Limited`` or ``Documented`` honestly; the
tooltip carries the longer explanation.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cleanyourmail_app.domain.providers import Provider
from cleanyourmail_app.i18n import Translator
from cleanyourmail_app.ui.style import set_dynamic_property

#: Enough room for a two-line title plus the status badge.
CARD_MIN_HEIGHT = 96


class ProviderCard(QPushButton):
    """A provider choice; ``selected`` mirrors the button's checked state."""

    def __init__(
        self,
        provider: Provider,
        translator: Translator,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.provider = provider
        self._translator = translator

        self.setObjectName("providerCard")
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(CARD_MIN_HEIGHT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        self.title_label = QLabel(self)
        self.title_label.setObjectName("section")
        self.title_label.setWordWrap(True)

        self.badge = QLabel(self)
        self.badge.setObjectName("badge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        header.addWidget(self.title_label, 1)
        header.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        layout.addStretch(1)

        # Labels must not swallow the click: the whole card is the target.
        for label in (self.title_label, self.badge):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            label.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.retranslate()

    @property
    def selected(self) -> bool:
        """Whether this card is the current choice."""
        return self.isChecked()

    def setSelected(self, selected: bool) -> None:
        """Check or uncheck the card without emitting the page's signal."""
        self.setChecked(bool(selected))

    def retranslate(self) -> None:
        """Refresh every visible string from the active catalog."""
        provider = self.provider
        title = self._translator.t(f"provider.{provider.id}.label")
        note = self._translator.t(f"provider.{provider.id}.note")
        status = self._translator.t(f"provider.status.{provider.status}")
        detail = self._translator.t(f"provider.status.{provider.status}_detail")

        self.title_label.setText(title)
        self.badge.setText(status)
        set_dynamic_property(self.badge, "status", provider.status)

        self.setAccessibleName(title)
        self.setAccessibleDescription(f"{note} {detail}")
        self.setToolTip(f"{note}\n{detail}")
