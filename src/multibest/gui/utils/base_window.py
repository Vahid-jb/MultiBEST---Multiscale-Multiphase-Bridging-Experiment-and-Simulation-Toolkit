# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
multibest.gui.utils/base_window.py
==============================

Thin base class for every MultiBEST sub-module GUI.

Centralises the boilerplate that was previously copy-pasted into each
sub-module: signal declaration, logger/runner wiring, run/stop helpers,
input validation, parameter-file writing, and the public interface
expected by :class:`MultiBESTMainWindow`.
"""

from __future__ import annotations

import os
import posixpath
from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from multibest.gui.utils.general import MultiBESTLogger, Runner


class BaseModuleWindow(QMainWindow):
    """Base class for all MultiBEST sub-module windows.

    Subclasses must:
    * Set ``self.control_widget`` and ``self.viz_widget`` before the end
      of ``__init__`` so that the main window can embed them.
    * Populate ``self._calc_btns`` and ``self._stop_btns`` with their
      Calculate / Stop button references so that :meth:`_set_running`
      works automatically.
    """

    log_message = Signal(str)

    def __init__(self) -> None:
        super().__init__()

        # Subclasses should set these to the widgets the main window embeds.
        self.control_widget: QWidget | None = None
        self.viz_widget: QWidget | None = None

        # Button bookkeeping — subclasses append to these.
        self._calc_btns: list[QPushButton] = []
        self._stop_btns: list[QPushButton] = []

        self.logger = MultiBESTLogger(self.log_message)
        self.runner = Runner(
            on_line=self.logger.handle_process_line,
        )

    # ------------------------------------------------------------------
    # Public interface used by MultiBESTMainWindow
    # ------------------------------------------------------------------

    def get_control_widget(self) -> QWidget:
        """Return the widget inserted into the main window's control area."""
        assert self.control_widget is not None, f"{type(self).__name__} must set self.control_widget in __init__"
        return self.control_widget

    def get_visualization_widget(self) -> QWidget:
        """Return the widget inserted into the main window's viz area."""
        assert self.viz_widget is not None, f"{type(self).__name__} must set self.viz_widget in __init__"
        return self.viz_widget

    def _build_split_layout(self) -> tuple[QHBoxLayout, QVBoxLayout]:
        """Create the standard left-control/right-preview module layout."""
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.left_panel_content = QWidget()
        left_layout = QVBoxLayout(self.left_panel_content)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(14)
        self.left_scroll.setWidget(self.left_panel_content)
        main_layout.addWidget(self.left_scroll, 1)
        return main_layout, left_layout

    # ------------------------------------------------------------------
    # Run / stop helpers
    # ------------------------------------------------------------------

    def _set_running(self, running: bool) -> None:
        """Toggle all registered Calculate / Stop buttons."""
        for btn in self._calc_btns:
            btn.setEnabled(not running)
        for btn in self._stop_btns:
            btn.setEnabled(running)

    def _stop_calculation(self) -> None:
        """Kill the active sub-process and reset button states."""
        self.runner.kill()
        self._set_running(False)
        self.logger.log_message("INFO", "Calculation stopped by user.")

    # ------------------------------------------------------------------
    # Shared validation helpers
    # ------------------------------------------------------------------

    def _validate_input_file(self, path: str) -> bool:
        """Return True if *path* is a non-empty, existing file."""
        if not path:
            self.logger.log_message("ERROR", "Please choose an input file first.")
            return False
        if not os.path.isfile(path):
            self.logger.log_message("ERROR", f"File not found:\n{path}")
            return False
        return True

    def _validate_output_dir(self, path: str, create: bool = True) -> bool:
        """Return True if *path* is a usable output directory.

        When *create* is True (default) the directory is created if missing.
        """
        if not path:
            self.logger.log_message("ERROR", "Please choose an output directory first.")
            return False
        if not os.path.isdir(path):
            if create:
                try:
                    os.makedirs(path, exist_ok=True)
                except Exception as e:
                    self.logger.log_message("ERROR", f"Failed to create output directory:\n{e}")
                    return False
            else:
                self.logger.log_message("ERROR", f"Output directory does not exist:\n{path}")
                return False
        return True

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _resolve_to_outdir(self, line_edit: QLineEdit, out_dir: str) -> str:
        """Return an absolute path, resolving a relative value against *out_dir*.

        If *line_edit* contains a relative path it is joined with *out_dir* and
        the widget is updated in-place.  The resolved (always absolute) path is
        returned so the caller can use it directly.
        """
        path = line_edit.text().strip()
        if path and not os.path.isabs(path):
            if "/" in out_dir and "\\" not in out_dir:
                path = posixpath.join(out_dir, path.replace("\\", "/"))
            else:
                path = os.path.join(out_dir, path)
            line_edit.setText(path)
        return path

    # ------------------------------------------------------------------
    # Write-params-and-run helper
    # ------------------------------------------------------------------

    def _write_param_file(self, param_file: str, params: dict) -> str:
        """Write *params* as ``key = value`` lines to *param_file*.

        Parameters
        ----------
        param_file:
            Absolute path to the parameter file to write.
        params:
            Key-value pairs written as ``key = value`` lines.

        Returns
        -------
        str
            The path that was written, so callers can pass it straight on.
        """
        self.logger.log_message("INFO", f"Writing parameter file: {param_file}")
        with open(param_file, "w", encoding="utf-8") as f:
            for k, v in params.items():
                f.write(f"{k} = {v}\n")
        return param_file

    def _write_and_run(
        self,
        param_file: str,
        params: dict,
        script_parts: tuple[str, ...],
        cwd: str,
        on_finished: Callable[[int, object], None],
        *,
        extra_args: list[str] | None = None,
    ) -> None:
        """Write *params* to *param_file* and launch the compute script.

        Parameters
        ----------
        param_file:
            Absolute path to the parameter file to write.
        params:
            Key-value pairs written as ``key = value`` lines.
        script_parts:
            Path components passed to :func:`get_script_path`,
            e.g. ``("XRD", "XRD-Kinematical.py")``.
        cwd:
            Working directory for the sub-process.
        on_finished:
            Callback invoked when the process exits.
        extra_args:
            Additional CLI arguments inserted *before* the param file path.
        """
        from multibest.gui.utils.general import get_script_path

        self._write_param_file(param_file, params)

        self._set_running(True)
        self.runner.on_finished_cb = on_finished

        script_path = get_script_path(*script_parts)

        args: list[str] = []
        if extra_args:
            args.extend(extra_args)
        args.append(param_file)

        self.runner.start(script_path, args=args, cwd=cwd)

    # ------------------------------------------------------------------
    # Finish-callback factory
    # ------------------------------------------------------------------

    def _make_finish_callback(
        self,
        name: str,
        plot_fn: Callable[[], None] | None = None,
    ) -> Callable[[int, object], None]:
        """Return a finish callback that logs and optionally plots.

        Parameters
        ----------
        name:
            Human-readable name for the computation (used in log messages).
        plot_fn:
            If provided, called on success to render results.
        """

        def _on_finished(exit_code: int, exit_status: object) -> None:
            self._set_running(False)
            if exit_code == 0:
                msg = f"{name} finished."
                if plot_fn is not None:
                    msg += " Plotting results..."
                self.logger.log_message("INFO", msg)
                if plot_fn is not None:
                    plot_fn()
            else:
                self.logger.log_message("ERROR", f"{name} failed with code {exit_code}.")

        return _on_finished
