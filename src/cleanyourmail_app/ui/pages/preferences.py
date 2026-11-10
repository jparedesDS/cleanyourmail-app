"""The third wizard page: what to clean, how, and what to protect.

The page owns the preference half of ``AppSettings`` and nothing else. It never
touches the network or the mailbox: it writes the person's choices to
``SettingsStore`` as they change, and on Continue it hands the same policy to
``ConfigService.update_preferences`` so the CLI is the only engine that acts.

Every value shown here maps to a real sidecar key and no more:

* ``categories`` are the six message classes the scanner knows.
* ``mode`` is the reversible folder move or Gmail's archive.
* ``protect_starred`` is IMAP ``\\Flagged`` (Gmail's star) and
  ``protect_answered`` is ``\\Answered``.
* the three limits are the safety belt: small runs are easier to check and undo.

Validation is deliberately local. A limit outside its accepted range disables
Continue and explains why, instead of writing a config the CLI would reject.
When the TOML is missing the page stays put and points back to Connect: only a
connected account can have a config to edit.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cleanyourmail_app.domain.models import CATEGORIES, Preferences
from cleanyourmail_app.services.app_services import AppServices
from cleanyourmail_app.services.config import ConfigServiceError

#: The two filing modes, matching ``Preferences.mode``.
MODE_FOLDERS = "folders"
MODE_ARCHIVE = "archive"

#: The accepted ranges. They are tighter than the widget's own bounds so an
#: out-of-range value can be typed and explained, never silently clamped.
MIN_AGE_FLOOR = 0
MIN_AGE_CEILING = 3650
MOVES_FLOOR = 1
MOVES_CEILING = 5000

#: The widget bound; validation owns the narrower, contractual range above.
_SPIN_CEILING = 99999


class PreferencesPage(QWidget):
    """Checkboxes, a mode, protections, limits and an optional Advanced panel."""

    continueRequested = Signal()
    backRequested = Signal()
    languageChanged = Signal(str)

    def __init__(
        self,
        services: AppServices,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._settings = services.settings
        self._translator = services.translator
        self._loading = False
        self._syncing_language = False
        self._feedback_key: str | None = None
        self.category_boxes: dict[str, QCheckBox] = {}

        self._build()
        self.reload()

    # -- public state -------------------------------------------------------

    def current_preferences(self) -> Preferences:
        """The values on screen as a validated ``Preferences``.

        Only call this when :meth:`is_valid` is true: the model raises on an
        out-of-range limit, which is exactly the state Continue refuses.
        """
        return Preferences(
            categories=self._selected_categories(),
            mode=self._selected_mode(),
            protect_starred=self.starred_check.isChecked(),
            protect_answered=self.answered_check.isChecked(),
            min_age_days=self.min_age_spin.value(),
            max_moves=self.max_moves_spin.value(),
            max_per_group=self.max_per_group_spin.value(),
            language=self._translator.language,
        )

    def is_valid(self) -> bool:
        """Whether the choices can be saved and handed to the CLI."""
        return bool(self._selected_categories()) and self._limits_valid()

    def reload(self) -> None:
        """Restore the stored choices without writing them back.

        Called once at construction and whenever the shell enters this page, so
        a change made elsewhere (or in a previous run) is never hidden by a
        stale widget. Signals are blocked through ``_loading`` so a reload is
        not mistaken for an edit.
        """
        self._loading = True
        try:
            preferences = self._settings.load().preferences
            for category, box in self.category_boxes.items():
                box.setChecked(category in preferences.categories)
            self.folders_radio.setChecked(preferences.mode != MODE_ARCHIVE)
            self.archive_radio.setChecked(preferences.mode == MODE_ARCHIVE)
            self.starred_check.setChecked(preferences.protect_starred)
            self.answered_check.setChecked(preferences.protect_answered)
            self.min_age_spin.setValue(preferences.min_age_days)
            self.max_moves_spin.setValue(preferences.max_moves)
            self.max_per_group_spin.setValue(preferences.max_per_group)
            # The app starts the translator from the same file, so this is a
            # no-op in the real window and keeps a reopened page coherent in
            # isolation. No signal: the window is not listening yet.
            if preferences.language != self._translator.language:
                self._translator.set_language(preferences.language)
            self._sync_language_combo()
        finally:
            self._loading = False

        self._feedback_key = None
        self._sync_paths()
        self._refresh_state()

    # -- layout -------------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("pageScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        body = QWidget(self.scroll)
        root = QVBoxLayout(body)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(14)

        self.title_label = QLabel(self)
        self.title_label.setObjectName("title")
        self.title_label.setWordWrap(True)

        self.subtitle_label = QLabel(self)
        self.subtitle_label.setObjectName("subtitle")
        self.subtitle_label.setWordWrap(True)

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(16)

        self.categories_group = QGroupBox(self)
        categories_layout = QVBoxLayout(self.categories_group)
        categories_layout.setContentsMargins(0, 0, 0, 0)
        categories_layout.setSpacing(2)
        for category in CATEGORIES:
            box = QCheckBox(self.categories_group)
            box.setObjectName(f"category_{category}")
            box.setChecked(True)
            box.toggled.connect(self._on_changed)
            self.category_boxes[category] = box
            categories_layout.addWidget(box)
        categories_layout.addStretch(1)

        self.mode_group = QGroupBox(self)
        mode_layout = QVBoxLayout(self.mode_group)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(2)
        self.folders_radio = QRadioButton(self.mode_group)
        self.folders_radio.setObjectName("mode_folders")
        self.folders_radio.setChecked(True)
        self.folders_radio.toggled.connect(self._on_changed)
        self.folders_help = QLabel(self.mode_group)
        self.folders_help.setObjectName("muted")
        self.folders_help.setWordWrap(True)
        self.archive_radio = QRadioButton(self.mode_group)
        self.archive_radio.setObjectName("mode_archive")
        self.archive_radio.toggled.connect(self._on_changed)
        self.archive_help = QLabel(self.mode_group)
        self.archive_help.setObjectName("muted")
        self.archive_help.setWordWrap(True)
        mode_layout.addWidget(self.folders_radio)
        mode_layout.addWidget(self.folders_help)
        mode_layout.addSpacing(8)
        mode_layout.addWidget(self.archive_radio)
        mode_layout.addWidget(self.archive_help)
        mode_layout.addStretch(1)

        columns.addWidget(self.categories_group, 3)
        columns.addWidget(self.mode_group, 2)

        self.protect_group = QGroupBox(self)
        protect = QGridLayout(self.protect_group)
        protect.setContentsMargins(0, 0, 0, 0)
        protect.setHorizontalSpacing(10)
        protect.setVerticalSpacing(4)
        self.starred_check = QCheckBox(self.protect_group)
        self.starred_check.setObjectName("protect_starred")
        self.starred_check.setChecked(True)
        self.starred_check.toggled.connect(self._on_changed)
        self.answered_check = QCheckBox(self.protect_group)
        self.answered_check.setObjectName("protect_answered")
        self.answered_check.setChecked(True)
        self.answered_check.toggled.connect(self._on_changed)

        self.min_age_label = QLabel(self.protect_group)
        self.min_age_spin = QSpinBox(self.protect_group)
        self.min_age_spin.setObjectName("minAge")
        self.min_age_spin.setRange(0, _SPIN_CEILING)
        self.min_age_spin.setValue(30)
        self.min_age_spin.valueChanged.connect(self._on_changed)
        self.min_age_label.setBuddy(self.min_age_spin)
        self.min_age_suffix = QLabel(self.protect_group)
        self.min_age_suffix.setObjectName("muted")

        self.protect_help = QLabel(self.protect_group)
        self.protect_help.setObjectName("muted")
        self.protect_help.setWordWrap(True)

        protect.addWidget(self.starred_check, 0, 0, 1, 3)
        protect.addWidget(self.answered_check, 1, 0, 1, 3)
        protect.addWidget(self.min_age_label, 2, 0)
        protect.addWidget(self.min_age_spin, 2, 1)
        protect.addWidget(self.min_age_suffix, 2, 2)
        protect.addWidget(self.protect_help, 3, 0, 1, 3)
        protect.setColumnStretch(2, 1)

        self.limits_group = QGroupBox(self)
        limits = QGridLayout(self.limits_group)
        limits.setContentsMargins(0, 0, 0, 0)
        limits.setHorizontalSpacing(10)
        limits.setVerticalSpacing(4)
        self.max_moves_label = QLabel(self.limits_group)
        self.max_moves_spin = QSpinBox(self.limits_group)
        self.max_moves_spin.setObjectName("maxMoves")
        self.max_moves_spin.setRange(0, _SPIN_CEILING)
        self.max_moves_spin.setValue(50)
        self.max_moves_spin.valueChanged.connect(self._on_changed)
        self.max_moves_label.setBuddy(self.max_moves_spin)
        self.max_per_group_label = QLabel(self.limits_group)
        self.max_per_group_spin = QSpinBox(self.limits_group)
        self.max_per_group_spin.setObjectName("maxPerGroup")
        self.max_per_group_spin.setRange(0, _SPIN_CEILING)
        self.max_per_group_spin.setValue(100)
        self.max_per_group_spin.valueChanged.connect(self._on_changed)
        self.max_per_group_label.setBuddy(self.max_per_group_spin)
        self.limits_help = QLabel(self.limits_group)
        self.limits_help.setObjectName("muted")
        self.limits_help.setWordWrap(True)

        limits.addWidget(self.max_moves_label, 0, 0)
        limits.addWidget(self.max_moves_spin, 0, 1)
        limits.addWidget(self.max_per_group_label, 1, 0)
        limits.addWidget(self.max_per_group_spin, 1, 1)
        limits.addWidget(self.limits_help, 2, 0, 1, 2)
        limits.setColumnStretch(0, 1)

        self.spam_note = QLabel(self)
        self.spam_note.setObjectName("muted")
        self.spam_note.setWordWrap(True)

        self.advanced_toggle = QToolButton(self)
        self.advanced_toggle.setObjectName("advancedToggle")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(False)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.advanced_toggle.setAutoRaise(True)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)

        self.advanced_panel = QWidget(self)
        advanced = QGridLayout(self.advanced_panel)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.setHorizontalSpacing(10)
        advanced.setVerticalSpacing(6)
        self.config_path_label = QLabel(self.advanced_panel)
        self.config_path_edit = QLineEdit(self.advanced_panel)
        self.config_path_edit.setObjectName("configPath")
        self.config_path_edit.setReadOnly(True)
        self.config_path_label.setBuddy(self.config_path_edit)
        self.state_path_label = QLabel(self.advanced_panel)
        self.state_path_edit = QLineEdit(self.advanced_panel)
        self.state_path_edit.setObjectName("statePath")
        self.state_path_edit.setReadOnly(True)
        self.state_path_label.setBuddy(self.state_path_edit)
        self.cli_state_label = QLabel(self.advanced_panel)
        self.cli_state_edit = QLineEdit(self.advanced_panel)
        self.cli_state_edit.setObjectName("cliStatePath")
        self.cli_state_edit.setReadOnly(True)
        self.cli_state_label.setBuddy(self.cli_state_edit)
        self.language_label = QLabel(self.advanced_panel)
        self.language_combo = QComboBox(self.advanced_panel)
        self.language_combo.setObjectName("language")
        self.language_label.setBuddy(self.language_combo)
        self.advanced_help = QLabel(self.advanced_panel)
        self.advanced_help.setObjectName("muted")
        self.advanced_help.setWordWrap(True)

        self._build_languages()
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)

        advanced.addWidget(self.config_path_label, 0, 0)
        advanced.addWidget(self.config_path_edit, 0, 1)
        advanced.addWidget(self.state_path_label, 1, 0)
        advanced.addWidget(self.state_path_edit, 1, 1)
        advanced.addWidget(self.cli_state_label, 2, 0)
        advanced.addWidget(self.cli_state_edit, 2, 1)
        advanced.addWidget(self.language_label, 3, 0)
        advanced.addWidget(self.language_combo, 3, 1)
        advanced.addWidget(self.advanced_help, 4, 0, 1, 2)
        advanced.setColumnStretch(1, 1)
        self.advanced_panel.setVisible(False)

        self.error_label = QLabel(self)
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)

        self.continue_button = QPushButton(self)
        self.continue_button.setObjectName("primary")
        self.continue_button.setMinimumWidth(180)
        self.continue_button.clicked.connect(self._continue)

        self.back_button = QPushButton(self)
        self.back_button.setObjectName("secondary")
        self.back_button.setMinimumWidth(140)
        self.back_button.clicked.connect(self._go_back)

        actions = QHBoxLayout()
        actions.setContentsMargins(32, 12, 32, 24)
        actions.addWidget(self.back_button)
        actions.addStretch(1)
        actions.addWidget(self.continue_button)

        root.addWidget(self.title_label)
        root.addWidget(self.subtitle_label)
        root.addLayout(columns)
        root.addWidget(self.protect_group)
        root.addWidget(self.limits_group)
        root.addWidget(self.spam_note)
        root.addWidget(self.advanced_toggle)
        root.addWidget(self.advanced_panel)
        root.addWidget(self.error_label)
        root.addStretch(1)

        self.scroll.setWidget(body)
        outer.addWidget(self.scroll, 1)
        outer.addLayout(actions)

        self._sync_paths()
        self.retranslate()

    def _build_languages(self) -> None:
        """One item per catalog, keyed by its language code."""
        for language in self._translator.available_languages:
            self.language_combo.addItem(language, language)

    def _sync_paths(self) -> None:
        """Show where the app keeps its state; the fields are read-only."""
        self.config_path_edit.setText(str(self._services.config.config_path()))
        self.state_path_edit.setText(str(self._services.config.app_data))
        self.cli_state_edit.setText(str(self._services.config.state_dir()))

    # -- copy ---------------------------------------------------------------

    def retranslate(self) -> None:
        """Refresh every visible string from the active catalog."""
        t = self._translator.t

        self.title_label.setText(t("preferences.title"))
        self.subtitle_label.setText(t("preferences.subtitle"))
        self.categories_group.setTitle(t("preferences.categories.title"))
        self.mode_group.setTitle(t("preferences.mode.title"))
        self.protect_group.setTitle(t("preferences.protect.title"))
        self.limits_group.setTitle(t("preferences.limits.title"))

        for category, box in self.category_boxes.items():
            label = t(f"preferences.category.{category}.label")
            box.setText(label)
            box.setToolTip(t(f"preferences.category.{category}.help"))
            box.setAccessibleName(label)

        self.folders_radio.setText(t("preferences.mode.folders"))
        self.folders_help.setText(t("preferences.mode.folders_help"))
        self.archive_radio.setText(t("preferences.mode.archive"))
        self.archive_help.setText(t("preferences.mode.archive_help"))

        self.starred_check.setText(t("preferences.protect.starred"))
        self.answered_check.setText(t("preferences.protect.answered"))
        self.min_age_label.setText(t("preferences.protect.min_age"))
        self.min_age_suffix.setText(t("preferences.protect.min_age_suffix"))
        self.protect_help.setText(t("preferences.protect.help"))

        self.max_moves_label.setText(t("preferences.limits.max_moves"))
        self.max_per_group_label.setText(t("preferences.limits.max_per_group"))
        self.limits_help.setText(t("preferences.limits.help"))
        self.spam_note.setText(t("preferences.spam_note"))

        self.advanced_toggle.setText(t("preferences.advanced.title"))
        self.config_path_label.setText(t("preferences.advanced.config_path"))
        self.config_path_edit.setAccessibleName(
            t("preferences.advanced.config_path")
        )
        self.state_path_label.setText(t("preferences.advanced.app_data"))
        self.state_path_edit.setAccessibleName(
            t("preferences.advanced.app_data")
        )
        self.cli_state_label.setText(t("preferences.advanced.cli_state"))
        self.cli_state_edit.setAccessibleName(
            t("preferences.advanced.cli_state")
        )
        self.language_label.setText(t("preferences.advanced.language"))
        self.language_combo.setAccessibleName(t("preferences.advanced.language"))
        self.advanced_help.setText(t("preferences.advanced.help"))

        self.back_button.setText(t("common.back"))
        self.continue_button.setText(t("preferences.continue"))
        self._sync_language_combo()
        self._refresh_state()

    def _sync_language_combo(self) -> None:
        """Show the translator's language without re-entering its handler."""
        self._syncing_language = True
        try:
            for index in range(self.language_combo.count()):
                code = self.language_combo.itemData(index)
                self.language_combo.setItemText(
                    index, self._translator.t(f"language.{code}")
                )
                if code == self._translator.language:
                    self.language_combo.setCurrentIndex(index)
        finally:
            self._syncing_language = False

    # -- interaction --------------------------------------------------------

    def _toggle_advanced(self, opened: bool) -> None:
        self.advanced_panel.setVisible(opened)
        self.advanced_toggle.setArrowType(
            Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow
        )

    def _on_language_changed(self, index: int) -> None:
        """Apply the chosen language, remember it and tell the window."""
        if self._loading or self._syncing_language:
            return
        language = self.language_combo.itemData(index)
        if not isinstance(language, str) or language == self._translator.language:
            return
        self._translator.set_language(language)
        self.retranslate()
        self._persist()
        self.languageChanged.emit(language)

    def _on_changed(self) -> None:
        """Persist a valid edit; keep an invalid one on screen but unsaved."""
        if self._loading:
            return
        if self.is_valid():
            self._feedback_key = None
            self._persist()
        self._refresh_state()

    def _persist(self) -> None:
        """Write the current choices, preserving provider and email."""
        if self._loading or not self.is_valid():
            return
        try:
            self._settings.update_preferences(self.current_preferences())
        except (OSError, ValueError, TypeError):
            # A read-only profile is not fatal: the person can still continue,
            # and Continue retries the write before touching the TOML.
            return

    def _selected_categories(self) -> list[str]:
        return [
            category
            for category in CATEGORIES
            if self.category_boxes[category].isChecked()
        ]

    def _selected_mode(self) -> str:
        return MODE_ARCHIVE if self.archive_radio.isChecked() else MODE_FOLDERS

    def _limits_valid(self) -> bool:
        return (
            MIN_AGE_FLOOR <= self.min_age_spin.value() <= MIN_AGE_CEILING
            and MOVES_FLOOR <= self.max_moves_spin.value() <= MOVES_CEILING
            and MOVES_FLOOR <= self.max_per_group_spin.value() <= MOVES_CEILING
        )

    # -- feedback -----------------------------------------------------------

    def _error_key(self) -> str | None:
        """The first reason Continue is unavailable, else the last failure."""
        if not self._selected_categories():
            return "preferences.category_required"
        if not self._limits_valid():
            return "preferences.limits.out_of_range"
        return self._feedback_key

    def _show_error(self, key: str) -> None:
        self._feedback_key = key
        self._refresh_state()

    def _refresh_state(self) -> None:
        key = self._error_key()
        self.error_label.setText(self._translator.t(key) if key else "")
        self.error_label.setVisible(bool(key))
        self.continue_button.setEnabled(self.is_valid())

    # -- navigation ---------------------------------------------------------

    def _go_back(self) -> None:
        """Ask the shell for the previous page; no config is written."""
        self.backRequested.emit()

    def _continue(self) -> None:
        """Save the choices, write the TOML policy, then let the shell advance."""
        if not self.is_valid():
            self._refresh_state()
            return

        preferences = self.current_preferences()
        try:
            self._settings.update_preferences(preferences)
        except (OSError, ValueError, TypeError):
            pass

        if not self._services.config.config_path().is_file():
            self._show_error("errors.config_missing")
            return

        try:
            self._services.config.update_preferences(preferences)
        except (ConfigServiceError, OSError, ValueError, TypeError):
            self._show_error("errors.config")
            return

        self._feedback_key = None
        self._refresh_state()
        self.continueRequested.emit()
