import sys
import threading
from datetime import datetime
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QLabel,
    QTextEdit,
    QWidget,
)

from config import select_config_file, parse_config
from converter import run_converter


class SignalStream(QObject):
    """Thread-safe redirection of stdout to PySide6 with line buffering."""

    text_written = Signal(str)

    def write(self, text):
        # Only send if there is actual content (ignore empty newlines)
        if text.strip():
            self.text_written.emit(text.strip())

    def flush(self):
        pass


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("MIDI to OSC Converter")
        self.resize(680, 450)
        self.setMinimumSize(680, 450)

        # Main layout
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Header
        title = QLabel("🎛️ MIDI TO OSC CONVERTER")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin-top: 5px;")
        layout.addWidget(title)

        subtitle = QLabel("High-Performance Bridge for Live Performance")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #888888; font-size: 11px; margin-bottom: 5px;")
        layout.addWidget(subtitle)

        # Dark console/terminal text box
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)

        # Limit log to a maximum of 1000 lines for stability and low memory usage
        self.log_area.document().setMaximumBlockCount(1000)

        # Uses native macOS monospace fonts and removes inner padding
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

        # Start the engine
        self.start_engine()

    def append_log_line(self, line_text: str):
        """Formats the text as raw terminal HTML without extra spacing."""
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Colorize keywords if present in the string
        formatted = line_text
        if "MIDI IN:" in formatted:
            formatted = formatted.replace(
                "MIDI IN:",
                "<span style='color: #4CAF50; font-weight: bold;'>MIDI IN:</span>",
            )
        if "MAPPED" in formatted:
            formatted = formatted.replace(
                "MAPPED",
                "<span style='color: #00E676; font-weight: bold;'>MAPPED </span>",
            )
        if "DEFAULT" in formatted:
            formatted = formatted.replace(
                "DEFAULT", "<span style='color: #FFB74D;'>DEFAULT</span>"
            )
        if "Listening on MIDI" in formatted or "Target OSC" in formatted:
            formatted = f"<span style='color: #29B6F6;'>{formatted}</span>"
        if "Error" in formatted or "Invalid" in formatted:
            formatted = (
                f"<span style='color: #FF5252; font-weight: bold;'>{formatted}</span>"
            )

        # Construct final HTML line with timestamp
        html_line = f"<span style='color: #555555;'>[{timestamp}]</span> {formatted}"

        # Insert directly at the bottom of the console without extra line breaks
        cursor = self.log_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_area.setTextCursor(cursor)
        self.log_area.insertHtml(html_line + "<br>")
        self.log_area.ensureCursorVisible()

    def start_engine(self):
        def worker():
            try:
                selected_file = select_config_file()
                config = parse_config(selected_file)

                print(f"✔ Active config: {selected_file.name}")
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

        threading.Thread(target=worker, daemon=True).start()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()