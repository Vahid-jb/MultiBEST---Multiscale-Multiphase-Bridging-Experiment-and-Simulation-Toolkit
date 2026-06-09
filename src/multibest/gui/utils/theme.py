# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shared theme utilities for all MultiBEST GUI applications.

Applies a unified dark appearance via Qt Style Sheets (QSS) and QPalette.
Also exports the no-wheel spin-box/combo-box subclasses and the reusable
button factory functions used by every sub-module.
"""

import sys
from pathlib import Path
from string import Template

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

try:
    import qtawesome as qta
except Exception:  # pragma: no cover - qtawesome is optional at import time
    qta = None

QLEMENTINE_DARK = {
    "background_main_1": "#20242a",
    "background_main_2": "#181b20",
    "background_main_3": "#252a31",
    "background_main_4": "#2b3139",
    "background_workspace": "#111418",
    "background_tabbar": "#1c2026",
    "border": "#3a414c",
    "border_hovered": "#55606f",
    "border_pressed": "#687486",
    "border_disabled": "#2a3038",
    "focus": "#40a9ff66",
    "neutral": "#303743",
    "neutral_hovered": "#394250",
    "neutral_pressed": "#242a33",
    "neutral_disabled": "#252a31",
    "primary": "#1890ff",
    "primary_hovered": "#2c9dff",
    "primary_pressed": "#106ef9",
    "primary_disabled": "#24415d",
    "primary_foreground": "#ffffff",
    "secondary": "#e7eaf0",
    "secondary_hovered": "#ffffff",
    "secondary_pressed": "#f4f7fb",
    "secondary_disabled": "#737d8c",
    "secondary_alternative": "#a4adba",
    "success": "#2bb5a0",
    "info": "#1ba8d5",
    "warning": "#fbc064",
    "error": "#e96b72",
    "status_foreground": "#ffffff",
}


def _theme_icon_dir() -> Path:
    """Return the theme icon directory in source and PyInstaller layouts."""
    if getattr(sys, "frozen", False):
        bundle_internal = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        bundle_root = Path(sys.executable).parent
        for base in (bundle_internal, bundle_root):
            candidate = base / "multibest" / "gui" / "assets" / "icons"
            if candidate.is_dir():
                return candidate
    return Path(__file__).resolve().parent.parent / "assets" / "icons"


_THEME_ICON_DIR = _theme_icon_dir()

_ACTION_ICONS = {
    "add": "fa5s.plus",
    "analyze": "fa5s.chart-bar",
    "apply": "fa5s.check",
    "browse": "fa5s.folder-open",
    "cancel": "fa5s.times",
    "convert": "fa5s.exchange-alt",
    "delete": "fa5s.trash-alt",
    "download": "fa5s.download",
    "export": "fa5s.file-export",
    "file": "fa5s.file-alt",
    "generate": "fa5s.play",
    "help": "fa5s.question-circle",
    "import": "fa5s.file-import",
    "remove": "fa5s.minus-circle",
    "reset": "fa5s.sync-alt",
    "save": "fa5s.save",
    "stop": "fa5s.stop",
    "test": "fa5s.vial",
}


def _icon(icon_name: str, *, color: str | None = None, disabled_color: str | None = None) -> QIcon:
    """Return a themed QtAwesome icon, or an empty icon when unavailable."""
    if qta is None:
        return QIcon()
    color = color or QLEMENTINE_DARK["secondary"]
    disabled_color = disabled_color or QLEMENTINE_DARK["secondary_disabled"]
    return qta.icon(icon_name, color=color, color_disabled=disabled_color)


def icon_for_action(action: str) -> QIcon:
    """Return the standard icon for an action key."""
    return _icon(_ACTION_ICONS[action])


def decorate_action_button(button: QPushButton, action: str, *, icon_size: int = 14) -> QPushButton:
    """Attach a standard action icon and cursor to *button*."""
    button.setIcon(icon_for_action(action))
    button.setIconSize(QSize(icon_size, icon_size))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def make_action_button(text: str, action: str, *, icon_size: int = 14) -> QPushButton:
    """Create a standard secondary action button with icon and text."""
    return decorate_action_button(QPushButton(text), action, icon_size=icon_size)


def action_for_text(text: str, *, fallback: str = "generate") -> str:
    """Infer a standard action key from a button label."""
    normalized = text.lower()
    for keyword, action in (
        ("analy", "analyze"),
        ("apply", "apply"),
        ("browse", "browse"),
        ("cancel", "cancel"),
        ("convert", "convert"),
        ("delete", "delete"),
        ("download", "download"),
        ("export", "export"),
        ("import", "import"),
        ("remove", "remove"),
        ("reset", "reset"),
        ("rescale", "generate"),
        ("save", "save"),
        ("stop", "stop"),
        ("test", "test"),
    ):
        if keyword in normalized:
            return action
    return fallback


def make_path_row(
    line_edit: QLineEdit,
    button_text: str,
    on_click,
    *,
    action: str = "browse",
) -> QWidget:
    """Return a consistent path-input row with a trailing action button."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.addWidget(line_edit, 1)
    button = make_action_button(button_text, action)
    button.clicked.connect(on_click)
    layout.addWidget(button)
    return row


