"""PySide6 GUI entrypoint for MIDI to OSC Converter."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QObject, QSettings, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QShortcut,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QPlainTextEdit,
    QWidget,
    QFileDialog,
    QMessageBox,
)

from midi2osc.config import example_config_text, parse_config
from midi2osc.converter import MidiPortError, run_from_config
from midi2osc.logging_utils import (
    LOG_KIND_STATUS,
    STYLE_DEFAULT,
    STYLE_DEFAULT_STATUS,
    STYLE_MAPPED,
    STYLE_MIDI_IN,
    STYLE_MUTED,
    STYLE_UNMAPPED,
    log_status,
    record_log_kind,
    record_routed_tokens,
    setup_logging,
)

logger = logging.getLogger("midi2osc")

LOG_FLUSH_MS = 50
LOG_BUFFER_MAX = 500
LOG_FLUSH_MAX_LINES = 80
LOG_MIDI_MAX_PER_FLUSH = 25
LOG_MAX_BLOCKS = 1000
ENGINE_JOIN_TIMEOUT_S = 2.0
ENGINE_REOPEN_PAUSE_MS = 150


def app_icon() -> QIcon:
    """Load the bundled app icon, empty if it is missing."""
    # PyInstaller one-file builds unpack data files into sys._MEIPASS.
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))
    icon_path = base / "midi2osc" / "assets" / "icon.png"
    return QIcon(str(icon_path)) if icon_path.exists() else QIcon()


def _char_format(color: str, *, bold: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    return fmt


class QtLogEmitter(QObject):
    """Bridge logging records onto the Qt event loop."""

    record_emitted = Signal(object)


class QtLogHandler(logging.Handler):
    """Thread-safe logging handler that emits LogRecord objects to Qt."""

    def __init__(self, emitter: QtLogEmitter) -> None:
        super().__init__()
        self.emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.emitter.record_emitted.emit(record)
        except Exception:
            self.handleError(record)


def _plain_log_record(message: str, level: int = logging.INFO) -> logging.LogRecord:
    """Build a LogRecord that only carries a plain message (no routed_msg)."""
    return logging.LogRecord(
        name="midi2osc",
        level=level,
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=None,
    )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("MIDI to OSC Converter")
        self.setWindowIcon(app_icon())
        self.resize(800, 520)
        self.setMinimumSize(400, 300)

        self.current_thread: threading.Thread | None = None
        self.stop_event: threading.Event | None = None
        self._pending_engine_path: Path | None = None
        self._engine_start_timer = QTimer(self)
        self._engine_start_timer.setSingleShot(True)
        self._engine_start_timer.timeout.connect(self._launch_pending_engine)
        # Owned by the window so mute survives config reloads; never persisted,
        # so the app always starts live.
        self.mute_event = threading.Event()
        self.active_config_path: Path | None = None
        self._log_buffer: deque[logging.LogRecord] = deque(maxlen=LOG_BUFFER_MAX)
        self._midi_log_pending = 0
        self._midi_log_dropped = 0
        self._fmt_time = _char_format("#555555")
        self._fmt_body = _char_format("#e0e0e0")
        self._fmt_midi_in = _char_format("#4CAF50", bold=True)
        self._fmt_mapped = _char_format("#00E676", bold=True)
        self._fmt_unmapped = _char_format("#888888", bold=True)
        self._fmt_default = _char_format("#FFB74D")
        self._fmt_info = _char_format("#29B6F6")
        self._fmt_error = _char_format("#FF5252", bold=True)
        self._fmt_muted = _char_format("#CE93D8", bold=True)
        self._routed_style_map = {
            STYLE_MIDI_IN: self._fmt_midi_in,
            STYLE_MAPPED: self._fmt_mapped,
            STYLE_UNMAPPED: self._fmt_unmapped,
            STYLE_DEFAULT_STATUS: self._fmt_default,
            STYLE_DEFAULT: self._fmt_body,
            STYLE_MUTED: self._fmt_muted,
        }

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setSpacing(4)
        layout.setContentsMargins(10, 8, 10, 8)

        title = QLabel("MIDI TO OSC CONVERTER")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin-top: 2px;")
        layout.addWidget(title)

        subtitle = QLabel("High-Performance Bridge for Live Performance")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #888888; font-size: 12px; margin-bottom: 4px;")
        layout.addWidget(subtitle)

        action_buttons_bar = QHBoxLayout()
        action_buttons_bar.setSpacing(6)
        action_buttons_bar.setContentsMargins(0, 0, 0, 2)

        self.btn_open = QPushButton("Open...")
        self.btn_open.setToolTip("Open a mapping configuration file")
        self.btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open.setStyleSheet(self._button_style())
        self.btn_open.clicked.connect(self.browse_config_file)
        action_buttons_bar.addWidget(self.btn_open)

        self.btn_edit = QPushButton("Edit")
        self.btn_edit.setToolTip("Open active config file in the default system text editor")
        self.btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit.setStyleSheet(self._button_style())
        self.btn_edit.clicked.connect(self.open_config_file)
        action_buttons_bar.addWidget(self.btn_edit)

        self.btn_reload = QPushButton("Reload")
        self.btn_reload.setToolTip("Reload current configuration file to apply changes")
        self.btn_reload.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reload.setStyleSheet(self._button_style())
        self.btn_reload.clicked.connect(self.reload_config)
        action_buttons_bar.addWidget(self.btn_reload)

        self.btn_new_template = QPushButton("New Template")
        self.btn_new_template.setToolTip("Create a new example mapping configuration file")
        self.btn_new_template.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_new_template.setStyleSheet(self._button_style())
        self.btn_new_template.clicked.connect(self.create_new_template)
        action_buttons_bar.addWidget(self.btn_new_template)

        action_buttons_bar.addStretch()

        self.btn_mute = QPushButton("Mute OSC")
        self.btn_mute.setToolTip(
            "Stop sending OSC while still logging incoming MIDI (Ctrl+M)"
        )
        self.btn_mute.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mute.setCheckable(True)
        self.btn_mute.setStyleSheet(self._button_style())
        self.btn_mute.toggled.connect(self._on_mute_toggled)
        action_buttons_bar.addWidget(self.btn_mute)

        mute_shortcut = QShortcut(QKeySequence("Ctrl+M"), self)
        mute_shortcut.activated.connect(self.btn_mute.toggle)

        layout.addLayout(action_buttons_bar)

        config_label = QLabel("Config File:")
        config_label.setStyleSheet(
            "color: #aaaaaa; font-size: 12px; font-weight: bold; margin-top: 2px;"
        )
        layout.addWidget(config_label)

        self.input_config_path = QLineEdit()
        self.input_config_path.setReadOnly(True)
        self.input_config_path.setPlaceholderText("No configuration file selected...")
        self.input_config_path.setStyleSheet(
            """
            QLineEdit {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 4px 6px;
                font-size: 12px;
                margin-bottom: 2px;
            }
            """
        )
        layout.addWidget(self.input_config_path)

        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setUndoRedoEnabled(False)
        self.log_area.setMaximumBlockCount(LOG_MAX_BLOCKS)
        self.log_area.setStyleSheet(
            """
            QPlainTextEdit {
                background-color: #121212;
                color: #e0e0e0;
                font-family: "Menlo", "Monaco", "Courier New", monospace;
                font-size: 12px;
                border: 1px solid #2a2a2a;
                border-radius: 6px;
                padding: 4px;
            }
            """
        )
        layout.addWidget(self.log_area)

        self._log_emitter = QtLogEmitter()
        self._log_emitter.record_emitted.connect(self._enqueue_log_line)
        self._log_handler = QtLogHandler(self._log_emitter)
        setup_logging(handler=self._log_handler)

        self._log_timer = QTimer(self)
        self._log_timer.setInterval(LOG_FLUSH_MS)
        self._log_timer.timeout.connect(self._flush_log_buffer)
        self._log_timer.start()

        # Restore the last config if it still exists; otherwise wait for the user.
        settings = QSettings("midi2osc", "MIDI2OSC")
        last_path_str = settings.value("last_config_path", "")
        last_file = Path(str(last_path_str)) if last_path_str else None

        if last_file and last_file.exists():
            self.load_config(last_file)
        else:
            log_status("Welcome to MIDI2OSC!")
            log_status(
                "Please open a configuration file ('Open...') "
                "or create a new one ('New Template')."
            )

    def _button_style(self) -> str:
        return """
            QPushButton {
                background-color: #383838;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                border-color: #00E676;
            }
            QPushButton:pressed {
                background-color: #222222;
                border-color: #333333;
            }
            QPushButton:checked {
                background-color: #7f1d1d;
                border-color: #FF5252;
                color: #ffffff;
                font-weight: bold;
            }
            QPushButton:checked:hover {
                background-color: #991b1b;
                border-color: #FF5252;
            }
        """

    def _on_mute_toggled(self, muted: bool) -> None:
        """Toggle OSC output without restarting the converter thread."""
        if muted:
            self.mute_event.set()
            self.btn_mute.setText("MUTED - click to unmute")
            log_status("OSC output: MUTED")
        else:
            self.mute_event.clear()
            self.btn_mute.setText("Mute OSC")
            log_status("OSC output: live")

    def browse_config_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Mapping Configuration",
            "",
            "Mapping Files (*.mapping.txt);;Text Files (*.txt);;All Files (*)",
        )
        if file_path:
            self.load_config(Path(file_path))

    def open_config_file(self) -> None:
        """Open the currently active config file in the default text editor."""
        if not self.active_config_path or not self.active_config_path.exists():
            QMessageBox.warning(
                self,
                "No Config File",
                "No valid configuration file is currently selected to edit.",
            )
            return

        file_str = str(self.active_config_path.resolve())

        try:
            if sys.platform == "darwin":
                subprocess.run(["open", file_str], check=True)
            elif sys.platform == "win32":
                os.startfile(file_str)  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", file_str], check=True)
            log_status("Opened '%s' in external text editor.", self.active_config_path.name)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Error Opening File",
                f"Could not open file in system editor:\n{exc}",
            )

    def reload_config(self) -> None:
        """Reload the currently active config file."""
        if not self.active_config_path or not self.active_config_path.exists():
            QMessageBox.warning(
                self,
                "No Config File",
                "No valid configuration file is currently selected to reload.",
            )
            return

        log_status("Reloading active config: %s", self.active_config_path.name)
        self.load_config(self.active_config_path)

    def create_new_template(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Create New Mapping Template",
            "default.mapping.txt",
            "Mapping Files (*.mapping.txt);;Text Files (*.txt)",
        )
        if file_path:
            target_path = Path(file_path)
            try:
                target_path.write_text(example_config_text(), encoding="utf-8")
                log_status("Created template at: %s", target_path.name)
                self.load_config(target_path)
            except Exception as exc:
                QMessageBox.critical(self, "Error", f"Failed to create template: {exc}")

    def load_config(self, config_path: Path) -> None:
        self.active_config_path = config_path
        self.input_config_path.setText(str(config_path.resolve()))

        settings = QSettings("midi2osc", "MIDI2OSC")
        settings.setValue("last_config_path", str(config_path.resolve()))

        log_status("Loading configuration: %s", config_path.name)
        self.start_engine(config_path)

    def _enqueue_log_line(self, record: logging.LogRecord) -> None:
        if getattr(record, "routed_msg", None) is not None:
            self._midi_log_pending += 1
            if self._midi_log_pending > LOG_MIDI_MAX_PER_FLUSH:
                self._midi_log_dropped += 1
                return
        self._log_buffer.append(record)

    def _flush_log_buffer(self) -> None:
        dropped = self._midi_log_dropped
        self._midi_log_dropped = 0
        self._midi_log_pending = 0
        if dropped:
            self._log_buffer.append(
                _plain_log_record(f"… dropped {dropped} MIDI log lines")
            )

        if not self._log_buffer:
            return

        cursor = self.log_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_area.setUpdatesEnabled(False)
        try:
            flushed = 0
            while self._log_buffer and flushed < LOG_FLUSH_MAX_LINES:
                self._insert_log_line(cursor, self._log_buffer.popleft())
                flushed += 1
        finally:
            self.log_area.setUpdatesEnabled(True)
        self.log_area.setTextCursor(cursor)
        self.log_area.ensureCursorVisible()

    def _insert_log_line(self, cursor: QTextCursor, record: logging.LogRecord) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        cursor.insertText(f"[{timestamp}] ", self._fmt_time)

        tokens = record_routed_tokens(record)
        if tokens is not None:
            for style_key, text in tokens:
                fmt = self._routed_style_map.get(style_key, self._fmt_body)
                cursor.insertText(text, fmt)
            cursor.insertText("\n", self._fmt_body)
            return

        line_text = record.getMessage()
        if record.levelno >= logging.ERROR:
            base = self._fmt_error
        elif record.levelno >= logging.WARNING:
            base = self._fmt_default
        elif record_log_kind(record) == LOG_KIND_STATUS:
            base = self._fmt_info
        else:
            base = self._fmt_body
        cursor.insertText(line_text + "\n", base)

    def stop_current_engine(self) -> bool:
        """Signal the running converter thread to stop.

        Returns True if the previous engine is gone, False if it is still
        running after the join timeout.
        """
        if self.stop_event:
            self.stop_event.set()
        if self.current_thread and self.current_thread.is_alive():
            self.current_thread.join(timeout=ENGINE_JOIN_TIMEOUT_S)
            if self.current_thread.is_alive():
                logger.warning(
                    "Previous MIDI engine did not stop within %.1fs",
                    ENGINE_JOIN_TIMEOUT_S,
                )
                return False
        self.current_thread = None
        self.stop_event = None
        return True

    def start_engine(self, config_path: Path) -> None:
        if not config_path or not config_path.exists():
            logger.error("Invalid or missing config file.")
            return

        self._engine_start_timer.stop()
        had_running = self.current_thread is not None and self.current_thread.is_alive()
        self._pending_engine_path = config_path

        if not self.stop_current_engine():
            self._engine_start_timer.start(ENGINE_REOPEN_PAUSE_MS)
            return

        if had_running:
            # Let the OS MIDI backend release the previous handle without
            # freezing the UI thread.
            self._engine_start_timer.start(ENGINE_REOPEN_PAUSE_MS)
            return

        self._launch_pending_engine()

    def _launch_pending_engine(self) -> None:
        config_path = self._pending_engine_path
        if config_path is None:
            return

        if self.current_thread is not None and self.current_thread.is_alive():
            logger.warning("Previous MIDI engine still running; retrying...")
            self._engine_start_timer.start(ENGINE_REOPEN_PAUSE_MS)
            return

        self.stop_event = threading.Event()
        stop_event = self.stop_event

        def worker() -> None:
            try:
                config = parse_config(config_path)
                log_status("Active config: %s", config_path.name)
                log_status("Waiting for incoming MIDI events...")
                run_from_config(
                    config,
                    stop_event=stop_event,
                    reconnect=True,
                    mute_event=self.mute_event,
                )
            except MidiPortError as exc:
                logger.error("%s", exc)
            except Exception as exc:
                logger.error("Error: %s", exc)

        self.current_thread = threading.Thread(target=worker, daemon=True)
        self.current_thread.start()

    def closeEvent(self, event) -> None:  # noqa: N802
        """Clean shutdown when closing GUI window."""
        self._log_timer.stop()
        self._engine_start_timer.stop()
        self._pending_engine_path = None
        self.stop_current_engine()
        root = logging.getLogger("midi2osc")
        if self._log_handler in root.handlers:
            root.removeHandler(self._log_handler)
        event.accept()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("MIDI2OSC")
    app.setWindowIcon(app_icon())
    if sys.platform == "darwin":
        try:
            from Foundation import NSBundle  # type: ignore[import-not-found]

            bundle = NSBundle.mainBundle()
            info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
            if info is not None:
                info["CFBundleName"] = "MIDI2OSC"
        except ImportError:
            pass

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
