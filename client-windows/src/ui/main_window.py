from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QToolBar, QStatusBar, QFileDialog, QMessageBox, QComboBox, QSplitter, QInputDialog, QProgressDialog, QSizePolicy
from PyQt6.QtGui import QAction, QDragEnterEvent, QDropEvent, QIcon
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from api.client import APIClient
from ui.login_dialog import LoginDialog
from file_browser.browser_widget import BrowserWidget
from media.vlc_player import play_url
from media.image_viewer import ImageViewer
from ui.music_player import MusicPlayer
from ui.camera_viewer import CameraViewer
from ui.details_panel import DetailsPanel
import os
import tempfile
import uuid
import requests
import json
import time
from pathlib import Path


class _LoginThread(QThread):
    """Background thread for performing login/connection without blocking UI."""
    success = pyqtSignal(object, str, str)  # (client, base_url, user_or_anon)
    error = pyqtSignal(str, str)  # (error_msg, friendly_msg)

    def __init__(self, base: str, user: str = None, pwd: str = None, parent=None):
        super().__init__(parent)
        self.base = base
        self.user = user
        self.pwd = pwd
        self.is_login_mode = user is not None

    def run(self):
        try:
            client = APIClient(self.base)
            if self.is_login_mode:
                # Credential login
                from api.auth import AuthClient
                auth = AuthClient(self.base)
                token = auth.login(self.user, self.pwd)
                if not token:
                    self.error.emit("Invalid credentials", "Invalid username or password.")
                    return
                client.set_token(token)
                self.success.emit(client, self.base, self.user)
            else:
                # No-auth mode: probe first
                try:
                    items = client.list_files("/")
                    _ = len(items)
                    # Success with no auth
                    self.success.emit(client, self.base, None)
                except Exception as probe_err:
                    import requests as _req
                    status = getattr(getattr(probe_err, 'response', None), 'status_code', None)
                    if isinstance(probe_err, _req.exceptions.HTTPError) and status == 401:
                        # Try anonymous login fallback
                        try:
                            from api.auth import AuthClient
                            auth = AuthClient(self.base)
                            token = auth.login("anonymous", "anonymous")
                            if not token:
                                raise RuntimeError("Anonymous login failed")
                            client.set_token(token)
                            self.success.emit(client, self.base, "anonymous")
                        except Exception as anon_err:
                            raise anon_err
                    else:
                        raise probe_err
        except Exception as e:
            error_msg = str(e).lower()
            if "connection" in error_msg or "timeout" in error_msg or "max retries" in error_msg:
                friendly = (f"Cannot connect to server at {self.base}.\n\nPlease check:\n"
                          "• Server URL is correct\n• Server is running\n• Network connection is available")
            elif "invalid" in error_msg or "unauthorized" in error_msg:
                friendly = "Invalid username or password."
            else:
                friendly = f"Failed to connect: {e}"
            self.error.emit(str(e), friendly)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stremer - Windows Client")
        self.resize(1200, 800)

        # Set application/window icon from repo root app.ico if available
        try:
            here = Path(__file__).resolve()
            candidates = [
                here.parents[3] / "app.ico",                 # <repo>/app.ico
                here.parents[2] / "app.ico",                 # <client-windows>/app.ico (fallback)
                here.parents[2] / "assets" / "app.ico",     # <client-windows>/assets/app.ico (fallback)
            ]
            for p in candidates:
                if p.exists():
                    self.setWindowIcon(QIcon(str(p)))
                    break
        except Exception:
            pass

        self.api_client: APIClient | None = None
        self._open_image_views: list[ImageViewer] = []
        self._open_music_players: list[MusicPlayer] = []
        self._open_mini_players = []
        self._current_login_thread: QThread | None = None

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


        # Add spacer to push About and dropdown to the right
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        # View mode selector (dropdown) just left of About
        self.view_combo = QComboBox(self)
        self.view_combo.addItems(["List", "Icons", "Thumbnails"])
        self.view_combo.setCurrentIndex(2)
        self.view_combo.setToolTip("Change view mode")
        self.view_combo.currentTextChanged.connect(self._on_view_change)
        toolbar.addWidget(self.view_combo)

        # About action on the extreme right
        self.about_action = QAction("About", self)
        self.about_action.triggered.connect(self._show_about)
        toolbar.addAction(self.about_action)

        # Central container: start screen + splitter
        from PyQt6.QtWidgets import QStackedLayout, QLabel
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
        self.browser = BrowserWidget(api_client=None, on_play=self._play, on_delete=self._delete, on_copy=self._copy, on_open=self._open_default, on_rename=self._rename, on_properties=self._show_properties, on_new_folder=self._new_folder, on_new_file=self._new_file, on_open_with=self._open_with, on_upload=self._upload, on_camera=self._open_camera_stream, on_play_mini=self._open_mini_player)
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

            # Pre-fill with last successful host
            last_host = self._get_last_host()
            if last_host:
                dlg.host_input.setText(last_host)

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

        # Warn user about disabled security before connecting
        try:
            warn = QMessageBox(dlg)
            warn.setIcon(QMessageBox.Icon.Warning)
            warn.setWindowTitle("Security Warning")
            warn.setText("Authentication is disabled on the server. Anyone on your network may be able to access your shared content.")
            warn.setInformativeText(
                "Recommended: On your Android device, open Stremer > Settings > enable 'Require authentication' and set a username & password."
            )
            warn.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok)
            ok_btn = warn.button(QMessageBox.StandardButton.Ok)
            if ok_btn:
                ok_btn.setText("Connect anyway")
            cancel_btn = warn.button(QMessageBox.StandardButton.Cancel)
            if cancel_btn:
                cancel_btn.setText("Cancel")
            choice = warn.exec()
            if choice != QMessageBox.StandardButton.Ok:
                return
        except Exception:
            # If QMessageBox customization fails, continue without blocking
            pass

        # Show progress dialog while connecting
        progress = QProgressDialog("Connecting...", None, 0, 0, dlg)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()

        # Run connection in background thread to keep UI responsive
        login_thread = _LoginThread(base)
        # Keep thread reference so it doesn't get garbage collected
        self._current_login_thread = login_thread

        def on_success(client, url, user_label):
            progress.close()
            self.api_client = client
            self.browser.set_api_client(client)
            self.details.set_api_client(client)
            token = client.token if getattr(client, 'token', None) else None
            auth_mode = 'auth disabled' if token is None else 'anonymous auth'
            self.statusBar().showMessage(f"Connected to {url} ({auth_mode})")
            self.login_action.setText("Logout")
            try:
                self.browser.load_path("/")
            except Exception as load_err:
                print(f"Error loading root path: {load_err}")
            try:
                self._show_main_view()
            except Exception:
                pass
            # Persist only if we have a token
            try:
                if token:
                    self._save_session(url, token, "anonymous")
                else:
                    # No token but successful - save just the host
                    self._save_last_host(url)
            except Exception:
                pass
            dlg.accept()
            # Clean up thread reference
            try:
                login_thread.wait(1000)
            except Exception:
                pass
            self._current_login_thread = None

        def on_error(error_raw, friendly_msg):
            progress.close()
            QMessageBox.critical(self, "Connection Error", friendly_msg)
            # Clean up thread reference
            try:
                login_thread.wait(1000)
            except Exception:
                pass
            self._current_login_thread = None

        login_thread.success.connect(on_success)
        login_thread.error.connect(on_error)
        login_thread.start()

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

        # Show progress dialog while connecting
        progress = QProgressDialog("Connecting...", None, 0, 0, dlg)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()

        # Run login in background thread to keep UI responsive
        login_thread = _LoginThread(base, user=user, pwd=pwd)
        # Keep thread reference so it doesn't get garbage collected
        self._current_login_thread = login_thread

        def on_success(client, url, user_label):
            progress.close()
            self.api_client = client
            self.browser.set_api_client(client)
            self.details.set_api_client(client)
            self.statusBar().showMessage(f"Connected to {url}")
            self.login_action.setText("Logout")
            try:
                self.browser.load_path("/")
            except Exception as load_err:
                print(f"Error loading root path: {load_err}")
            try:
                self._show_main_view()
            except Exception:
                pass
            # Persist session for 30 days, if requested
            try:
                token = client.token if getattr(client, 'token', None) else None
                if token and (getattr(dlg, 'remember_check', None) is None or dlg.remember_check.isChecked()):
                    self._save_session(url, token, user_label)
                else:
                    # Clear full session but always save last successful host
                    self._clear_saved_session()
                    self._save_last_host(url)
            except Exception:
                pass
            dlg.accept()
            # Clean up thread reference
            try:
                login_thread.wait(1000)  # Wait up to 1 second for thread to finish
            except Exception:
                pass
            self._current_login_thread = None

        def on_error(error_raw, friendly_msg):
            progress.close()
            QMessageBox.critical(self, "Connection Error", friendly_msg)
            # Clean up thread reference
            try:
                login_thread.wait(1000)
            except Exception:
                pass
            self._current_login_thread = None

        login_thread.success.connect(on_success)
        login_thread.error.connect(on_error)
        login_thread.start()

    def _refresh(self):
        if self.api_client:
            try:
                self.browser.load_path(self.browser.current_path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Refresh failed: {e}")
        else:
            QMessageBox.information(self, "Not connected", "Login first.")

    def _open_camera_stream(self):
        if not self.api_client:
            QMessageBox.information(self, "Not connected", "Login first.")
            return
        try:
            # Always create a fresh viewer so the stream thread starts cleanly
            try:
                if hasattr(self, "_camera_viewer") and self._camera_viewer is not None:
                    self._camera_viewer.close()
            except Exception:
                pass
            self._camera_viewer = CameraViewer(self.api_client, self)
            self._camera_viewer.show()
            self._camera_viewer.raise_()
            self._camera_viewer.activateWindow()
        except Exception as e:
            QMessageBox.critical(self, "Camera", f"Unable to open camera stream: {e}")

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

    def _show_about(self):
        try:
            from ui.about_dialog import AboutDialog
            dlg = AboutDialog(self)
            dlg.exec()
        except Exception as e:
            QMessageBox.information(self, "About", f"About dialog unavailable: {e}")

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
            self._cancel = False

        def cancel(self):
            self._cancel = True

        def run(self):
            try:
                with requests.get(self.url, headers=self.headers, stream=True, timeout=120) as r:
                    r.raise_for_status()
                    total = int(r.headers.get('Content-Length') or 0)
                    downloaded = 0
                    with open(self.dest, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=1024 * 64):
                            if self._cancel:
                                # Clean up partial file on cancel
                                try:
                                    f.close()
                                except Exception:
                                    pass
                                try:
                                    if os.path.exists(self.dest):
                                        os.remove(self.dest)
                                except Exception:
                                    pass
                                self.error.emit('Canceled')
                                return
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
            self._cancel = False

        def cancel(self):
            self._cancel = True

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
                                if self._cancel:
                                    try:
                                        f.close()
                                    except Exception:
                                        pass
                                    try:
                                        if os.path.exists(dest_path):
                                            os.remove(dest_path)
                                    except Exception:
                                        pass
                                    self.error.emit('Canceled')
                                    return
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
                        thread_self = self

                        class ProgressFileReader:
                            def __init__(self):
                                self.file = open(file_path, 'rb')
                                self.bytes_read = 0

                            def read(self, size=-1):
                                nonlocal last_update_time
                                # Abort early if upload was canceled
                                if getattr(thread_self, 'canceled', False):
                                    try:
                                        self.file.close()
                                    except Exception:
                                        pass
                                    raise Exception('Canceled')

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
                                try:
                                    self.file.close()
                                except Exception:
                                    pass

                        return ProgressFileReader()

                    try:
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
                        # If cancellation triggered the exception, finish gracefully
                        if getattr(self, 'canceled', False) and str(e) == 'Canceled':
                            # Delete the partially uploaded file from the server
                            try:
                                self.api_client.delete_file(remote_path)
                            except Exception as del_err:
                                print(f"Could not delete partial file {remote_path}: {del_err}")
                            # Emit done with current progress so UI treats it as canceled
                            self.done.emit(uploaded_count, uploaded_bytes)
                            return
                        else:
                            self.error.emit(f"Error uploading {remote_name}: {str(e)}")

                except Exception as e:
                    self.error.emit(f"Error uploading {remote_name}: {str(e)}")

            self.done.emit(uploaded_count, uploaded_bytes)

    def _open_default(self, path: str):
        if not self.api_client:
            return

        # Import Qt early to avoid UnboundLocalError
        from PyQt6.QtCore import Qt, QCoreApplication
        from PyQt6.QtWidgets import QFileDialog, QMessageBox

        name_lower = os.path.basename(path).lower()

        # If audio file, open in mini music player with playlist from current folder
        if self._is_audio(name_lower):
            try:
                # Get all audio files from current folder by reading the browser widget
                current_folder = os.path.dirname(path) or "/"

                # Build playlist from all audio files visible in the browser
                playlist = []
                current_index = 0

                # Get items from table view or icon list depending on current view mode
                if self.browser.view_mode == "list":
                    # Get from table
                    for row in range(self.browser.table.rowCount()):
                        item_widget = self.browser.table.item(row, 0)
                        if item_widget:
                            item_data = item_widget.data(Qt.ItemDataRole.UserRole)
                            if item_data and item_data.get("type") == "file":
                                item_name = item_data.get("name", "")
                                item_path = item_data.get("path", "")
                                if self._is_audio(item_name.lower()):
                                    url = self.api_client.stream_url(item_path)
                                    token = self.api_client.token if self.api_client.token else None
                                    playlist.append({"url": url, "token": token, "display_name": item_name})
                                    if item_path == path:
                                        current_index = len(playlist) - 1
                else:
                    # Get from icon list
                    for i in range(self.browser.icon_list.count()):
                        item_widget = self.browser.icon_list.item(i)
                        if item_widget:
                            item_data = item_widget.data(Qt.ItemDataRole.UserRole)
                            if item_data and item_data.get("type") == "file":
                                item_name = item_data.get("name", "")
                                item_path = item_data.get("path", "")
                                if self._is_audio(item_name.lower()):
                                    url = self.api_client.stream_url(item_path)
                                    token = self.api_client.token if self.api_client.token else None
                                    playlist.append({"url": url, "token": token, "display_name": item_name})
                                    if item_path == path:
                                        current_index = len(playlist) - 1

                # Fallback if no playlist found
                if not playlist:
                    url = self.api_client.stream_url(path)
                    token = self.api_client.token if self.api_client.token else None
                    display_name = os.path.basename(path).lstrip('/') or None
                    playlist = [{"url": url, "token": token, "display_name": display_name}]
                    current_index = 0

                print(f"Opening audio playlist with {len(playlist)} tracks, starting at index {current_index}")

                # Reuse existing full player if open
                if self._open_music_players:
                    player = self._open_music_players[0]
                    player.load_playlist_and_play(playlist, current_index)
                    self.statusBar().showMessage("Playing in existing music player…", 2000)
                    return

                # Otherwise reuse existing mini player if present
                if self._open_mini_players:
                    mini = self._open_mini_players[0]
                    mini.load_playlist_and_play(playlist, current_index)
                    self.statusBar().showMessage("Playing in existing mini player…", 2000)
                    return

                # Create MusicPlayer with playlist and starting index
                player = MusicPlayer(
                    playlist[current_index]["url"],
                    playlist[current_index]["token"],
                    playlist[current_index]["display_name"],
                    parent=None,
                    playlist=playlist,
                    start_index=current_index,
                    main_window=self
                )
                player.setModal(False)
                player.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
                self._open_music_players.append(player)

                def _cleanup_player():
                    try:
                        self._open_music_players.remove(player)
                    except ValueError:
                        pass
                player.destroyed.connect(lambda *_: _cleanup_player())

                player.show()
                self.statusBar().showMessage("Opening music player…", 2000)
                return
            except Exception as e:
                print(f"MusicPlayer error: {e}")
                import traceback
                traceback.print_exc()
                QMessageBox.critical(self, "Open failed", f"Could not open audio: {e}")
                return

        # If image file, open in in-app viewer without saving to disk
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
        # Ask user where to save the file instead of using a temp file
        base_name = os.path.basename(path).lstrip('/')
        if not base_name:
            base_name = "file"

        suggested = os.path.join(os.path.expanduser("~"), "Downloads", base_name)
        dest, _ = QFileDialog.getSaveFileName(self, f"Save {base_name} as", suggested)
        if not dest:
            return

        url = self.api_client.stream_url(path)
        # Don't add Authorization header since token is already in URL
        headers = {}

        self._dl = self._DownloadThread(url, dest, headers)
        dlg = QProgressDialog(f"Downloading {base_name}…", "Cancel", 0, 100, self)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        dlg.canceled.connect(self._dl.cancel)
        # update UI from progress
        self._dl.progress.connect(lambda p: (dlg.setValue(p), self.statusBar().showMessage(f"Downloading {base_name}… {p}%")))
        # ensure dialog closes on completion/error
        self._dl.done.connect(lambda _p: dlg.close())
        self._dl.error.connect(lambda _m: dlg.close())
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
        dlg.show()

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

        # Ask user where to save the file before opening with external app
        base_name = os.path.basename(path).lstrip('/')
        if not base_name:
            base_name = "file"
        from PyQt6.QtWidgets import QFileDialog, QProgressDialog
        from PyQt6.QtCore import Qt

        suggested = os.path.join(os.path.expanduser("~"), "Downloads", base_name)
        dest, _ = QFileDialog.getSaveFileName(self, f"Save {base_name} as", suggested)
        if not dest:
            return

        url = self.api_client.stream_url(path)
        # Don't add Authorization header since token is already in URL
        headers = {}

        self._dl = self._DownloadThread(url, dest, headers)
        dlg = QProgressDialog(f"Downloading {base_name}…", "Cancel", 0, 100, self)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        dlg.canceled.connect(self._dl.cancel)
        self._dl.progress.connect(lambda p: (dlg.setValue(p), self.statusBar().showMessage(f"Downloading {base_name}… {p}%")))
        self._dl.done.connect(lambda _p: dlg.close())
        self._dl.error.connect(lambda _m: dlg.close())

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
        dlg.show()

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

    def _is_audio(self, name_lower: str) -> bool:
        return name_lower.endswith((
            ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".opus"
        ))

    def _open_mini_player_dialog(self):
        """Open a dialog to select an audio file and play in mini player"""
        if not self.api_client:
            return
        self.statusBar().showMessage("Select an audio file to play in mini player", 3000)

    def _open_mini_player(self, path: str):
        """Open an audio file in the mini player instead of full player"""
        if not self.api_client:
            return
        try:
            from ui.music_player import MiniMusicPlayer
            url = self.api_client.stream_url(path)
            token = self.api_client.token if self.api_client.token else None
            display_name = os.path.basename(path).lstrip('/') or None

            playlist = [{"url": url, "token": token, "display_name": display_name}]

            print(f"MiniMusicPlayer: opening {path}")
            print(f"MiniMusicPlayer: url={url}")
            # Reuse existing mini player if available
            if self._open_mini_players:
                mini = self._open_mini_players[0]
                mini.load_playlist_and_play(playlist, 0)
                self.statusBar().showMessage("Playing in existing mini player…", 2000)
                return

            mini = MiniMusicPlayer(url, token, display_name, parent=None, main_window=self, playlist=playlist, current_index=0)
            mini.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            mini.show()
            self._open_mini_players.append(mini)
            def _cleanup_mini():
                try:
                    self._open_mini_players.remove(mini)
                except ValueError:
                    pass
            mini.destroyed.connect(lambda *_: _cleanup_mini())
            self.statusBar().showMessage("Opening mini player…", 2000)
        except Exception as e:
            print(f"MiniMusicPlayer error: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Open failed", f"Could not open audio: {e}")

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
            from PyQt6.QtWidgets import QProgressDialog
            from PyQt6.QtCore import Qt

            self._ddl = self._DownloadDirThread(self.api_client, src_path, target_dir)
            dlg = QProgressDialog(f"Downloading folder {base_name}…", "Cancel", 0, 100, self)
            dlg.setWindowModality(Qt.WindowModality.WindowModal)
            dlg.setAutoClose(False)
            dlg.setAutoReset(False)
            dlg.setValue(0)
            dlg.canceled.connect(self._ddl.cancel)
            self._ddl.progress.connect(lambda p: (dlg.setValue(p), self.statusBar().showMessage(f"Downloading folder {base_name}… {p}%")))
            self._ddl.message.connect(lambda m: (dlg.setLabelText(m), self.statusBar().showMessage(m)))
            self._ddl.done.connect(lambda p: (dlg.close(), self.statusBar().showMessage(f"Folder saved to {p}", 5000)))
            self._ddl.error.connect(lambda msg: (dlg.close(), QMessageBox.critical(self, "Download failed", msg)))
            self._ddl.start()
            dlg.show()
        else:
            dest = os.path.join(dest_folder, base_name)
            url = self.api_client.stream_url(src_path)
            headers = {}
            if self.api_client.token:
                headers["Authorization"] = f"Bearer {self.api_client.token}"
            from PyQt6.QtWidgets import QProgressDialog
            from PyQt6.QtCore import Qt

            self._dl = self._DownloadThread(url, dest, headers)
            dlg = QProgressDialog(f"Downloading {base_name}…", "Cancel", 0, 100, self)
            dlg.setWindowModality(Qt.WindowModality.WindowModal)
            dlg.setAutoClose(False)
            dlg.setAutoReset(False)
            dlg.setValue(0)
            dlg.canceled.connect(self._dl.cancel)
            self._dl.progress.connect(lambda p: (dlg.setValue(p), self.statusBar().showMessage(f"Downloading {base_name}… {p}%")))
            self._dl.done.connect(lambda _p: dlg.close())
            self._dl.error.connect(lambda _m: dlg.close())
            def _done(local_path: str):
                self.statusBar().showMessage(f"Saved to {local_path}", 5000)
            def _err(msg: str):
                QMessageBox.critical(self, "Download failed", msg)
                self.statusBar().clearMessage()
            self._dl.done.connect(_done)
            self._dl.error.connect(_err)
            self._dl.start()
            dlg.show()

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
            'expires_at': int(time.time()) + 30 * 24 * 3600,
            'last_successful_host': base_url
        }
        try:
            self._session_file().write_text(json.dumps(data))
        except Exception:
            pass

    def _save_last_host(self, base_url: str):
        """Save only the last successful host without session token."""
        try:
            fp = self._session_file()
            data = {}
            if fp.exists():
                try:
                    data = json.loads(fp.read_text())
                except Exception:
                    pass
            data['last_successful_host'] = base_url
            fp.write_text(json.dumps(data))
        except Exception:
            pass

    def _get_last_host(self) -> str | None:
        """Retrieve the last successful host URL."""
        try:
            fp = self._session_file()
            if fp.exists():
                data = json.loads(fp.read_text())
                return data.get('last_successful_host')
        except Exception:
            pass
        return None

    def _clear_saved_session(self):
        """Clear session token but preserve last successful host."""
        try:
            fp = self._session_file()
            if fp.exists():
                # Read existing data to preserve last_successful_host
                try:
                    data = json.loads(fp.read_text())
                    last_host = data.get('last_successful_host')
                    if last_host:
                        # Write back only the last host
                        fp.write_text(json.dumps({'last_successful_host': last_host}))
                    else:
                        # No host to preserve, delete file
                        fp.unlink()
                except Exception:
                    # If we can't read, just delete
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
