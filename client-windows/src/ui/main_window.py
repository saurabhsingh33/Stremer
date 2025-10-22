from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QToolBar, QStatusBar, QFileDialog, QMessageBox, QComboBox, QSplitter, QInputDialog
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from api.client import APIClient
from ui.login_dialog import LoginDialog
from file_browser.browser_widget import BrowserWidget
from media.vlc_player import play_url
from ui.details_panel import DetailsPanel
import os
import tempfile
import uuid
import requests
import json
import time
from pathlib import Path


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
        self.back_action = QAction(self)
        self.back_action.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ArrowBack))
        self.back_action.setToolTip("Back")
        self.back_action.setEnabled(False)
        self.back_action.triggered.connect(self._go_back)
        toolbar.addAction(self.back_action)

        self.up_action = QAction(self)
        self.up_action.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ArrowUp))
        self.up_action.setToolTip("Up one level")
        self.up_action.setEnabled(False)
        self.up_action.triggered.connect(self._go_up)
        toolbar.addAction(self.up_action)

        self.login_action = QAction("Login", self)
        self.login_action.triggered.connect(self._on_login_or_logout)
        toolbar.addAction(self.login_action)

        self.refresh_action = QAction("Refresh", self)
        self.refresh_action.triggered.connect(self._refresh)
        toolbar.addAction(self.refresh_action)

        # View mode selector
        self.view_combo = QComboBox(self)
        self.view_combo.addItems(["List", "Icons", "Thumbnails"])
        # Default to Thumbnails view
        self.view_combo.setCurrentIndex(2)
        self.view_combo.setToolTip("Change view mode")
        self.view_combo.currentTextChanged.connect(self._on_view_change)
        toolbar.addWidget(self.view_combo)

        # Central splitter: browser left, details right
        self.splitter = QSplitter(self)
        self.setCentralWidget(self.splitter)

        # Browser (initialize without API client; will be set after login)
        self.browser = BrowserWidget(api_client=None, on_play=self._play, on_delete=self._delete, on_copy=self._copy, on_open=self._open_default, on_rename=self._rename, on_properties=self._show_properties, on_new_folder=self._new_folder, on_new_file=self._new_file)
        self.browser.path_changed.connect(self._update_nav_actions)
        self.splitter.addWidget(self.browser)
        # Ensure initial view mode matches combobox selection (Thumbnails)
        try:
            self._on_view_change(self.view_combo.currentText())
        except Exception:
            pass

        # Details panel
        self.details = DetailsPanel(api_client=None)
        self.splitter.addWidget(self.details)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self._last_details_width = 360
        # Start collapsed until selection
        self._set_details_visible(False)
        # Update details on selection change and clear on path change
        self.browser.selection_changed.connect(self._on_selection)
        self.browser.selection_cleared.connect(self._on_selection_cleared)
        self.browser.path_changed.connect(self._on_path_changed)

        # Status bar
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Not connected")
        # Try restore previous session
        try:
            self._try_restore_session()
        except Exception:
            pass

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
            self._clear_saved_session()
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
            self.details.set_api_client(client)
            self.statusBar().showMessage(f"Connected to {base}")
            self.login_action.setText("Logout")
            self.browser.load_path("/")
            # Persist session for 30 days, if requested
            try:
                if getattr(dlg, 'remember_check', None) is None or dlg.remember_check.isChecked():
                    self._save_session(base, token, user)
                else:
                    self._clear_saved_session()
            except Exception:
                pass
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

    def _update_nav_actions(self, _path: str):
        self.back_action.setEnabled(self.browser.can_go_back())
        self.up_action.setEnabled(self.browser.can_go_up())

    def _set_details_visible(self, visible: bool):
        # Adjust splitter sizes to show/hide details pane
        if not self.splitter:
            return
        sizes = self.splitter.sizes()
        if not sizes or len(sizes) < 2:
            return
        left = sizes[0]
        right = sizes[1]
        if visible:
            # Only expand if currently hidden (width 0). Otherwise keep user's width.
            if right == 0:
                target = max(self._last_details_width, 240)
                total = max(1, sum(sizes))
                if target >= total:
                    target = max(1, total // 3)
                self.splitter.setSizes([max(1, total - target), target])
        else:
            # Save current right width if not zero
            if right > 0:
                self._last_details_width = right
            self.splitter.setSizes([sum(sizes), 0])

    def _on_selection(self, item: dict):
        # Do not auto-open details; remember last selected item only
        self._last_selected_item = item

    def _on_selection_cleared(self):
        # Hide details only when explicitly cleared
        self.details.clear()
        self._set_details_visible(False)

    def _on_path_changed(self, _p: str):
        self._update_nav_actions(_p)
        self.details.clear()
        self._set_details_visible(False)

    def _show_properties(self, item: dict):
        # Show details panel on demand
        if not item:
            return
        self.details.show_item(item)
        self._set_details_visible(True)

    def _go_back(self):
        self.browser.go_back()

    def _go_up(self):
        self.browser.go_up()

    class _DownloadThread(QThread):
        progress = pyqtSignal(int)
        done = pyqtSignal(str)
        error = pyqtSignal(str)

        def __init__(self, url: str, dest: str, headers: dict | None = None):
            super().__init__()
            self.url = url
            self.dest = dest
            self.headers = headers or {}

        def run(self):
            try:
                with requests.get(self.url, headers=self.headers, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    total = int(r.headers.get('Content-Length') or 0)
                    downloaded = 0
                    with open(self.dest, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=1024 * 64):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total > 0:
                                    self.progress.emit(int(downloaded * 100 / total))
                self.done.emit(self.dest)
            except Exception as e:
                self.error.emit(str(e))

    class _DownloadDirThread(QThread):
        progress = pyqtSignal(int)
        message = pyqtSignal(str)
        done = pyqtSignal(str)
        error = pyqtSignal(str)

        def __init__(self, api_client: APIClient, src_dir: str, dest_dir: str):
            super().__init__()
            self.api_client = api_client
            self.src_dir = src_dir if src_dir else "/"
            self.dest_dir = dest_dir

        def run(self):
            try:
                files: list[tuple[str, str]] = []
                def walk(path: str, rel: str = ""):
                    items = self.api_client.list_files(path)
                    for it in items:
                        name = it.get("name", "")
                        t = it.get("type", "file")
                        child_server = f"{path.rstrip('/')}/{name}" if path != "/" else f"/{name}"
                        child_rel = f"{rel}/{name}" if rel else name
                        if t == "dir":
                            walk(child_server, child_rel)
                        else:
                            files.append((child_server, child_rel))
                walk(self.src_dir, "")

                total = len(files)
                if total == 0:
                    self.done.emit(self.dest_dir)
                    return
                for idx, (server_path, rel) in enumerate(files, start=1):
                    dest_path = os.path.join(self.dest_dir, rel)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    url = self.api_client.stream_url(server_path)
                    headers = {}
                    if getattr(self.api_client, 'token', None):
                        headers["Authorization"] = f"Bearer {self.api_client.token}"
                    with requests.get(url, headers=headers, stream=True, timeout=120) as r:
                        r.raise_for_status()
                        with open(dest_path, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=1024 * 64):
                                if chunk:
                                    f.write(chunk)
                    pct = int(idx * 100 / total)
                    self.progress.emit(pct)
                self.done.emit(self.dest_dir)
            except Exception as e:
                self.error.emit(str(e))

    def _open_default(self, path: str):
        if not self.api_client:
            return
        # Build temp destination with original extension
        base_name = os.path.basename(path).lstrip('/')
        if not base_name:
            base_name = "file"
        dest = os.path.join(tempfile.gettempdir(), f"stremer_{uuid.uuid4().hex}_{base_name}")
        url = self.api_client.stream_url(path)
        headers = {}
        # Prefer Authorization header if token exists, although token is already in URL
        if self.api_client.token:
            headers["Authorization"] = f"Bearer {self.api_client.token}"

        self.statusBar().showMessage(f"Downloading {base_name}…")
        self._dl = self._DownloadThread(url, dest, headers)
        self._dl.progress.connect(lambda p: self.statusBar().showMessage(f"Downloading {base_name}… {p}%"))
        def _done(local_path: str):
            self.statusBar().showMessage(f"Opening {base_name}", 3000)
            try:
                os.startfile(local_path)
            except Exception as e:
                QMessageBox.critical(self, "Open failed", f"Could not open file: {e}")
        def _err(msg: str):
            QMessageBox.critical(self, "Download failed", msg)
            self.statusBar().clearMessage()
        self._dl.done.connect(_done)
        self._dl.error.connect(_err)
        self._dl.start()

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
        # Determine if directory or file
        try:
            meta = self.api_client.get_meta(src_path)
            is_dir = (meta.get("type") == "dir")
        except Exception:
            is_dir = False
        dest_folder = QFileDialog.getExistingDirectory(self, "Select destination folder")
        if not dest_folder:
            return
        base_name = os.path.basename(src_path).lstrip('/') or "download"
        if is_dir:
            target_dir = os.path.join(dest_folder, base_name)
            try:
                os.makedirs(target_dir, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Cannot create folder: {e}")
                return
            self.statusBar().showMessage(f"Downloading folder {base_name}…")
            self._ddl = self._DownloadDirThread(self.api_client, src_path, target_dir)
            self._ddl.progress.connect(lambda p: self.statusBar().showMessage(f"Downloading folder {base_name}… {p}%"))
            self._ddl.message.connect(lambda m: self.statusBar().showMessage(m))
            self._ddl.done.connect(lambda p: self.statusBar().showMessage(f"Folder saved to {p}", 5000))
            self._ddl.error.connect(lambda msg: QMessageBox.critical(self, "Download failed", msg))
            self._ddl.start()
        else:
            dest = os.path.join(dest_folder, base_name)
            url = self.api_client.stream_url(src_path)
            headers = {}
            if self.api_client.token:
                headers["Authorization"] = f"Bearer {self.api_client.token}"
            self.statusBar().showMessage(f"Downloading {base_name}…")
            self._dl = self._DownloadThread(url, dest, headers)
            self._dl.progress.connect(lambda p: self.statusBar().showMessage(f"Downloading {base_name}… {p}%"))
            def _done(local_path: str):
                self.statusBar().showMessage(f"Saved to {local_path}", 5000)
            def _err(msg: str):
                QMessageBox.critical(self, "Download failed", msg)
                self.statusBar().clearMessage()
            self._dl.done.connect(_done)
            self._dl.error.connect(_err)
            self._dl.start()

    def _rename(self, path: str):
        if not self.api_client:
            return
        base_name = os.path.basename(path).lstrip('/')
        new_name, ok = QInputDialog.getText(self, "Rename", f"Enter new name for:\n{base_name}", text=base_name)
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == base_name:
            return
        try:
            success = self.api_client.rename_file(path, new_name)
            if success:
                self._refresh()
            else:
                QMessageBox.critical(self, "Error", "Rename failed")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Rename failed: {e}")

    def _new_folder(self, parent_path: str):
        if not self.api_client:
            return
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return
        try:
            if self.api_client.create_folder(parent_path, name):
                self._refresh()
            else:
                QMessageBox.critical(self, "Error", "Create folder failed")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Create folder failed: {e}")

    def _new_file(self, parent_path: str):
        if not self.api_client:
            return
        name, ok = QInputDialog.getText(self, "New File", "File name (with extension):")
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return
        # Optional: derive MIME by extension; server also guesses
        mime = None
        try:
            if self.api_client.create_file(parent_path, name, mime):
                self._refresh()
            else:
                QMessageBox.critical(self, "Error", "Create file failed")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Create file failed: {e}")

    # --- Session persistence ---
    def _session_file(self) -> Path:
        appdata = os.getenv('APPDATA')
        if appdata:
            base = Path(appdata) / 'Stremer'
        else:
            base = Path.home() / '.stremer'
        base.mkdir(parents=True, exist_ok=True)
        return base / 'session.json'

    def _save_session(self, base_url: str, token: str, username: str | None = None):
        data = {
            'base_url': base_url,
            'token': token,
            'username': username,
            'expires_at': int(time.time()) + 30 * 24 * 3600
        }
        try:
            self._session_file().write_text(json.dumps(data))
        except Exception:
            pass

    def _clear_saved_session(self):
        try:
            fp = self._session_file()
            if fp.exists():
                fp.unlink()
        except Exception:
            pass

    def _try_restore_session(self):
        fp = self._session_file()
        if not fp.exists():
            return
        try:
            data = json.loads(fp.read_text())
        except Exception:
            return
        expires = data.get('expires_at', 0)
        if int(time.time()) >= int(expires):
            # Expired
            self._clear_saved_session()
            return
        base = data.get('base_url')
        token = data.get('token')
        if not base or not token:
            return
        client = APIClient(base)
        client.set_token(token)
        # Try a light call to verify; if fails, clear session
        try:
            self.api_client = client
            self.browser.set_api_client(client)
            self.details.set_api_client(client)
            self.browser.load_path("/")
            self.statusBar().showMessage(f"Connected to {base}")
            self.login_action.setText("Logout")
        except Exception:
            self.api_client = None
            self.browser.set_api_client(None)
            self._clear_saved_session()
            self.statusBar().showMessage("Not connected")