class NoWheelSpinBox(QSpinBox):
    """QSpinBox that ignores scroll-wheel events to prevent accidental value changes."""

    def wheelEvent(self, event) -> None:
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that ignores scroll-wheel events to prevent accidental value changes."""

    def wheelEvent(self, event) -> None:
        event.ignore()


class NoWheelComboBox(QComboBox):
    """QComboBox that ignores scroll-wheel events to prevent accidental selection changes."""

    def wheelEvent(self, event) -> None:
        event.ignore()


def apply_dark_theme(app: QApplication) -> None:
    """Apply a Qlementine-inspired Fusion dark theme to *app*.

    Sets the application style to "Fusion" and installs a custom QPalette and
    QSS stylesheet that follows Qlementine's compact, layered desktop look.
    """
    app.setStyle("Fusion")

    dark_palette = QPalette()

    c = QLEMENTINE_DARK | {
        "checkbox_tick": _THEME_ICON_DIR.joinpath("checkbox_tick.svg").as_posix(),
        "combo_arrow_down": _THEME_ICON_DIR.joinpath("combo_arrow_down.svg").as_posix(),
        "spin_arrow_down": _THEME_ICON_DIR.joinpath("spin_arrow_down.svg").as_posix(),
        "spin_arrow_up": _THEME_ICON_DIR.joinpath("spin_arrow_up.svg").as_posix(),
    }
    window_color = QColor(c["background_main_2"])
    base_color = QColor(c["background_main_1"])
    text_color = QColor(c["secondary"])
    highlight_color = QColor(c["primary"])
    highlighted_text_color = QColor(c["primary_foreground"])

    dark_palette.setColor(QPalette.ColorRole.Window, window_color)
    dark_palette.setColor(QPalette.ColorRole.WindowText, text_color)
    dark_palette.setColor(QPalette.ColorRole.Base, base_color)
    dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c["background_main_3"]))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase, text_color)
    dark_palette.setColor(QPalette.ColorRole.ToolTipText, QColor(c["background_workspace"]))
    dark_palette.setColor(QPalette.ColorRole.Text, text_color)
    dark_palette.setColor(QPalette.ColorRole.Button, QColor(c["neutral"]))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, text_color)
    dark_palette.setColor(QPalette.ColorRole.BrightText, QColor(c["error"]))
    dark_palette.setColor(QPalette.ColorRole.Link, highlight_color)
    dark_palette.setColor(QPalette.ColorRole.Highlight, highlight_color)
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, highlighted_text_color)
    dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(c["secondary_disabled"]))
    dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(c["secondary_disabled"]))
    dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(c["secondary_disabled"]))

    app.setPalette(dark_palette)

    app.setStyleSheet(
        Template("""
        QToolTip {
            color: ${secondary};
            background-color: ${background_main_4};
            border: 1px solid ${border_hovered};
            border-radius: 6px;
            padding: 6px 8px;
        }
        QWidget {
            font-size: 10pt;
            color: ${secondary};
            selection-background-color: ${primary};
            selection-color: ${primary_foreground};
        }
        QMainWindow, QDialog {
            background-color: ${background_main_2};
        }
        QFrame, QScrollArea, QStackedWidget {
            background-color: transparent;
        }
        QLabel {
            background-color: transparent;
        }
        QLabel#moduleTitle {
            color: ${secondary_hovered};
            font-size: 22px;
            font-weight: 700;
            padding-bottom: 6px;
        }
        QLabel#panelTitle {
            color: ${secondary_hovered};
            font-size: 20px;
            font-weight: 700;
        }
        QLabel#subtleText {
            color: ${secondary_alternative};
        }
        QLabel#previewPlaceholder {
            color: ${secondary_alternative};
            font-size: 14px;
            padding: 24px;
        }
        QFrame#previewPanel, QWidget#previewPanel {
            background-color: ${background_workspace};
            border: 1px solid ${border};
            border-radius: 8px;
        }
        QFrame#infoCallout {
            background-color: ${background_main_3};
            border: 1px solid ${border_hovered};
            border-radius: 8px;
        }
        QLabel#infoCalloutLabel {
            color: ${secondary};
            font-weight: 600;
        }
        QWidget#toolBar {
            background-color: ${background_main_2};
            border-bottom: 1px solid ${border};
        }
        QWidget#toolBar QPushButton, QWidget#zoomBar QPushButton {
            background-color: transparent;
            border: 1px solid transparent;
            border-radius: 5px;
            color: ${secondary_alternative};
            min-width: 0;
            min-height: 0;
            padding: 3px;
        }
        QWidget#toolBar QPushButton:hover, QWidget#zoomBar QPushButton:hover {
            background-color: ${neutral};
            border-color: ${border_hovered};
            color: ${secondary_hovered};
        }
        QWidget#toolBar QPushButton:checked, QWidget#zoomBar QPushButton:pressed {
            background-color: ${primary};
            border-color: ${primary_pressed};
            color: ${primary_foreground};
        }
        QWidget#toolBar QPushButton:disabled, QWidget#zoomBar QPushButton:disabled {
            background-color: transparent;
            border-color: transparent;
            color: ${secondary_disabled};
        }
        QWidget#toolSettingsPanel {
            background-color: ${background_main_2};
            border-bottom: 1px solid ${border};
        }
        QGroupBox {
            background-color: ${background_main_2};
            border: 1px solid ${border};
            border-radius: 6px;
            margin-top: 14px;
            padding: 14px 10px 10px 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 10px;
            padding: 0 5px;
            color: ${secondary_alternative};
            background-color: ${background_main_2};
        }
        QPushButton {
            background-color: ${neutral};
            border: 1px solid ${border};
            border-radius: 6px;
            color: ${secondary};
            padding: 6px 12px;
            min-width: 60px;
            min-height: 24px;
        }
        QPushButton:hover {
            background-color: ${neutral_hovered};
            border-color: ${border_hovered};
            color: ${secondary_hovered};
        }
        QPushButton:pressed {
            background-color: ${neutral_pressed};
            border-color: ${border_pressed};
            color: ${secondary_pressed};
        }
        QPushButton:disabled {
            background-color: ${neutral_disabled};
            border-color: ${border_disabled};
            color: ${secondary_disabled};
        }
        QPushButton:focus, QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
        QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
            border: 1px solid ${primary};
        }
        QLineEdit, QTextEdit, QPlainTextEdit {
            background-color: ${background_main_1};
            border: 1px solid ${border};
            border-radius: 6px;
            padding: 5px 7px;
            color: ${secondary};
        }
        QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {
            background-color: ${background_main_2};
            border-color: ${border_disabled};
            color: ${secondary_disabled};
        }
        QComboBox, QSpinBox, QDoubleSpinBox {
            background-color: ${background_main_1};
            border: 1px solid ${border};
            border-radius: 6px;
            padding: 5px 8px;
            color: ${secondary};
            min-width: 6em;
        }
        QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
            border-color: ${border_hovered};
        }
        QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
            background-color: ${background_main_2};
            border-color: ${border_disabled};
            color: ${secondary_disabled};
        }
        QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button,
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
            subcontrol-origin: padding;
            width: 20px;
            border-left: 1px solid ${border};
            background-color: ${background_main_3};
        }
        QComboBox::drop-down {
            subcontrol-position: top right;
            border-top-right-radius: 6px;
            border-bottom-right-radius: 6px;
        }
        QComboBox::down-arrow {
            image: url("${combo_arrow_down}");
            width: 10px;
            height: 10px;
        }
        QSpinBox::up-button, QDoubleSpinBox::up-button {
            subcontrol-position: top right;
            height: 13px;
            border-top-right-radius: 6px;
            border-bottom: 1px solid ${border};
        }
        QSpinBox::down-button, QDoubleSpinBox::down-button {
            subcontrol-position: bottom right;
            height: 13px;
            border-bottom-right-radius: 6px;
        }
        QSpinBox::up-button:hover, QSpinBox::down-button:hover,
        QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
            background-color: ${neutral_hovered};
        }
        QSpinBox::up-button:pressed, QSpinBox::down-button:pressed,
        QDoubleSpinBox::up-button:pressed, QDoubleSpinBox::down-button:pressed {
            background-color: ${neutral_pressed};
        }
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
            image: url("${spin_arrow_up}");
            width: 8px;
            height: 8px;
        }
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
            image: url("${spin_arrow_down}");
            width: 8px;
            height: 8px;
        }
        QComboBox QAbstractItemView {
            background-color: ${background_main_1};
            border: 1px solid ${border};
            border-radius: 6px;
            color: ${secondary};
            selection-background-color: ${primary};
            selection-color: ${primary_foreground};
            outline: none;
        }
        QListWidget, QTreeWidget, QTableWidget, QTableView, QTreeView {
            background-color: ${background_main_1};
            alternate-background-color: ${background_main_2};
            border: 1px solid ${border};
            border-radius: 6px;
            color: ${secondary};
            outline: none;
        }
        QListWidget::item, QTreeView::item {
            padding: 4px 6px;
            border-radius: 4px;
        }
        QListWidget::item:selected, QTreeView::item:selected, QTableView::item:selected {
            background-color: ${primary};
            color: ${primary_foreground};
        }
        QTabWidget::pane {
            border: 1px solid ${border};
            border-radius: 6px;
            top: -1px;
            background-color: ${background_main_2};
        }
        QTabBar::tab {
            background: ${background_tabbar};
            border: 1px solid ${border};
            border-bottom-color: ${border};
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            min-width: 8ex;
            padding: 7px 12px;
            color: ${secondary_alternative};
        }
        QTabBar::tab:hover {
            background: ${neutral};
            color: ${secondary_hovered};
        }
        QTabBar::tab:selected {
            background: ${background_main_2};
            color: ${secondary_hovered};
            border-color: ${border_hovered};
            border-bottom-color: ${background_main_2};
        }
        QHeaderView::section {
            background-color: ${background_main_3};
            padding: 5px 8px;
            border: 1px solid ${border};
            color: ${secondary};
        }
        QScrollBar:vertical {
            border: none;
            background: ${background_main_2};
            width: 12px;
            margin: 2px;
        }
        QScrollBar::handle:vertical {
            background: ${neutral};
            border-radius: 5px;
            min-height: 20px;
        }
        QScrollBar::handle:vertical:hover {
            background: ${neutral_hovered};
        }
        QScrollBar:horizontal {
            border: none;
            background: ${background_main_2};
            height: 12px;
            margin: 2px;
        }
        QScrollBar::handle:horizontal {
            background: ${neutral};
            border-radius: 5px;
            min-width: 20px;
        }
        QScrollBar::handle:horizontal:hover {
            background: ${neutral_hovered};
        }
        QScrollBar::add-line, QScrollBar::sub-line {
            width: 0;
            height: 0;
            border: none;
            background: none;
        }
        QCheckBox {
            color: ${secondary};
            spacing: 8px;
        }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border: 1px solid ${border};
            border-radius: 4px;
            background-color: ${background_main_1};
        }
        QCheckBox::indicator:hover {
            border-color: ${border_hovered};
            background-color: ${background_main_3};
        }
        QCheckBox::indicator:checked {
            background-color: ${primary};
            border-color: ${primary};
            image: url("${checkbox_tick}");
        }
        QCheckBox::indicator:checked:hover {
            background-color: ${primary_hovered};
            border-color: ${primary_hovered};
            image: url("${checkbox_tick}");
        }
        QCheckBox::indicator:disabled {
            border-color: ${border_disabled};
            background-color: ${neutral_disabled};
        }
        QCheckBox::indicator:checked:disabled {
            background-color: ${primary_disabled};
            border-color: ${border_disabled};
            image: url("${checkbox_tick}");
        }
        QRadioButton {
            color: ${secondary};
            spacing: 8px;
        }
        QRadioButton::indicator {
            width: 16px;
            height: 16px;
            border: 1px solid ${border};
            border-radius: 8px;
            background-color: ${background_main_1};
        }
        QRadioButton::indicator:hover {
            border-color: ${border_hovered};
        }
        QRadioButton::indicator:checked {
            background-color: ${primary};
            border: 4px solid ${background_main_1};
        }
        QProgressBar {
            background-color: ${background_main_1};
            border: 1px solid ${border};
            border-radius: 6px;
            color: ${secondary};
            text-align: center;
            min-height: 16px;
        }
        QProgressBar::chunk {
            background-color: ${primary};
            border-radius: 5px;
        }
        QSlider::groove:horizontal {
            background-color: ${background_main_1};
            border: 1px solid ${border};
            border-radius: 4px;
            height: 6px;
        }
        QSlider::sub-page:horizontal {
            background-color: ${primary};
            border-radius: 4px;
        }
        QSlider::handle:horizontal {
            background-color: ${secondary_hovered};
            border: 1px solid ${primary};
            border-radius: 7px;
            width: 14px;
            height: 14px;
            margin: -5px 0;
        }
        QSlider::handle:horizontal:hover {
            background-color: ${primary_hovered};
        }
        QMenu {
            background-color: ${background_main_1};
            border: 1px solid ${border};
            border-radius: 6px;
            color: ${secondary};
        }
        QMenu::item {
            padding: 6px 24px 6px 12px;
        }
        QMenu::item:selected {
            background-color: ${primary};
            color: ${primary_foreground};
        }
        QSplitter::handle {
            background-color: ${background_workspace};
        }
        QSplitter::handle:hover {
            background-color: ${border};
        }
    """).substitute(c)
    )


# ---------------------------------------------------------------------------
# Reusable button factories
# ---------------------------------------------------------------------------


def make_primary_button(text: str = "Calculate", max_width: int = 220) -> QPushButton:
    """Return the standard primary action button used across all sub-interfaces.

    Use *text* to override the default label (e.g. 'Convert').
    """
    btn = QPushButton(text)
    btn.setMinimumHeight(50)
    btn.setMaximumWidth(max_width)
    decorate_action_button(btn, action_for_text(text), icon_size=15)
    btn.setStyleSheet(
        "QPushButton { font-size: 15px; font-weight: bold;"
        f" background-color: {QLEMENTINE_DARK['primary']};"
        f" color: {QLEMENTINE_DARK['primary_foreground']};"
        " border-radius: 6px; border: none; }"
        f"QPushButton:hover {{ background-color: {QLEMENTINE_DARK['primary_hovered']}; }}"
        f"QPushButton:pressed {{ background-color: {QLEMENTINE_DARK['primary_pressed']}; }}"
        f"QPushButton:disabled {{ background-color: {QLEMENTINE_DARK['primary_disabled']};"
        f" color: {QLEMENTINE_DARK['secondary_disabled']}; }}"
    )
    return btn


def make_stop_button(max_width: int = 120) -> QPushButton:
    """Return the standard Stop button, initially disabled.

    The caller enables it when a computation is in progress and disables it
    again on completion or cancellation.
    """
    btn = QPushButton("Stop")
    btn.setMinimumHeight(50)
    btn.setMaximumWidth(max_width)
    btn.setEnabled(False)
    decorate_action_button(btn, "stop", icon_size=15)
    btn.setStyleSheet(
        "QPushButton { font-size: 15px; font-weight: bold;"
        f" background-color: {QLEMENTINE_DARK['error']};"
        f" color: {QLEMENTINE_DARK['status_foreground']};"
        " border-radius: 6px; border: none; }"
        "QPushButton:hover { background-color: #f47c83; }"
        "QPushButton:pressed { background-color: #cf5f66; }"
        f"QPushButton:disabled {{ background-color: {QLEMENTINE_DARK['neutral_disabled']};"
        f" color: {QLEMENTINE_DARK['secondary_disabled']}; }}"
    )
    return btn


def apply_module_title(label: QLabel) -> QLabel:
    """Apply the standard large title treatment used in module side panels."""
    label.setObjectName("moduleTitle")
    label.setStyleSheet("")
    return label


def apply_panel_title(label: QLabel) -> QLabel:
    """Apply the standard title treatment for visualization/result panels."""
    label.setObjectName("panelTitle")
    label.setStyleSheet("")
    return label


def apply_subtle_text(label: QLabel) -> QLabel:
    """Apply subdued secondary text styling."""
    label.setObjectName("subtleText")
    label.setStyleSheet("")
    return label


def apply_preview_panel(widget: QWidget) -> QWidget:
    """Apply the standard framed preview surface style."""
    widget.setObjectName("previewPanel")
    widget.setStyleSheet("")
    return widget


def apply_preview_placeholder(label: QLabel) -> QLabel:
    """Apply the standard empty-state preview label style."""
    label.setObjectName("previewPlaceholder")
    label.setStyleSheet("")
    return label


def apply_framed_preview_placeholder(label: QLabel) -> QLabel:
    """Apply preview-surface styling directly to a placeholder label."""
    c = QLEMENTINE_DARK
    label.setStyleSheet(
        "QLabel {"
        f" background-color: {c['background_workspace']};"
        f" border: 1px solid {c['border']};"
        " border-radius: 8px;"
        f" color: {c['secondary_alternative']};"
        " font-size: 14px;"
        " padding: 24px;"
        "}"
    )
    return label


def apply_info_callout(frame: QFrame, label: QLabel | None = None) -> QFrame:
    """Apply a quiet informational callout style to *frame* and optional *label*."""
    frame.setObjectName("infoCallout")
    frame.setStyleSheet("")
    if label is not None:
        label.setObjectName("infoCalloutLabel")
        label.setStyleSheet("")
    return frame


def add_run_row(layout, calc_btn: QPushButton, stop_btn: QPushButton) -> None:
    """Append a horizontal row containing *calc_btn* and *stop_btn* to *layout*."""
    row = QHBoxLayout()
    row.addWidget(calc_btn)
    row.addWidget(stop_btn)
    row.addStretch()
    layout.addLayout(row)
