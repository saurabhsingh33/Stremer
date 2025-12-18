from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QProgressDialog, QMessageBox
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from pathlib import Path
import webbrowser
import version
import updater

class _CheckUpdateThread(QThread):
    result = pyqtSignal(object)  # dict with info or None
    error = pyqtSignal(str)

    def run(self):
        try:
            info = updater.check_latest_release()
            self.result.emit(info)
        except Exception as e:
            self.error.emit(str(e))


class _DownloadThread(QThread):
    progress = pyqtSignal(int)
    finished_path = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, url: str, filename: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.filename = filename

    def run(self):
        try:
            path = updater.download_asset(self.url, self.filename, self.progress.emit)
            self.finished_path.emit(path)
        except Exception as e:
            self.error.emit(str(e))


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Stremer")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        here = Path(__file__).resolve()
        icon_paths = [here.parents[3] / "app.png", here.parents[3] / "app.ico"]
        icon_label = QLabel("Stremer")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        layout.addWidget(QLabel(f"Windows Client\nVersion: {version.VERSION}"))

        link = QLabel("<a href='https://github.com/OWNER/REPO/releases'>Releases on GitHub</a>")
        link.setOpenExternalLinks(True)
        layout.addWidget(link)

        btns = QHBoxLayout()
        self.check_btn = QPushButton("Check for updates")
        self.check_btn.clicked.connect(self._check_updates)
        btns.addStretch(1)
        btns.addWidget(self.check_btn)
        layout.addLayout(btns)

        self._progress: QProgressDialog | None = None

    def _check_updates(self):
        self.check_btn.setEnabled(False)
        t = _CheckUpdateThread()
        self._t_check = t
        def on_result(info):
            self.check_btn.setEnabled(True)
            if not info:
                QMessageBox.information(self, "Updates", "Could not fetch release info.")
                return
            latest = info.get("tag_name")
            if updater.is_newer(latest, version.VERSION):
                url = updater.get_windows_asset_url(info)
                if not url:
                    QMessageBox.information(self, "Updates", "No Windows installer found in the latest release.")
                    return
                self._start_download(url)
            else:
                QMessageBox.information(self, "Updates", "You're up to date.")
        def on_error(msg):
            self.check_btn.setEnabled(True)
            QMessageBox.information(self, "Updates", f"Update check failed: {msg}")
        t.result.connect(on_result)
        t.error.connect(on_error)
        t.start()

    def _start_download(self, url: str):
        self._progress = QProgressDialog("Downloading update...", None, 0, 100, self)
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.show()
        t = _DownloadThread(url, "Stremer-Client-setup.exe", self)
        self._t_dl = t
        t.progress.connect(lambda p: self._progress.setValue(max(0, min(100, p))))
        def on_done(path: str):
            if self._progress:
                self._progress.close()
            updater.launch_installer(path)
        def on_err(msg: str):
            if self._progress:
                self._progress.close()
            QMessageBox.information(self, "Updates", f"Download failed: {msg}")
        t.finished_path.connect(on_done)
        t.error.connect(on_err)
        t.start()
