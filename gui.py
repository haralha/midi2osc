"""PySide6 GUI entrypoint for MIDI to OSC Converter."""

import html
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QObject, QSettings
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QWidget,
    QFileDialog,
    QMessageBox,
)

from config import parse_config, EXAMPLE_CONFIG
from converter import run_converter, MidiPortError


class SignalStream(QObject):
    """Thread-safe redirection of stdout to PySide6 with line buffering."""

    text_written = Signal(str)

    def write(self, text):
        if text.strip():
            self.text_written.emit(text.strip())

    def flush(self):
        pass


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("MIDI to OSC Converter")
        self.resize(600, 520)
        self.setMinimumSize(600, 400)

        self.current_thread = None
        self.stop_event = None
        self.active_config_path = None

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        
        # Redusert spacing mellom elementene for en tettere layout
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(4)
        layout.setContentsMargins(10, 8, 10, 8)

        # Header Title
        title = QLabel("🎛️ MIDI TO OSC CONVERTER")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin-top: 2px;")
        layout.addWidget(title)

        subtitle = QLabel("High-Performance Bridge for Live Performance")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #888888; font-size: 12px; margin-bottom: 4px;")
        layout.addWidget(subtitle)

        # LINJE 1: Handlingsknapper
        action_buttons_bar = QHBoxLayout()
        action_buttons_bar.setSpacing(6)
        action_buttons_bar.setContentsMargins(0, 0, 0, 2)

        self.btn_open = QPushButton("📂 Open...")
        self.btn_open.setToolTip("Open a mapping configuration file")
        self.btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open.setStyleSheet(self._button_style())
        self.btn_open.clicked.connect(self.browse_config_file)
        action_buttons_bar.addWidget(self.btn_open)

        self.btn_edit = QPushButton("✏️ Edit")
        self.btn_edit.setToolTip("Open active config file in the default system text editor")
        self.btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit.setStyleSheet(self._button_style())
        self.btn_edit.clicked.connect(self.open_config_file)
        action_buttons_bar.addWidget(self.btn_edit)

        self.btn_reload = QPushButton("🔄 Reload")
        self.btn_reload.setToolTip("Reload current configuration file to apply changes")
        self.btn_reload.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reload.setStyleSheet(self._button_style())
        self.btn_reload.clicked.connect(self.reload_config)
        action_buttons_bar.addWidget(self.btn_reload)

        self.btn_new_template = QPushButton("➕ New Template")
        self.btn_new_template.setToolTip("Create a new example mapping configuration file")
        self.btn_new_template.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_new_template.setStyleSheet(self._button_style())
        self.btn_new_template.clicked.connect(self.create_new_template)
        action_buttons_bar.addWidget(self.btn_new_template)

        action_buttons_bar.addStretch()  # Skyver knappene til venstre
        layout.addLayout(action_buttons_bar)

        # LINJE 2: Config File Tittel
        config_label = QLabel("Config File:")
        config_label.setStyleSheet("color: #aaaaaa; font-size: 12px; font-weight: bold; margin-top: 2px;")
        layout.addWidget(config_label)

        # LINJE 3: Filbane under tittelen
        self.input_config_path = QLineEdit()
        self.input_config_path.setReadOnly(True)
        self.input_config_path.setPlaceholderText("No configuration file selected...")
        self.input_config_path.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 4px 6px;
                font-size: 12px;
                margin-bottom: 2px;
            }
        """)
        layout.addWidget(self.input_config_path)

        # Log Area
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.document().setMaximumBlockCount(1000)
        self.log_area.setStyleSheet("""
            QTextEdit {
                background-color: #121212;
                color: #e0e0e0;
                font-family: "Menlo", "Monaco", "Courier New", monospace;
                font-size: 12px;
                border: 1px solid #2a2a2a;
                border-radius: 6px;
                padding: 4px;
            }
        """)
        layout.addWidget(self.log_area)

        # Redirect stdout
        self.stream = SignalStream()
        self.stream.text_written.connect(self.append_log_line)
        sys.stdout = self.stream

        # Restore last used config file, or fallback to default.mapping.txt
        settings = QSettings("midi2osc", "MIDI2OSC")
        last_path_str = settings.value("last_config_path", "")

        last_file = Path(last_path_str) if last_path_str else None
        default_file = Path("default.mapping.txt")

        if last_file and last_file.exists():
            self.load_config(last_file)
        elif default_file.exists():
            self.load_config(default_file)
        else:
            print("ℹ Please select a config file using 'Open...' or create a 'New Template'.")

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
        """

    def browse_config_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Mapping Configuration",
            "",
            "Mapping Files (*.mapping.txt);;Text Files (*.txt);;All Files (*)",
        )
        if file_path:
            self.load_config(Path(file_path))

    def open_config_file(self):
        """Open the currently active config file in the default text editor."""
        if not self.active_config_path or not self.active_config_path.exists():
            QMessageBox.warning(
                self,
                "No Config File",
                "No valid configuration file is currently selected to edit."
            )
            return

        file_str = str(self.active_config_path.resolve())

        try:
            if sys.platform == "darwin":  # macOS
                subprocess.run(["open", file_str], check=True)
            elif sys.platform == "win32":  # Windows
                os.startfile(file_str)  # type: ignore[attr-defined]
            else:  # Linux / Unix
                subprocess.run(["xdg-open", file_str], check=True)
            
            print(f"📄 Opened '{self.active_config_path.name}' in external text editor.")
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error Opening File",
                f"Could not open file in system editor:\n{e}"
            )

    def reload_config(self):
        """Reload the currently active config file."""
        if not self.active_config_path or not self.active_config_path.exists():
            QMessageBox.warning(
                self,
                "No Config File",
                "No valid configuration file is currently selected to reload."
            )
            return

        print(f"\n🔄 Reloading active config: {self.active_config_path.name}")
        self.load_config(self.active_config_path)

    def create_new_template(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Create New Mapping Template",
            "default.mapping.txt",
            "Mapping Files (*.mapping.txt);;Text Files (*.txt)",
        )
        if file_path:
            target_path = Path(file_path)
            try:
                target_path.write_text(EXAMPLE_CONFIG.strip(), encoding="utf-8")
                print(f"✔ Created template at: {target_path.name}")
                self.load_config(target_path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create template: {e}")

    def load_config(self, config_path: Path):
        self.active_config_path = config_path
        self.input_config_path.setText(str(config_path.resolve()))

        # Save last used configuration path to persistent settings
        settings = QSettings("midi2osc", "MIDI2OSC")
        settings.setValue("last_config_path", str(config_path.resolve()))

        print(f"🔄 Loading configuration: {config_path.name}")
        self.start_engine(config_path)

    def append_log_line(self, line_text: str):
            timestamp = datetime.now().strftime("%H:%M:%S")
            safe_text = html.escape(line_text)

            formatted = safe_text
            if "MIDI IN:" in formatted:
                formatted = formatted.replace(
                    "MIDI IN:", "<span style='color: #4CAF50; font-weight: bold;'>MIDI IN:</span>"
                )
            # Sjekk for UNMAPPED FØR MAPPED slik at MAPPED ikke treffer inni ordet!
            if "UNMAPPED" in formatted:
                formatted = formatted.replace(
                    "UNMAPPED", "<span style='color: #888888; font-weight: bold;'>UNMAPPED</span>"
                )
            elif "MAPPED" in formatted:
                formatted = formatted.replace(
                    "MAPPED", "<span style='color: #00E676; font-weight: bold;'>MAPPED </span>"
                )
            if "DEFAULT" in formatted:
                formatted = formatted.replace(
                    "DEFAULT", "<span style='color: #FFB74D;'>DEFAULT</span>"
                )
            if any(k in formatted for k in ("Listening on MIDI", "Target OSC", "Creating", "Loading", "📄", "✔", "🔄")):
                formatted = f"<span style='color: #29B6F6;'>{formatted}</span>"
            if any(k in formatted for k in ("Error", "Invalid", "✖")):
                formatted = f"<span style='color: #FF5252; font-weight: bold;'>{formatted}</span>"

            html_line = f"<span style='color: #555555;'>[{timestamp}]</span> {formatted}"

            cursor = self.log_area.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.log_area.setTextCursor(cursor)
            self.log_area.insertHtml(html_line + "<br>")
            self.log_area.ensureCursorVisible()

    def stop_current_engine(self):
        """Signal the running converter thread to stop cleanly."""
        if self.stop_event:
            self.stop_event.set()
        if self.current_thread and self.current_thread.is_alive():
            self.current_thread.join(timeout=0.5)

    def start_engine(self, config_path: Path):
        if not config_path or not config_path.exists():
            print("✖ Invalid or missing config file.")
            return

        # Stop existing background worker first
        self.stop_current_engine()

        self.stop_event = threading.Event()

        def worker():
            try:
                config = parse_config(config_path)

                print(f"✔ Active config: {config_path.name}")
                print(f"Listening on MIDI: '{config['midi_port']}'")
                print(f"Target OSC: {config['ip']}:{config['port']}")
                print(f"Convert Unmapped: {config.get('convert_unmapped', True)}")
                print("Waiting for incoming MIDI events...")

                run_converter(
                    config["midi_port"],
                    config["ip"],
                    config["port"],
                    config["mappings"],
                    stop_event=self.stop_event,
                    convert_unmapped=config.get("convert_unmapped", True),
                )
            except MidiPortError:
                # Error and available ports already printed by run_converter
                pass
            except Exception as e:
                print(f"✖ Error: {e}")

        self.current_thread = threading.Thread(target=worker, daemon=True)
        self.current_thread.start()

    def closeEvent(self, event):
        """Clean shutdown when closing GUI window."""
        self.stop_current_engine()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("MIDI2OSC")
    if sys.platform == "darwin":
        try:
            from Foundation import NSBundle
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