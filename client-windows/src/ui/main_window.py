from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QToolBar, QStatusBar, QFileDialog, QMessageBox, QComboBox
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt

from api.client import APIClient
from ui.login_dialog import LoginDialog
from file_browser.browser_widget import BrowserWidget
from media.vlc_player import play_url


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stremer - Windows Client")
        self.resize(1200, 800)

        self.api_client: APIClient | None = None

        # Toolbar
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        # Actions
        self.login_action = QAction("Login", self)
        self.login_action.triggered.connect(self._on_login_or_logout)
        toolbar.addAction(self.login_action)

        self.refresh_action = QAction("Refresh", self)
        self.refresh_action.triggered.connect(self._refresh)
        toolbar.addAction(self.refresh_action)

        # View mode selector
        self.view_combo = QComboBox(self)
        self.view_combo.addItems(["List", "Icons", "Thumbnails"])
        self.view_combo.setCurrentIndex(0)
        self.view_combo.setToolTip("Change view mode")
        self.view_combo.currentTextChanged.connect(self._on_view_change)
        toolbar.addWidget(self.view_combo)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout()
        central.setLayout(layout)

        # Browser (initialize without API client; will be set after login)
        self.browser = BrowserWidget(api_client=None, on_play=self._play, on_delete=self._delete, on_copy=self._copy)
        layout.addWidget(self.browser)

        # Status bar
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Not connected")

    def _api(self):
        if not self.api_client:
            QMessageBox.warning(self, "Not connected", "Please login to a server first.")
        return self.api_client


    def _on_login_or_logout(self):
        if self.api_client:
            # Logout: reset state
            self.api_client = None
            self.browser.set_api_client(None)
            self.browser.load_path("/")
            self.statusBar().showMessage("Not connected")
            self.login_action.setText("Login")
        else:
            dlg = LoginDialog()
            dlg.login_btn.clicked.connect(lambda: self._do_login(dlg))
            dlg.exec()

    def _do_login(self, dlg: LoginDialog):
        base = dlg.host_input.text().strip()
        user = dlg.user_input.text().strip()
        pwd = dlg.pass_input.text().strip()
        if not base or not user or not pwd:
            QMessageBox.warning(self, "Missing info", "Please fill all fields.")
            return
        client = APIClient(base)
        try:
            from api.auth import AuthClient
            auth = AuthClient(base)
            token = auth.login(user, pwd)
            if not token:
                QMessageBox.critical(self, "Login failed", "Invalid credentials.")
                return
            client.set_token(token)
            self.api_client = client
            # Provide API client to browser now that we're authenticated
            self.browser.set_api_client(client)
            self.statusBar().showMessage(f"Connected to {base}")
            self.login_action.setText("Logout")
            self.browser.load_path("/")
            dlg.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to connect: {e}")

    def _refresh(self):
        if self.api_client:
            try:
                self.browser.load_path(self.browser.current_path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Refresh failed: {e}")
        else:
            QMessageBox.information(self, "Not connected", "Login first.")

    def _on_view_change(self, text: str):
        self.browser.set_view_mode(text.lower())

    def _play(self, path: str):
        if not self.api_client:
            return
        url = self.api_client.stream_url(path)
        # Copy URL to clipboard for debugging
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(url)
        self.statusBar().showMessage(f"Streaming in VLC...", 3000)
        play_url(url)

    def _delete(self, path: str):
        if not self.api_client:
            return
        if QMessageBox.question(self, "Confirm", f"Delete {path}?") == QMessageBox.StandardButton.Yes:
            ok = self.api_client.delete_file(path)
            if ok:
                self._refresh()
            else:
                QMessageBox.critical(self, "Error", "Delete failed")

    def _copy(self, src_path: str):
        if not self.api_client:
            return
        dst, _ = QFileDialog.getSaveFileName(self, "Copy to server path", src_path)
        if dst:
            ok = self.api_client.copy_file(src_path, dst)
            if ok:
                self._refresh()
            else:
                QMessageBox.critical(self, "Error", "Copy failed")
