from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QMenu,
    QListWidget,
    QListWidgetItem,
    QListView,
    QToolButton,
    QTreeView,
)
from PyQt6.QtCore import Qt, QPoint, QSize, QUrl, pyqtSignal
from PyQt6.QtWidgets import QStyle
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest


class BrowserWidget(QWidget):
    path_changed = pyqtSignal(str)
    selection_changed = pyqtSignal(dict)
    selection_cleared = pyqtSignal()

    def __init__(self, api_client, on_play, on_delete, on_copy, on_open=None, on_rename=None, on_properties=None, on_new_folder=None, on_new_file=None, on_open_with=None, on_upload=None):
        super().__init__()
        self.api_client = api_client
        self.on_play = on_play
        self.on_delete = on_delete
        self.on_copy = on_copy
        self.on_open = on_open
        self.on_rename = on_rename
        self.on_properties = on_properties
        self.on_new_folder = on_new_folder
        self.on_new_file = on_new_file
        self.on_open_with = on_open_with
        self.on_upload = on_upload
        self.current_path = "/"
        self.view_mode = "list"  # list | icons | thumbnails
        self._net = QNetworkAccessManager(self)
        self._thumb_cache = {}
        # Track in-flight thumbnail requests by key (path, w, h) without holding item refs
        self._thumb_inflight: set[tuple[str, int, int]] = set()
        self._thumb_pending = []  # list of (key_tuple, url)
        self._thumb_active = 0
        self._back_stack: list[str] = []
        self._forward_stack: list[str] = []

        layout = QVBoxLayout(self)

        # Toolbar with upload button
        toolbar_layout = QHBoxLayout()

        self.upload_btn = QToolButton()
        self.upload_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        self.upload_btn.setToolTip("Upload files/folders")
        self.upload_btn.clicked.connect(self._on_upload_clicked)
        toolbar_layout.addWidget(self.upload_btn)

        toolbar_layout.addStretch()
        layout.addLayout(toolbar_layout)
        # List (table) view
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Size"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._open_context_menu)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        # Icon/thumbnail view
        self.icon_list = QListWidget()
        self.icon_list.setViewMode(QListView.ViewMode.IconMode)
        self.icon_list.setMovement(QListView.Movement.Static)
        self.icon_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.icon_list.setIconSize(QSize(64, 64))
        self.icon_list.setGridSize(QSize(120, 110))
        self.icon_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.icon_list.customContextMenuRequested.connect(self._open_context_menu_icons)
        self.icon_list.doubleClicked.connect(self._on_icon_double_click)
        self.icon_list.itemSelectionChanged.connect(self._on_selection_changed)

        layout.addWidget(self.table)
        layout.addWidget(self.icon_list)
        self.icon_list.hide()

    def set_view_mode(self, mode: str):
        mode = mode.lower()
        if mode not in ("list", "icons", "thumbnails"):
            mode = "list"
        self.view_mode = mode
        if mode == "list":
            self.table.show()
            self.icon_list.hide()
        else:
            # Icon sizes for icons vs thumbnails
            if mode == "icons":
                self.icon_list.setIconSize(QSize(48, 48))
                self.icon_list.setGridSize(QSize(120, 100))
            else:  # thumbnails
                self.icon_list.setIconSize(QSize(112, 112))
                self.icon_list.setGridSize(QSize(150, 140))
            self.table.hide()
            self.icon_list.show()
        # Reload current path to apply view change
        self.load_path(self.current_path)

    def _fmt_size(self, size):
        try:
            if size is None or size == "":
                return "-"
            size = int(size)
            units = ["B", "KB", "MB", "GB", "TB"]
            i = 0
            while size >= 1024 and i < len(units) - 1:
                size /= 1024.0
                i += 1
            if i == 0:
                return f"{int(size)} {units[i]}"
            return f"{size:.1f} {units[i]}"
        except Exception:
            return str(size)

    def load_path(self, path: str = "/"):
        self.current_path = path
        if not self.api_client:
            # No API client yet; clear view
            self.table.setRowCount(0)
            self.icon_list.clear()
            self.path_changed.emit(self.current_path)
            self.selection_cleared.emit()
            return
        items = self.api_client.list_files(path)
        # Clear selections
        self.table.clearSelection()
        self.icon_list.clearSelection()
        if self.view_mode == "list":
            self.table.setRowCount(0)
            for item in items:
                row = self.table.rowCount()
                self.table.insertRow(row)
                name = item.get("name", "")
                type_ = item.get("type", "file")
                size_val = item.get("size", None)
                path_full = f"{self.current_path.rstrip('/')}/{name}" if self.current_path != "/" else f"/{name}"
                name_item = QTableWidgetItem(name)
                # Attach metadata to first column item for retrieval
                name_item.setData(Qt.ItemDataRole.UserRole, {"name": name, "type": type_, "path": path_full, "size": size_val})
                self.table.setItem(row, 0, name_item)
                self.table.setItem(row, 1, QTableWidgetItem(type_))
                size_text = self._fmt_size(item.get("size", None)) if item.get("type") == "file" else "-"
                self.table.setItem(row, 2, QTableWidgetItem(size_text))
                self.table.setRowHeight(row, 24)
            self.table.resizeColumnsToContents()
        else:
            self.icon_list.clear()
            style = self.style()
            folder_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
            file_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
            for it in items:
                name = it.get("name", "")
                type_ = it.get("type", "file")
                size_val = it.get("size", None)
                size_text = self._fmt_size(size_val) if type_ == "file" else ""
                text = f"{name}\n{size_text}" if size_text else name
                icon = folder_icon if type_ == "dir" else file_icon
                item = QListWidgetItem(icon, text)
                # Store metadata for context/double-click
                path_full = f"{self.current_path.rstrip('/')}/{name}" if self.current_path != "/" else f"/{name}"
                item.setData(Qt.ItemDataRole.UserRole, {"name": name, "type": type_, "path": path_full, "size": size_val})
                self.icon_list.addItem(item)

                # If thumbnails mode and file is image/video, try loading thumbnail
                if self.view_mode == "thumbnails" and type_ == "file":
                    lower = name.lower()
                    if lower.endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".mp4", ".mkv", ".avi", ".mov", ".webm")):
                        self._load_thumbnail_async(item, path_full)
        # Notify listeners that path changed
        self.path_changed.emit(self.current_path)
        self.selection_cleared.emit()

    def navigate_to(self, path: str):
        # Push current path to back history if not the same
        if path != self.current_path:
            if self.current_path:
                self._back_stack.append(self.current_path)
            # Clear forward history
            self._forward_stack.clear()
        self.load_path(path)

    def can_go_back(self) -> bool:
        return len(self._back_stack) > 0

    def can_go_up(self) -> bool:
        return self.current_path != "/"

    def go_back(self):
        if not self._back_stack:
            return
        prev = self._back_stack.pop()
        # Current goes to forward stack
        if self.current_path:
            self._forward_stack.append(self.current_path)
        self.load_path(prev)

    def go_up(self):
        # Compute parent directory
        cur = self.current_path or "/"
        if cur == "/":
            return
        # Normalize
        if not cur.startswith("/"):
            cur = "/" + cur
        parent = cur.rsplit("/", 1)[0]
        if parent == "":
            parent = "/"
        self.navigate_to(parent)

    def _selected_item(self):
        if self.view_mode == "list":
            idx = self.table.currentRow()
            if idx < 0:
                return None
            name_item = self.table.item(idx, 0)
            if name_item is not None:
                data = name_item.data(Qt.ItemDataRole.UserRole)
                if data:
                    return data
            # Fallback reconstruction
            name = self.table.item(idx, 0).text()
            type_ = self.table.item(idx, 1).text()
            path = f"{self.current_path.rstrip('/')}/{name}" if self.current_path != "/" else f"/{name}"
            return {"name": name, "type": type_, "path": path}
        else:
            item = self.icon_list.currentItem()
            if not item:
                return None
            data = item.data(Qt.ItemDataRole.UserRole)
            return data

    def _open_context_menu(self, pos: QPoint):
        item = self._selected_item()
        menu = QMenu(self)
        if item:
            if item["type"] == "file":
                name_lower = item["name"].lower()
                if self._is_video(name_lower):
                    menu.addAction("Play in VLC")
                else:
                    menu.addAction("Open")

                # Add "Open With" submenu
                if self.on_open_with:
                    open_with_menu = menu.addMenu("Open With")
                    apps = self._get_associated_apps(item["name"])
                    if apps:
                        for app_name, app_path in apps:
                            action = open_with_menu.addAction(app_name)
                            action.setData({"path": item["path"], "app": app_path})
                    open_with_menu.addSeparator()
                    choose_action = open_with_menu.addAction("Choose another app...")
                    choose_action.setData({"path": item["path"], "app": None})

            menu.addAction("Rename")
            menu.addAction("Download")
            menu.addAction("Delete")
            menu.addAction("Properties")
        else:
            if self.on_new_folder:
                menu.addAction("New Folder")
            if self.on_new_file:
                menu.addAction("New File")
        act = menu.exec(self.table.mapToGlobal(pos))
        if act:
            # Check if it's an "Open With" action
            if act.data() and isinstance(act.data(), dict) and "app" in act.data():
                data = act.data()
                if self.on_open_with:
                    self.on_open_with(data["path"], data["app"])
            elif item:
                name_lower = item["name"].lower()
                if act.text() == "Play in VLC" and item["type"] == "file" and self._is_video(name_lower):
                    self.on_play(item["path"])
                elif act.text() == "Open" and item["type"] == "file" and self.on_open:
                    print(f"DEBUG browser_widget: About to call on_open({item['path']})")
                    self.on_open(item["path"])
                    print("DEBUG browser_widget: on_open() returned")
                elif act.text() == "Rename" and self.on_rename:
                    self.on_rename(item["path"])
                elif act.text() == "Download":
                    self.on_copy(item["path"])
                elif act.text() == "Delete":
                    self.on_delete(item["path"])
                elif act.text() == "Properties" and self.on_properties:
                    self.on_properties(item)
            else:
                if act.text() == "New Folder" and self.on_new_folder:
                    self.on_new_folder(self.current_path)
                elif act.text() == "New File" and self.on_new_file:
                    self.on_new_file(self.current_path)

    def _open_context_menu_icons(self, pos: QPoint):
        item_widget = self.icon_list.itemAt(pos)
        data = item_widget.data(Qt.ItemDataRole.UserRole) if item_widget else None
        menu = QMenu(self)
        if data:
            if data["type"] == "file":
                name_lower = data["name"].lower()
                if self._is_video(name_lower):
                    menu.addAction("Play in VLC")
                else:
                    menu.addAction("Open")

                # Add "Open With" submenu
                if self.on_open_with:
                    open_with_menu = menu.addMenu("Open With")
                    apps = self._get_associated_apps(data["name"])
                    if apps:
                        for app_name, app_path in apps:
                            action = open_with_menu.addAction(app_name)
                            action.setData({"path": data["path"], "app": app_path})
                    open_with_menu.addSeparator()
                    choose_action = open_with_menu.addAction("Choose another app...")
                    choose_action.setData({"path": data["path"], "app": None})

            menu.addAction("Rename")
            menu.addAction("Download")
            menu.addAction("Delete")
            menu.addAction("Properties")
        else:
            if self.on_new_folder:
                menu.addAction("New Folder")
            if self.on_new_file:
                menu.addAction("New File")
        act = menu.exec(self.icon_list.mapToGlobal(pos))
        if act:
            # Check if it's an "Open With" action
            if act.data() and isinstance(act.data(), dict) and "app" in act.data():
                act_data = act.data()
                if self.on_open_with:
                    self.on_open_with(act_data["path"], act_data["app"])
            elif data:
                name_lower = data["name"].lower()
                if act.text() == "Play in VLC" and data["type"] == "file" and self._is_video(name_lower):
                    self.on_play(data["path"])
                elif act.text() == "Open" and data["type"] == "file" and self.on_open:
                    print(f"DEBUG browser_widget (icons): About to call on_open({data['path']})")
                    self.on_open(data["path"])
                    print("DEBUG browser_widget (icons): on_open() returned")
                elif act.text() == "Rename" and self.on_rename:
                    self.on_rename(data["path"])
                elif act.text() == "Download":
                    self.on_copy(data["path"])
                elif act.text() == "Delete":
                    self.on_delete(data["path"])
                elif act.text() == "Properties" and self.on_properties:
                    self.on_properties(data)
            else:
                if act.text() == "New Folder" and self.on_new_folder:
                    self.on_new_folder(self.current_path)
                elif act.text() == "New File" and self.on_new_file:
                    self.on_new_file(self.current_path)

        print("DEBUG browser_widget: _open_context_menu_icons completed")

    def _on_double_click(self):
        item = self._selected_item()
        if not item:
            return
        if item["type"] == "dir":
            self.navigate_to(item["path"])  # navigate into directory

    def _on_icon_double_click(self):
        item = self.icon_list.currentItem()
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "dir":
            self.navigate_to(data.get("path"))

    def set_api_client(self, api_client):
        self.api_client = api_client

    def _is_video(self, name_lower: str) -> bool:
        return name_lower.endswith((
            ".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".3gp", ".ts"
        ))

    def _on_selection_changed(self):
        item = self._selected_item()
        if item:
            self.selection_changed.emit(item)
        else:
            self.selection_cleared.emit()

    def _load_thumbnail_async(self, list_item: QListWidgetItem, path: str):
        if not self.api_client:
            return
        # Cache key
        key = (path, self.icon_list.iconSize().width(), self.icon_list.iconSize().height())
        if key in self._thumb_cache:
            # Apply cached pixmap to any current items matching this path
            pix = self._thumb_cache[key]
            self._apply_thumb_to_items(key, pix)
            return
        # Avoid duplicate requests
        if key in self._thumb_inflight:
            return
        self._thumb_inflight.add(key)

        url = self.api_client.thumb_url(path, self.icon_list.iconSize().width(), self.icon_list.iconSize().height())
        # Queue request; we'll limit concurrent downloads
        self._thumb_pending.append((key, url))
        self._start_next_thumb()

    def _start_next_thumb(self):
        # Limit concurrent thumbnail fetches to reduce load on server/device
        MAX_CONCURRENT = 4
        while self._thumb_active < MAX_CONCURRENT and self._thumb_pending:
            key, url = self._thumb_pending.pop(0)

            req = QNetworkRequest(QUrl(url))
            if getattr(self.api_client, 'token', None):
                req.setRawHeader(b"Authorization", f"Bearer {self.api_client.token}".encode("utf-8"))
            reply = self._net.get(req)
            self._thumb_active += 1

            def _on_finished(reply=reply, key=key):
                try:
                    data = reply.readAll()
                finally:
                    reply.deleteLater()
                if not data:
                    # Nothing to do; drop inflight marker
                    pass
                else:
                    pixmap = QPixmap()
                    if pixmap.loadFromData(bytes(data)):
                        # Resize to icon size if larger
                        if pixmap.width() > self.icon_list.iconSize().width() or pixmap.height() > self.icon_list.iconSize().height():
                            pixmap = pixmap.scaled(self.icon_list.iconSize(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        self._thumb_cache[key] = pixmap
                        self._apply_thumb_to_items(key, pixmap)
                # Clean up inflight marker
                if key in self._thumb_inflight:
                    self._thumb_inflight.remove(key)
                self._thumb_active = max(0, self._thumb_active - 1)
                # Kick off next batch
                self._start_next_thumb()

            reply.finished.connect(_on_finished)

    def _apply_thumb_to_items(self, key: tuple[str, int, int], pixmap: QPixmap):
        """Safely apply thumbnail to any current items for the given key's path.
        Avoids keeping stale QListWidgetItem references across async boundaries.
        """
        path, _w, _h = key
        icon = QIcon(pixmap)
        # Update in icons view if visible
        try:
            for i in range(self.icon_list.count()):
                it = self.icon_list.item(i)
                if not it:
                    continue
                data = it.data(Qt.ItemDataRole.UserRole)
                if not data:
                    continue
                if data.get("path") == path:
                    it.setIcon(icon)
        except Exception:
            # Be defensive; never crash UI due to thumbnail update
            pass

    def _get_associated_apps(self, filename: str):
        """Get list of associated applications for a file extension from Windows registry."""
        import os
        import winreg

        # Get file extension
        _, ext = os.path.splitext(filename)
        if not ext:
            return []

        ext = ext.lower()
        apps = []

        try:
            # Try to get associated applications from registry
            # Check HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                   f"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\{ext}\\OpenWithList") as key:
                    i = 0
                    while True:
                        try:
                            app_name = winreg.EnumValue(key, i)[1]
                            if app_name and isinstance(app_name, str) and app_name != "MRUList":
                                # Try to find the full path
                                app_path = self._find_app_path(app_name)
                                if app_path:
                                    # Get friendly name (without .exe)
                                    friendly_name = os.path.splitext(app_name)[0]
                                    apps.append((friendly_name, app_path))
                            i += 1
                        except OSError:
                            break
            except FileNotFoundError:
                pass

            # Also check default program
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ext) as key:
                    prog_id = winreg.QueryValue(key, None)
                    if prog_id:
                        try:
                            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"{prog_id}\\shell\\open\\command") as cmd_key:
                                cmd = winreg.QueryValue(cmd_key, None)
                                if cmd:
                                    # Extract exe path from command
                                    import shlex
                                    parts = shlex.split(cmd.replace('"', '"').replace('"', '"'))
                                    if parts:
                                        exe_path = parts[0]
                                        if os.path.exists(exe_path):
                                            app_name = os.path.basename(exe_path)
                                            friendly_name = os.path.splitext(app_name)[0]
                                            # Add default app at the beginning if not already in list
                                            if not any(a[1].lower() == exe_path.lower() for a in apps):
                                                apps.insert(0, (f"{friendly_name} (default)", exe_path))
                        except FileNotFoundError:
                            pass
            except FileNotFoundError:
                pass

            # Add common apps for specific extensions
            common_apps = self._get_common_apps_for_ext(ext)
            for app_name, app_path in common_apps:
                if os.path.exists(app_path) and not any(a[1].lower() == app_path.lower() for a in apps):
                    apps.append((app_name, app_path))

        except Exception:
            pass

        return apps

    def _find_app_path(self, app_name: str):
        """Find full path of an application."""
        import os
        import winreg

        # Check if it's already a full path
        if os.path.exists(app_name):
            return app_name

        # Search in App Paths registry
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                               f"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{app_name}") as key:
                path = winreg.QueryValue(key, None)
                if path and os.path.exists(path):
                    return path
        except FileNotFoundError:
            pass

        # Search in PATH environment variable
        import shutil
        path = shutil.which(app_name)
        if path:
            return path

        return None

    def _get_common_apps_for_ext(self, ext: str):
        """Return common applications for specific file extensions."""
        import os

        common = []

        # Text files
        if ext in ['.txt', '.log', '.md', '.json', '.xml', '.csv']:
            notepad_path = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'notepad.exe')
            if os.path.exists(notepad_path):
                common.append(('Notepad', notepad_path))

        # Images
        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
            paint_path = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'System32', 'mspaint.exe')
            if os.path.exists(paint_path):
                common.append(('Paint', paint_path))

        # Videos
        if ext in ['.mp4', '.avi', '.mkv', '.mov', '.wmv']:
            # Windows Media Player
            wmp_path = os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'),
                                   'Windows Media Player', 'wmplayer.exe')
            if os.path.exists(wmp_path):
                common.append(('Windows Media Player', wmp_path))

        return common

    def _on_upload_clicked(self):
        """Handle upload button click - open file/folder selection dialog."""
        if self.on_upload:
            from PyQt6.QtWidgets import QFileDialog

            # Ask user what to upload
            dialog = QFileDialog(self)
            dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
            dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)

            # Enable selecting both files and folders
            file_view = dialog.findChild(QListView, "listView")
            if file_view:
                file_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

            tree_view = dialog.findChild(QTreeView)
            if tree_view:
                tree_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

            if dialog.exec():
                selected = dialog.selectedFiles()
                if selected:
                    self.on_upload(selected, self.current_path)
