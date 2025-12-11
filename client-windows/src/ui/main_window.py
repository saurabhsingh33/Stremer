from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QToolBar, QStatusBar, QFileDialog, QMessageBox, QComboBox, QSplitter, QInputDialog, QProgressDialog
from PyQt6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from api.client import APIClient
from ui.login_dialog import LoginDialog
from file_browser.browser_widget import BrowserWidget
from media.vlc_player import play_url
from media.image_viewer import ImageViewer
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
        self._open_image_views: list[ImageViewer] = []

        # Enable drag and drop
        self.setAcceptDrops(True)

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

        # Central container: start screen + splitter
        from PyQt6.QtWidgets import QWidget, QStackedLayout, QLabel
        self.container = QWidget()
        self._central_layout = QVBoxLayout(self.container)

        # Start / welcome screen shown when not connected
        self.start_widget = QLabel()
        self.start_widget.setText("\n\nWelcome to Stremer\n\nClick Login to connect to a server.")
        self.start_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._central_layout.addWidget(self.start_widget)

        # Central splitter: browser left, details right
        self.splitter = QSplitter(self)
        self._central_layout.addWidget(self.splitter)
        self.setCentralWidget(self.container)

        # Browser (initialize without API client; will be set after login)
        self.browser = BrowserWidget(api_client=None, on_play=self._play, on_delete=self._delete, on_copy=self._copy, on_open=self._open_default, on_rename=self._rename, on_properties=self._show_properties, on_new_folder=self._new_folder, on_new_file=self._new_file, on_open_with=self._open_with, on_upload=self._upload)
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
        # If not connected, show start screen; otherwise show splitter
        if not self.api_client:
            self._show_start_screen()
        else:
            self._show_main_view()

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
            # Clear details panel
            try:
                self.details.set_api_client(None)
                self.details.clear()
            except Exception:
                pass
            self.statusBar().showMessage("Not connected")
            self.login_action.setText("Login")
            self._clear_saved_session()
            # Show friendly start screen instead of browsing stale files
            self._show_start_screen()
        else:
            # Show login dialog
            dlg = LoginDialog()

            # Add a "Connect without login" button
            from PyQt6.QtWidgets import QPushButton
            connect_btn = QPushButton("Connect without login")
            connect_btn.clicked.connect(lambda: self._try_connect_without_auth(dlg))
            dlg.layout().insertWidget(dlg.layout().count() - 1, connect_btn)

            dlg.login_btn.clicked.connect(lambda: self._do_login(dlg))
            dlg.exec()

    def _try_connect_without_auth(self, dlg: LoginDialog):
        """Try to connect to server without authentication (for when auth is disabled)."""
        base = dlg.host_input.text().strip()
        if not base:
            QMessageBox.warning(self, "Missing info", "Please enter server URL.")
            return

        client = APIClient(base)
        try:
            # Probe files endpoint WITHOUT any token; if server has auth disabled,
            # this should succeed. No server changes required.
            try:
                items = client.list_files("/")
                _ = len(items)  # touch to ensure JSON parsed
                print("DEBUG(no-auth): list_files('/') succeeded without token")
                no_auth_mode = True
            except Exception as probe_err:
                # If it's a 401, try anonymous login fallback
                import requests as _req
                status = getattr(getattr(probe_err, 'response', None), 'status_code', None)
                print(f"DEBUG(no-auth): probe failed, status={status}, err={probe_err}")
                if isinstance(probe_err, _req.exceptions.HTTPError) and status == 401:
                    try:
                        from api.auth import AuthClient
                        auth = AuthClient(base)
                        token = auth.login("anonymous", "anonymous")
                        if not token:
                            raise RuntimeError("Server requires authentication and anonymous login failed")
                        client.set_token(token)
                        print("DEBUG(no-auth): Anonymous login succeeded, token acquired")
                        # Verify with token
                        items = client.list_files("/")
                        _ = len(items)
                        no_auth_mode = False
                    except Exception as anon_err:
                        print(f"DEBUG(no-auth): anonymous login fallback failed: {anon_err}")
                        raise
                else:
                    # Not a 401 or different failure
                    raise

            # Wire up client everywhere
            self.api_client = client
            token_dbg = client.token if getattr(client, 'token', None) else None
            print(f"DEBUG: Set api_client with token: {token_dbg}")
            self.browser.set_api_client(client)
            print("DEBUG: Set browser api_client")
            self.details.set_api_client(client)
            print("DEBUG: Set details api_client")
            self.statusBar().showMessage(f"Connected to {base} ({'auth disabled' if token_dbg is None else 'anonymous auth'})")
            self.login_action.setText("Logout")
            print("DEBUG: About to load browser path")
            try:
                self.browser.load_path("/")
                print("DEBUG: Browser path loaded successfully")
            except Exception as load_err:
                print(f"ERROR loading root path: {load_err}")
                import traceback
                traceback.print_exc()
            # Hide start screen and show main view
            self._show_main_view()
            # Persist only if we have a token (anonymous auth mode)
            if token_dbg:
                print("DEBUG: About to save session (anonymous auth)")
                self._save_session(base, token_dbg, "anonymous")
            print("DEBUG: About to accept dialog (no-auth/anon mode)")
            dlg.accept()
            print("DEBUG: Dialog accepted")
        except Exception as e:
            import traceback
            print(f"ERROR in _try_connect_without_auth: {e}")
            traceback.print_exc()
            QMessageBox.critical(self, "Connection failed",
                               f"Could not connect without authentication: {e}\n\nPlease try with credentials.")

    def _do_login(self, dlg: LoginDialog):
        base = dlg.host_input.text().strip()
        user = dlg.user_input.text().strip()
        pwd = dlg.pass_input.text().strip()
        if not base:
            QMessageBox.warning(self, "Missing info", "Please enter server URL.")
            return
        if not user or not pwd:
            QMessageBox.warning(self, "Missing info", "Please fill username and password.")
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
            try:
                self.browser.load_path("/")
            except Exception as load_err:
                print(f"Error loading root path: {load_err}")
                import traceback
                traceback.print_exc()
            # Show main view now that login succeeded
            try:
                self._show_main_view()
            except Exception:
                pass
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
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Failed to connect: {e}\n\n{traceback.format_exc()}")

    def _refresh(self):
        if self.api_client:
            try:
                self.browser.load_path(self.browser.current_path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Refresh failed: {e}")
        else:
            QMessageBox.information(self, "Not connected", "Login first.")

    def _show_start_screen(self):
        try:
            self.start_widget.show()
            self.splitter.hide()
        except Exception:
            pass

    def _show_main_view(self):
        try:
            self.start_widget.hide()
            self.splitter.show()
        except Exception:
            pass

    def _on_image_saved(self, saved_path: str):
        """Called when an image is saved from the image viewer."""
        # Refresh the browser to update thumbnails
        self._refresh()
        self.statusBar().showMessage(f"Thumbnail updated for {os.path.basename(saved_path)}", 3000)

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
                with requests.get(self.url, headers=self.headers, stream=True, timeout=120) as r:
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

    class _UploadThread(QThread):
        progress = pyqtSignal(int, str)  # percentage, message
        done = pyqtSignal(int, int)  # uploaded_count, total_bytes
        error = pyqtSignal(str)

        def __init__(self, api_client: APIClient, files_to_upload: list, target_path: str):
            super().__init__()
            self.api_client = api_client
            self.files_to_upload = files_to_upload  # list of (local_path, remote_name, size)
            self.target_path = target_path
            self.canceled = False

        def cancel(self):
            self.canceled = True

        def run(self):
            import time
            uploaded_count = 0
            uploaded_bytes = 0
            total_size = sum(size for _, _, size in self.files_to_upload)

            for file_idx, (local_file, remote_name, file_size) in enumerate(self.files_to_upload):
                if self.canceled:
                    break

                try:
                    remote_path = f"{self.target_path.rstrip('/')}/{remote_name}"
                    url = f"{self.api_client.base_url}/file?path={remote_path}"
                    headers = {'Authorization': f'Bearer {self.api_client.token}'}

                    # Track progress with throttling
                    last_update_time = time.time()

                    # Capture the progress signal from the thread
                    progress_signal = self.progress

                    # Helper function for formatting bytes
                    def format_bytes(bytes_count):
                        """Format bytes into human-readable format."""
                        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                            if bytes_count < 1024.0:
                                return f"{bytes_count:.1f} {unit}"
                            bytes_count /= 1024.0
                        return f"{bytes_count:.1f} PB"

                    def create_progress_reader(file_path, file_size):
                        """Create a file reader that tracks upload progress."""
                        class ProgressFileReader:
                            def __init__(self):
                                self.file = open(file_path, 'rb')
                                self.bytes_read = 0

                            def read(self, size=-1):
                                nonlocal last_update_time
                                chunk = self.file.read(size)
                                self.bytes_read += len(chunk)

                                # Throttle updates to every 200ms
                                current_time = time.time()
                                if current_time - last_update_time >= 0.2 or self.bytes_read == file_size:
                                    last_update_time = current_time
                                    current_file_progress = int((self.bytes_read / file_size) * 100) if file_size > 0 else 0
                                    overall_bytes = uploaded_bytes + self.bytes_read
                                    overall_progress = int((overall_bytes / total_size) * 100) if total_size > 0 else 0

                                    msg = (f"Uploading {remote_name}\n"
                                          f"{format_bytes(self.bytes_read)} / {format_bytes(file_size)} ({current_file_progress}%)\n"
                                          f"Overall: {format_bytes(overall_bytes)} / {format_bytes(total_size)}")
                                    progress_signal.emit(overall_progress, msg)

                                return chunk

                            def __len__(self):
                                return file_size

                            def __enter__(self):
                                return self

                            def __exit__(self, *args):
                                self.file.close()

                        return ProgressFileReader()

                    with create_progress_reader(local_file, file_size) as reader:
                        response = requests.put(
                            url,
                            data=reader,
                            headers=headers,
                            timeout=600  # 10 minutes for very large files
                        )

                        if response.status_code == 200:
                            uploaded_count += 1
                            uploaded_bytes += file_size
                        else:
                            error_msg = f"Failed to upload {remote_name}: {response.status_code}"
                            try:
                                error_msg += f"\n{response.text}"
                            except:
                                pass
                            self.error.emit(error_msg)

                except Exception as e:
                    self.error.emit(f"Error uploading {remote_name}: {str(e)}")

            self.done.emit(uploaded_count, uploaded_bytes)

    def _open_default(self, path: str):
        if not self.api_client:
            return
        # If image file, open in in-app viewer without saving to disk
        name_lower = os.path.basename(path).lower()
        if self._is_image(name_lower):
            try:
                url = self.api_client.stream_url(path)
                token = self.api_client.token if self.api_client.token else None
                display_name = os.path.basename(path).lstrip('/') or None

                # Debug logging
                print(f"Opening image: {path}")
                print(f"URL: {url}")
                print(f"Token: {token}")

                # Create ImageViewer WITHOUT parent to avoid Qt parent-child issues
                viewer = ImageViewer(url, token, display_name=display_name, parent=None)
                print("DEBUG main_window: ImageViewer created successfully")
                viewer.setModal(False)
                print("DEBUG main_window: setModal(False) completed")
                # Ensure Qt deletes on close and we drop our ref
                viewer.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
                print("DEBUG main_window: setAttribute WA_DeleteOnClose completed")
                self._open_image_views.append(viewer)
                print("DEBUG main_window: Appended to _open_image_views")
                def _cleanup():
                    try:
                        self._open_image_views.remove(viewer)
                    except ValueError:
                        pass
                viewer.destroyed.connect(lambda *_: _cleanup())
                print("DEBUG main_window: Connected destroyed signal")
                # Connect file_saved signal to refresh browser
                viewer.file_saved.connect(self._on_image_saved)
                print("DEBUG main_window: Connected file_saved signal")
                print("DEBUG main_window: About to call viewer.show()")
                viewer.show()
                print("DEBUG main_window: viewer.show() completed")
                self.statusBar().showMessage("Opening image…", 2000)
                print("DEBUG main_window: statusBar message set")
                print("DEBUG main_window: About to return from image open")

                # Force Qt to process pending events before returning
                from PyQt6.QtCore import QCoreApplication
                print("DEBUG main_window: Processing pending events")
                QCoreApplication.processEvents()
                print("DEBUG main_window: Pending events processed")

                return
            except Exception as e:
                print(f"DEBUG main_window: EXCEPTION in image open: {e}")
                import traceback
                traceback.print_exc()
                QMessageBox.critical(self, "Open failed", f"Could not open image: {e}\n\n{traceback.format_exc()}")
                return
        print("DEBUG main_window: Not an image, proceeding to download")
        # Build temp destination with original extension
        base_name = os.path.basename(path).lstrip('/')
        if not base_name:
            base_name = "file"
        dest = os.path.join(tempfile.gettempdir(), f"stremer_{uuid.uuid4().hex}_{base_name}")
        url = self.api_client.stream_url(path)
        # Don't add Authorization header since token is already in URL
        headers = {}

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
            # Show more detailed error message
            print(f"Download error for {base_name}: {msg}")
            print(f"URL: {url}")
            QMessageBox.critical(self, "Download failed", f"Failed to download {base_name}:\n{msg}\n\nURL: {url}")
            self.statusBar().clearMessage()
        self._dl.done.connect(_done)
        self._dl.error.connect(_err)
        self._dl.start()

    def _open_with(self, path: str, app_path: str | None):
        """Open file with specified application or show file chooser."""
        if not self.api_client:
            return

        # If app_path is None, show file chooser dialog
        if app_path is None:
            from PyQt6.QtWidgets import QFileDialog
            app_path, _ = QFileDialog.getOpenFileName(
                self,
                "Choose Application",
                "",
                "Applications (*.exe);;All Files (*.*)"
            )
            if not app_path:
                return

        # Download the file to temp and open with specified app
        base_name = os.path.basename(path).lstrip('/')
        if not base_name:
            base_name = "file"
        dest = os.path.join(tempfile.gettempdir(), f"stremer_{uuid.uuid4().hex}_{base_name}")
        url = self.api_client.stream_url(path)
        # Don't add Authorization header since token is already in URL
        headers = {}

        self.statusBar().showMessage(f"Downloading {base_name}…")
        self._dl = self._DownloadThread(url, dest, headers)
        self._dl.progress.connect(lambda p: self.statusBar().showMessage(f"Downloading {base_name}… {p}%"))

        def _done(local_path: str):
            self.statusBar().showMessage(f"Opening {base_name} with {os.path.basename(app_path)}", 3000)
            try:
                import subprocess
                subprocess.Popen([app_path, local_path])
            except Exception as e:
                QMessageBox.critical(self, "Open failed", f"Could not open file with {app_path}: {e}")

        def _err(msg: str):
            print(f"Download error for {base_name}: {msg}")
            print(f"URL: {url}")
            QMessageBox.critical(self, "Download failed", f"Failed to download {base_name}:\n{msg}\n\nURL: {url}")
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

    def _is_image(self, name_lower: str) -> bool:
        return name_lower.endswith((
            ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"
        ))

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
            # Show main view now that we're connected
            try:
                self._show_main_view()
            except Exception:
                pass
        except Exception:
            self.api_client = None
            self.browser.set_api_client(None)
            self._clear_saved_session()
            self.statusBar().showMessage("Not connected")

    def dragEnterEvent(self, event: QDragEnterEvent):
        """Accept drag events with file URLs."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        # Show main view after restoring session
        try:
            self._show_main_view()
        except Exception:
                pass
        """Handle dropped files/folders."""
        if not self.api_client:
            QMessageBox.warning(self, "Not connected", "Please login to upload files.")
            return

        urls = event.mimeData().urls()
        local_paths = [url.toLocalFile() for url in urls if url.isLocalFile()]

        if local_paths:
            self._upload(local_paths, self.browser.current_path)

    def _upload(self, local_paths: list[str], target_path: str):
        """Upload files/folders to the server."""
        if not self.api_client:
            QMessageBox.warning(self, "Not connected", "Please login to upload files.")
            return

        # Collect all files to upload (expand folders)
        files_to_upload = []
        total_size = 0
        for local_path in local_paths:
            if os.path.isfile(local_path):
                size = os.path.getsize(local_path)
                files_to_upload.append((local_path, os.path.basename(local_path), size))
                total_size += size
            elif os.path.isdir(local_path):
                # Recursively collect all files in the folder
                folder_name = os.path.basename(local_path)
                for root, dirs, files in os.walk(local_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Calculate relative path within the folder
                        rel_path = os.path.relpath(file_path, local_path)
                        remote_path = os.path.join(folder_name, rel_path).replace('\\', '/')
                        size = os.path.getsize(file_path)
                        files_to_upload.append((file_path, remote_path, size))
                        total_size += size

        if not files_to_upload:
            QMessageBox.information(self, "No files", "No files selected for upload.")
            return

        # Create progress dialog
        progress = QProgressDialog("Preparing upload...", "Cancel", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        # Create and start upload thread
        upload_thread = self._UploadThread(self.api_client, files_to_upload, target_path)

        def on_progress(percentage, message):
            if progress.wasCanceled():
                upload_thread.cancel()
                return
            progress.setValue(percentage)
            progress.setLabelText(message)

        def on_done(uploaded_count, uploaded_bytes):
            progress.setValue(100)
            if uploaded_count > 0:
                self.statusBar().showMessage(
                    f"Uploaded {uploaded_count} file(s) ({self._format_bytes(uploaded_bytes)})"
                )
                # Refresh browser to show new files
                self._refresh()
            else:
                self.statusBar().showMessage("Upload canceled or failed")

        def on_error(error_msg):
            QMessageBox.warning(self, "Upload Error", error_msg)

        upload_thread.progress.connect(on_progress)
        upload_thread.done.connect(on_done)
        upload_thread.error.connect(on_error)

        # Connect cancel button to thread cancellation
        progress.canceled.connect(upload_thread.cancel)

        upload_thread.start()

    def _format_bytes(self, bytes_count):
        """Format bytes into human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_count < 1024.0:
                return f"{bytes_count:.1f} {unit}"
            bytes_count /= 1024.0
        return f"{bytes_count:.1f} PB"
