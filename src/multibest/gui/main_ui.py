# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
main_ui.py
==========

Top-level launcher for the MultiBEST Toolkit.

Instantiates every sub-module window eagerly (so PyInstaller can detect all
imports statically), embeds their control and visualization widgets into a
unified sidebar-driven shell, and wires per-module log signals to a shared
log panel at the bottom of the window.
"""

import functools
import html
import http.server
import multiprocessing
import os
import sys
import threading
import webbrowser
from dataclasses import dataclass, field
from string import Template

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QFontDatabase, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from multibest.gui.atomistic_to_continuum.window import AtomisticToContinuumWindow
from multibest.gui.ebsd_to_atomistic_mesh.window import EbsdToAtomisticMeshWindow
from multibest.gui.image_processing.window import ImageProcessingWindow
from multibest.gui.image_to_mesh.window import ImageToMeshWindow
from multibest.gui.input_convertor.window import InputConvertorWindow
from multibest.gui.mesh_modification.window import MeshModificationWindow
from multibest.gui.mesh_to_atomistic.window import MeshToAtomisticWindow
from multibest.gui.relaxation.window import RelaxationWindow
from multibest.gui.utils.general import get_base_dir
from multibest.gui.utils.ovito_scene import clear_ovito_scene
from multibest.gui.utils.theme import QLEMENTINE_DARK, apply_dark_theme, decorate_action_button, icon_for_action


def _ui_font(size: int) -> QFont:
    return QFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family(), size)


def _mono_font() -> QFont:
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)


def _get_docs_site_dir() -> str:
    """Return the built MkDocs site directory for bundled and dev launches."""
    bundled_site = os.path.join(get_base_dir(), "docs_site", "site")
    dev_site = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs_site", "site"))
    cwd_site = os.path.abspath(os.path.join(os.getcwd(), "docs_site", "site"))

    for path in (bundled_site, dev_site, cwd_site):
        if os.path.isdir(path):
            return path
    return bundled_site


@dataclass
class ModuleEntry:
    """Descriptor for a single MultiBEST sub-module.

    Bundling the class reference, sidebar label, and documentation paths in one
    place means that adding a new module only requires a single entry in
    ``_MODULES`` — the navigation sidebar, stacked widgets, and documentation
    button all derive their data from it automatically.
    """

    label: str
    window_cls: type
    doc_path: str = "index.html"
    """Root documentation page, relative to the docs-site root."""
    doc_tab_paths: dict[str, str] = field(default_factory=dict)
    """Per-tab page overrides, keyed by the tab label shown in the GUI."""


# Module registry: order determines sidebar position and stack index.
_MODULES = [
    ModuleEntry("Image Processing", ImageProcessingWindow, doc_path="Image_Processing_Documentation.html"),
    ModuleEntry("Image to Mesh", ImageToMeshWindow, doc_path="Image_to_Mesh_Documentation.html"),
    ModuleEntry("Mesh Modification", MeshModificationWindow, doc_path="Mesh_Modification_Documentation.html"),
    ModuleEntry("Mesh to Atomistic", MeshToAtomisticWindow, doc_path="Mesh_to_Atomistic_Documentation.html"),
    ModuleEntry(
        "Relaxation",
        RelaxationWindow,
        doc_path="Relaxation_Module_Documentation.html",
        doc_tab_paths={
            "GFN-xTB": "Relaxation_Module_Documentation.html#methodology-1-gfn2-xtb-relaxation",
            "SevenNet": "Relaxation_Module_Documentation.html#methodology-2-sevennet-relaxation",
        },
    ),
    ModuleEntry(
        "EBSD to Atomistic / Mesh",
        EbsdToAtomisticMeshWindow,
        doc_path="EBSD_Atomistic_Documentation.html",
        doc_tab_paths={
            "Stage 1 - EBSD preparation": "EBSD_Atomistic_Documentation.html#step-1-ebsd-processing-meshing",
            "Stage 2 - Mesh / atomistic": "EBSD_Atomistic_Documentation.html#step-3-atomistic-filling",
        },
    ),
    ModuleEntry(
        "Atomistic to Continuum",
        AtomisticToContinuumWindow,
        doc_path="Atomistic_to_Continuum_Documentation.html",
    ),
    ModuleEntry("Input Convertor", InputConvertorWindow, doc_path="Input_Convertor_Docs.html"),
]


class NavigationButton(QPushButton):
    """Checkable sidebar navigation button with a left-accent indicator when active."""

    def __init__(self, text: str, icon_name: str | None = None) -> None:
        super().__init__(text)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setMinimumHeight(50)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(_ui_font(11))

        c = QLEMENTINE_DARK
        self.setStyleSheet(
            Template("""
            QPushButton {
                text-align: left;
                padding-left: 20px;
                border: none;
                background-color: transparent;
                color: ${secondary_alternative};
                border-left: 4px solid transparent;
                border-radius: 0;
            }
            QPushButton:hover {
                background-color: ${background_main_3};
                color: ${secondary_hovered};
            }
            QPushButton:checked {
                background-color: ${background_main_4};
                color: ${secondary_hovered};
                border-left: 4px solid ${primary};
                font-weight: bold;
            }
        """).substitute(c)
        )


class HelpButton(QPushButton):
    """Sidebar button styled for secondary actions (e.g. Help / documentation)."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setMinimumHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(_ui_font(10))
        decorate_action_button(self, "help")
        c = QLEMENTINE_DARK
        self.setStyleSheet(
            Template("""
            QPushButton {
                text-align: left;
                padding-left: 20px;
                border: none;
                background-color: transparent;
                color: ${secondary_alternative};
                border-radius: 0;
            }
            QPushButton:hover {
                color: ${primary_hovered};
                font-weight: bold;
            }
        """).substitute(c)
        )


