import sys
import subprocess
import json
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout,
    QLineEdit, QMessageBox
)
from PyQt6.QtCore import Qt

# Load config
with open("config.json", "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

class ScribdDownloader(QWidget):
    def __init__(self):
        super().__init__()

        # Window settings
        window_cfg = CONFIG["gui"]["window"]
        self.setWindowTitle(window_cfg.get("title", "Scribd Downloader"))
        width = window_cfg.get("width", 400)
        height = window_cfg.get("height", 200)
        self.resize(width, height)
        if not window_cfg.get("resizable", False):
            self.setFixedSize(width, height)

        # URL input
        self.url_label = QLabel("Enter Scribd URL:")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.scribd.com/document/...")
        self.url_input.setText(CONFIG["gui"].get("default_url", ""))
        self.url_input.setToolTip("Paste a Scribd document link here.")
        self.url_input.setAcceptDrops(True)
        self.url_input.installEventFilter(self)

        # Download button
        self.download_button = QPushButton("Download & Convert")
        self.download_button.clicked.connect(self.start_download)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_status("default")

        # Layout setup
        layout = QVBoxLayout()
        layout.addWidget(self.url_label)
        layout.addWidget(self.url_input)
        layout.addWidget(self.download_button)
        layout.addWidget(self.status_label)
        self.setLayout(layout)

    def eventFilter(self, source, event):
        if source == self.url_input and event.type() == event.Type.Drop:
            mime_data = event.mimeData()
            if mime_data.hasUrls():
                urls = mime_data.urls()
                if urls:
                    self.url_input.setText(urls[0].toString())
                    return True
        return super().eventFilter(source, event)

    def set_status(self, status_type, message=""):
        color = CONFIG["gui"]["status_colors"].get(status_type, "#333")
        self.status_label.setStyleSheet(f"color: {color};")
        self.status_label.setText(message)

    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Input Error", "Please enter a Scribd URL.")
            return

        self.set_status("default", "⏳ Downloading...")
        self.download_button.setEnabled(False)

        try:
            subprocess.run([sys.executable, "main.py", url], check=True)
            self.set_status("success", "✅ Done! PDF created.")
        except subprocess.CalledProcessError:
            self.set_status("error", "❌ Failed. Check the console for details.")
            QMessageBox.critical(self, "Error", "Download or conversion failed.")
        finally:
            self.download_button.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = ScribdDownloader()
    win.show()
    sys.exit(app.exec())
