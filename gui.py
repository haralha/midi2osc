"""PySide6 GUI entrypoint for MIDI to OSC Converter."""

import html
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QTextEdit,
    QWidget,
)

from config import parse_config, get_available_config_files, get_user_config_dir
from converter import run_converter


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
        self.resize(750, 480)
        self.setMinimumSize(750, 480)

        self.current_thread = None

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Top Bar
        top_bar = QHBoxLayout()

        config_label = QLabel("Selected Config File:")
        config_label.setStyleSheet("color: #aaaaaa; font-size: 12px; font-weight: bold;")
        top_bar.addWidget(config_label)

        self.combo_config = QComboBox()
        self.combo_config.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
                min-width: 200px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: #3a3a3a;
            }
        """)
        top_bar.addWidget(self.combo_config)

        self.btn_open_folder = QPushButton("📁 Open Config Folder")
        self.btn_open_folder.setToolTip("Open directory containing configuration files")
        self.btn_open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_folder.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #666666;
            }
            QPushButton:pressed { background-color: #1a1a1a; }
        """)
        self.btn_open_folder.clicked.connect(self.open_config_folder)
        top_bar.addWidget(self.btn_open_folder)

        top_bar.addStretch()
        layout.addLayout(top_bar)

        # Header Title
        title = QLabel("🎛️ MIDI TO OSC CONVERTER")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin-top: 5px;")
        layout.addWidget(title)

        subtitle = QLabel("High-Performance Bridge for Live Performance")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #888888; font-size: 11px; margin-bottom: 5px;")
        layout.addWidget(subtitle)

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
                padding: 6px;
            }
        """)
        layout.addWidget(self.log_area)

        # Redirect stdout
        self.stream = SignalStream()
        self.stream.text_written.connect(self.append_log_line)
        sys.stdout = self.stream

        self.load_config_list()
        self.combo_config.currentIndexChanged.connect(self.on_config_selected)

        self.start_engine()

    def load_config_list(self):
        self.combo_config.blockSignals(True)
        self.combo_config.clear()
        try:
            files = get_available_config_files()
            for file_path in files:
                self.combo_config.addItem(file_path.name, userData=file_path)
        except Exception as e:
            print(f"✖ Error listing config files: {e}")
        self.combo_config.blockSignals(False)

    def open_config_folder(self):
        selected_path = self.combo_config.currentData()
        target_dir = selected_path.parent if selected_path else get_user_config_dir()
        print(f"📂 Opening folder: {target_dir}")

        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(target_dir)])
            elif sys.platform == "win32":
                os.startfile(str(target_dir))
            else:
                subprocess.run(["xdg-open", str(target_dir)])
        except Exception as e:
            print(f"✖ Failed to open folder: {e}")

    def on_config_selected(self, index):
        if index < 0:
            return
        selected_path = self.combo_config.itemData(index)
        print(f"\n🔄 Switching configuration to: {selected_path.name}")
        self.start_engine(selected_path)

    def append_log_line(self, line_text: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        safe_text = html.escape(line_text)

        formatted = safe_text
        if "MIDI IN:" in formatted:
            formatted = formatted.replace("MIDI IN:", "<span style='color: #4CAF50; font-weight: bold;'>MIDI IN:</span>")
        if "MAPPED" in formatted:
            formatted = formatted.replace("MAPPED", "<span style='color: #00E676; font-weight: bold;'>MAPPED </span>")
        if "DEFAULT" in formatted:
            formatted = formatted.replace("DEFAULT", "<span style='color: #FFB74D;'>DEFAULT</span>")
        if any(k in formatted for k in ("Listening on MIDI", "Target OSC", "Creating", "Switching", "Opening folder")):
            formatted = f"<span style='color: #29B6F6;'>{formatted}</span>"
        if any(k in formatted for k in ("Error", "Invalid", "✖")):
            formatted = f"<span style='color: #FF5252; font-weight: bold;'>{formatted}</span>"

        html_line = f"<span style='color: #555555;'>[{timestamp}]</span> {formatted}"

        cursor = self.log_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_area.setTextCursor(cursor)
        self.log_area.insertHtml(html_line + "<br>")
        self.log_area.ensureCursorVisible()

    def start_engine(self, config_path: Path = None):
        if config_path is None:
            config_path = self.combo_config.currentData()

        if not config_path:
            print("✖ No config file selected or found.")
            return

        def worker():
            try:
                config = parse_config(config_path)

                print(f"✔ Active config: {config_path.name}")
                print(f"Listening on MIDI: '{config['midi_port']}'")
                print(f"Target OSC: {config['ip']}:{config['port']}")
                print("Waiting for incoming MIDI events...")

                run_converter(
                    config["midi_port"],
                    config["ip"],
                    config["port"],
                    config["mappings"],
                )
            except Exception as e:
                print(f"✖ Error: {e}")

        self.current_thread = threading.Thread(target=worker, daemon=True)
        self.current_thread.start()


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