class ModuleHelpButton(QToolButton):
    """Compact in-module documentation affordance."""

    def __init__(self) -> None:
        super().__init__()
        self.setText("?")
        self.setFixedSize(30, 30)
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(_ui_font(11))
        self.setIcon(icon_for_action("help"))
        self.setIconSize(QSize(14, 14))
        self.setToolTip("Open documentation for this module")
        self.setAccessibleName("Open module documentation")
        c = QLEMENTINE_DARK
        self.setStyleSheet(
            Template("""
            QToolButton {
                color: ${secondary};
                background-color: transparent;
                border: 1px solid ${border};
                border-radius: 15px;
                font-weight: bold;
                padding: 0;
            }
            QToolButton:hover {
                color: ${secondary_hovered};
                background-color: ${background_main_3};
                border-color: ${primary};
            }
            QToolButton:pressed {
                background-color: ${background_main_1};
                border-color: ${primary_pressed};
            }
        """).substitute(c)
        )


class DocumentationServer:
    """
    Simple HTTP server to serve static documentation files from a local directory.
    Runs in a separate daemon thread.
    """

    def __init__(self, root_dir: str, start_port: int = 8000) -> None:
        self.root_dir = root_dir
        self.port = start_port
        self.server = None
        self.thread = None
        self.is_running = False

    def start(self) -> int | None:
        if self.is_running:
            return self.port

        class SilentRequestHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Prevent writing to sys.stderr which is None in PyInstaller GUI apps

        while self.port < 65535:
            try:
                handler = functools.partial(SilentRequestHandler, directory=self.root_dir)
                self.server = http.server.ThreadingHTTPServer(("", self.port), handler)
                self.server.daemon_threads = True
                self.is_running = True

                self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
                self.thread.start()

                print(f"Documentation server started at http://localhost:{self.port}")
                return self.port
            except OSError:
                self.port += 1

        print("Could not find a free port for documentation server.")
        return None

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.is_running = False

    def get_url(self) -> str | None:
        if self.is_running:
            return f"http://localhost:{self.port}/index.html"
        return None


class MultiBESTMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MultiBEST Toolkit")
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            self.resize(min(1600, avail.width() - 40), min(980, avail.height() - 60))
        else:
            self.resize(1600, 980)

        docs_path = _get_docs_site_dir()
        self.doc_server = DocumentationServer(docs_path)  # lazy-started on first use

        self._windows = [None] * len(_MODULES)
        self._module_help_buttons: list[QToolButton] = []

        # Central Widget
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Top Section: Sidebar + Content Splitter ---
        top_container = QWidget()
        top_layout = QHBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)

        # Sidebar
        c = QLEMENTINE_DARK
        self.sidebar = QFrame()
        self.sidebar.setStyleSheet(
            f"background-color: {c['background_main_2']}; border-right: 1px solid {c['border']};"
        )
        self.sidebar.setFixedWidth(250)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 20, 0, 20)
        sidebar_layout.setSpacing(10)

        app_title = QLabel("MultiBEST")
        app_title.setStyleSheet(
            f"color: {c['secondary_hovered']}; font-size: 22px; font-weight: bold; "
            "padding-left: 20px; margin-bottom: 20px;"
        )
        sidebar_layout.addWidget(app_title)

        self.nav_group: list[QPushButton] = []

        # Build nav buttons dynamically from the module registry
        self.nav_buttons: list[QPushButton] = []
        for i, entry in enumerate(_MODULES):
            btn = self._add_nav_btn(sidebar_layout, entry.label, i)
            self.nav_buttons.append(btn)

        sidebar_layout.addStretch()

        self.btn_help = HelpButton("Docs")
        self.btn_help.clicked.connect(self.open_documentation)
        sidebar_layout.addWidget(self.btn_help)

        footer = QLabel("v0.1.0")
        footer.setStyleSheet(f"color: {c['secondary_disabled']}; padding-left: 20px;")
        sidebar_layout.addWidget(footer)

        top_layout.addWidget(self.sidebar)

        # Horizontal Splitter for [Controls | Visualization]
        self.h_splitter = QSplitter(Qt.Orientation.Horizontal)

        self.content_area = QStackedWidget()
        self.content_area.setStyleSheet(f"background-color: {c['background_main_2']};")
        self.h_splitter.addWidget(self.content_area)

        self.viz_area = QStackedWidget()
        self.viz_area.setStyleSheet(f"background-color: {c['background_workspace']};")
        self.h_splitter.addWidget(self.viz_area)

        self.h_splitter.setSizes([480, 620])
        self.h_splitter.setCollapsible(0, False)
        self.h_splitter.setCollapsible(1, False)

        top_layout.addWidget(self.h_splitter)

        self.log_stack = QStackedWidget()
        self._last_log_was_progress: dict[int, bool] = {}

        # Instantiate every sub-module window and embed its widgets.
        for i, entry in enumerate(_MODULES):
            try:
                window = entry.window_cls()
                self._windows[i] = window

                control = window.get_control_widget()
                viz = window.get_visualization_widget()
                self._add_module_help_button(control, i)

                self.content_area.addWidget(control)
                self.viz_area.addWidget(viz)

                log_view = QTextEdit()
                log_view.setReadOnly(True)
                log_view.setFont(_mono_font())
                self.log_stack.addWidget(log_view)
                window.log_message.connect(lambda msg, idx=i: self.append_log(idx, msg))
                self.append_log(i, f"INFO: {entry.label} loaded.")

            except Exception as e:
                # Placeholder widgets keep the stacked-widget indices aligned on failure.
                ph = QLabel(f"Failed to load {entry.label}:\n{e}")
                ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
                ph.setStyleSheet(f"color: {c['secondary_disabled']}; font-size: 14px;")
                self.content_area.addWidget(ph)
                self.viz_area.addWidget(QLabel(""))

                log_view = QTextEdit()
                log_view.setReadOnly(True)
                log_view.setFont(_mono_font())
                self.log_stack.addWidget(log_view)
                self.append_log(i, f"ERROR: {e}")

        # --- Bottom Section: Logs ---
        self.log_container = QFrame()
        self.log_container.setStyleSheet(
            Template("""
            QFrame {
                background-color: ${background_main_2};
                border-top: 1px solid ${border};
            }
            QLabel {
                color: ${secondary_alternative};
                font-weight: bold;
                padding: 5px;
            }
            QTextEdit {
                background-color: ${background_main_1};
                color: ${secondary};
                border: 1px solid ${border};
                border-radius: 6px;
            }
        """).substitute(c)
        )
        log_layout = QVBoxLayout(self.log_container)
        log_layout.setContentsMargins(10, 5, 10, 10)

        log_header = QLabel("Interface Output / Parameters / Commands")
        log_layout.addWidget(log_header)
        log_layout.addWidget(self.log_stack)

        # Vertical splitter (top content + bottom logs)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(top_container)
        splitter.addWidget(self.log_container)
        splitter.setSizes([650, 250])
        splitter.setHandleWidth(8)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)

        main_layout.addWidget(splitter)

        # Select default module
        if self.nav_buttons:
            self.nav_buttons[0].setChecked(True)
        self.switch_view(0)

    def switch_view(self, index: int) -> None:
        clear_ovito_scene()
        self.content_area.setCurrentIndex(index)
        self.viz_area.setCurrentIndex(index)
        self.log_stack.setCurrentIndex(index)

    # ------------------------------------------------------------------
    # Log helpers
    # ------------------------------------------------------------------

    def append_log(self, index: int, message: str) -> None:
        log_view = self.log_stack.widget(index)
        if log_view is None:
            return
        is_progress = message.startswith("PROGRESS")
        c = QLEMENTINE_DARK
        if is_progress:
            color = c["info"]
            if self._last_log_was_progress.get(index):
                cursor = log_view.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                cursor.removeSelectedText()
                log_view.setTextCursor(cursor)
        elif message.startswith("ERROR"):
            color = c["error"]
        elif message.startswith("INFO"):
            color = c["success"]
        elif message.startswith("STDOUT"):
            color = c["secondary"]
        else:
            color = c["secondary_alternative"]
        self._last_log_was_progress[index] = is_progress
        log_view.append(f'<span style="color:{color}">{html.escape(message)}</span>')

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def _add_nav_btn(self, sidebar_layout, text: str, index: int) -> QPushButton:
        btn = NavigationButton(text)
        btn.clicked.connect(lambda checked=False, i=index: self.switch_view(i))
        sidebar_layout.addWidget(btn)
        self.nav_group.append(btn)
        return btn

    # ------------------------------------------------------------------
    # Documentation
    # ------------------------------------------------------------------

    def _start_documentation_server(self) -> bool:
        if self.doc_server.is_running:
            return True

        port = self.doc_server.start()
        if port:
            self.btn_help.setText(f"Docs (port {self.doc_server.port})")
            return True

        QMessageBox.critical(
            self,
            "Error",
            "Could not start documentation server.\nNo free ports found.",
        )
        return False

    def _get_module_doc_path(self, module_index: int) -> str:
        if module_index < 0 or module_index >= len(_MODULES):
            return "index.html"

        entry = _MODULES[module_index]
        path = entry.doc_path

        if not entry.doc_tab_paths:
            return path

        active_window = self._windows[module_index]
        if active_window is None:
            return path

        control_widget = active_window.get_control_widget()
        if not isinstance(control_widget, QTabWidget):
            return path

        tab_text = control_widget.tabText(control_widget.currentIndex())
        return entry.doc_tab_paths.get(tab_text, path)

    def open_documentation(self) -> None:
        if not self._start_documentation_server():
            return

        base_url = f"http://localhost:{self.doc_server.port}"
        webbrowser.open(f"{base_url}/index.html")

    def open_module_documentation(self, module_index: int) -> None:
        if not self._start_documentation_server():
            return

        base_url = f"http://localhost:{self.doc_server.port}"
        webbrowser.open(f"{base_url}/{self._get_module_doc_path(module_index)}")

    def _add_module_help_button(self, control_widget: QWidget, module_index: int) -> None:
        if isinstance(control_widget, QTabWidget):
            for tab_index in range(control_widget.count()):
                self._add_help_button_to_panel(control_widget.widget(tab_index), module_index)
            return

        self._add_help_button_to_panel(control_widget, module_index)

    def _add_help_button_to_panel(self, panel: QWidget, module_index: int) -> None:
        content = panel.widget() if isinstance(panel, QScrollArea) else panel
        if content is None or content.layout() is None:
            return

        layout = content.layout()
        help_button = ModuleHelpButton()
        help_button.clicked.connect(lambda checked=False, idx=module_index: self.open_module_documentation(idx))
        self._module_help_buttons.append(help_button)

        header = None
        first_item = layout.itemAt(0)
        if first_item is not None:
            widget = first_item.widget()
            if isinstance(widget, QLabel):
                header = widget
                layout.removeWidget(header)

        header_row = QWidget()
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 8)
        header_layout.setSpacing(10)

        if header is not None:
            header.setParent(header_row)
            header_style = header.styleSheet()
            for margin_rule in ("margin-bottom: 20px;", "margin-bottom: 12px;", "margin-bottom: 8px;"):
                header_style = header_style.replace(margin_rule, "")
            header.setStyleSheet(header_style)
            header_layout.addWidget(header, 1)
        else:
            header_layout.addStretch()

        header_layout.addWidget(help_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.insertWidget(0, header_row)

    def closeEvent(self, event) -> None:
        if self.doc_server:
            self.doc_server.stop()
        super().closeEvent(event)


if __name__ == "__main__":
    os.environ["PYTHONUTF8"] = "1"
    multiprocessing.freeze_support()

    from multibest.gui.utils.qt_bootstrap import force_x11_if_wayland

    force_x11_if_wayland()

    app = QApplication(sys.argv)
    apply_dark_theme(app)

    window = MultiBESTMainWindow()

    if os.environ.get("_PYI_SPLASH_IPC"):
        try:
            pyi_splash = __import__("pyi" + "_splash")
            pyi_splash.close()
        except Exception:
            # Running outside a PyInstaller bundle or with splash IPC already closed.
            _ = None

    window.show()

    sys.exit(app.exec())
