from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QMenu,
    QListWidget,
    QListWidgetItem,
    QListView,
)
from PyQt6.QtCore import Qt, QPoint, QSize, QUrl, pyqtSignal
from PyQt6.QtWidgets import QStyle
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest


class BrowserWidget(QWidget):
    path_changed = pyqtSignal(str)
    selection_changed = pyqtSignal(dict)
    selection_cleared = pyqtSignal()

    def __init__(self, api_client, on_play, on_delete, on_copy, on_open=None, on_rename=None, on_properties=None):
        super().__init__()
        self.api_client = api_client
        self.on_play = on_play
        self.on_delete = on_delete
        self.on_copy = on_copy
        self.on_open = on_open
        self.on_rename = on_rename
        self.on_properties = on_properties
        self.current_path = "/"
        self.view_mode = "list"  # list | icons | thumbnails
        self._net = QNetworkAccessManager(self)
        self._thumb_cache = {}
        self._thumb_queue = {}
        self._back_stack: list[str] = []
        self._forward_stack: list[str] = []

        layout = QVBoxLayout(self)
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
        if not item:
            return
        menu = QMenu(self)
        if item["type"] == "file":
            name_lower = item["name"].lower()
            if self._is_video(name_lower):
                menu.addAction("Play in VLC")
            else:
                menu.addAction("Open")
        menu.addAction("Rename")
        copy_act = menu.addAction("Download")
        del_act = menu.addAction("Delete")
        props_act = menu.addAction("Properties")
        act = menu.exec(self.table.mapToGlobal(pos))
        if act:
            name_lower = item["name"].lower()
            if act.text() == "Play in VLC" and item["type"] == "file" and self._is_video(name_lower):
                self.on_play(item["path"])
            elif act.text() == "Open" and item["type"] == "file" and self.on_open:
                self.on_open(item["path"])
            elif act.text() == "Rename" and self.on_rename:
                self.on_rename(item["path"])
            elif act.text() == "Download":
                self.on_copy(item["path"])
            elif act.text() == "Delete":
                self.on_delete(item["path"])
            elif act.text() == "Properties" and self.on_properties:
                self.on_properties(item)

    def _open_context_menu_icons(self, pos: QPoint):
        item_widget = self.icon_list.itemAt(pos)
        if not item_widget:
            return
        data = item_widget.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        if data["type"] == "file":
            name_lower = data["name"].lower()
            if self._is_video(name_lower):
                menu.addAction("Play in VLC")
            else:
                menu.addAction("Open")
        menu.addAction("Rename")
        menu.addAction("Download")
        menu.addAction("Delete")
        menu.addAction("Properties")
        act = menu.exec(self.icon_list.mapToGlobal(pos))
        if act:
            name_lower = data["name"].lower()
            if act.text() == "Play in VLC" and data["type"] == "file" and self._is_video(name_lower):
                self.on_play(data["path"])
            elif act.text() == "Open" and data["type"] == "file" and self.on_open:
                self.on_open(data["path"])
            elif act.text() == "Rename" and self.on_rename:
                self.on_rename(data["path"])
            elif act.text() == "Download":
                self.on_copy(data["path"])
            elif act.text() == "Delete":
                self.on_delete(data["path"])
            elif act.text() == "Properties" and self.on_properties:
                self.on_properties(data)

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
            pix = self._thumb_cache[key]
            list_item.setIcon(QIcon(pix))
            return
        # Avoid duplicate requests
        if key in self._thumb_queue:
            self._thumb_queue[key].append(list_item)
            return
        self._thumb_queue[key] = [list_item]

        url = self.api_client.thumb_url(path, self.icon_list.iconSize().width(), self.icon_list.iconSize().height())
        req = QNetworkRequest(QUrl(url))
        # Pass bearer to authenticated /thumb
        if getattr(self.api_client, 'token', None):
            req.setRawHeader(b"Authorization", f"Bearer {self.api_client.token}".encode("utf-8"))
        reply = self._net.get(req)

        def _on_finished():
            data = reply.readAll()
            reply.deleteLater()
            if not data:
                # Clean queue
                self._thumb_queue.pop(key, None)
                return
            pixmap = QPixmap()
            if pixmap.loadFromData(bytes(data)):
                # Resize to icon size if larger
                if pixmap.width() > self.icon_list.iconSize().width() or pixmap.height() > self.icon_list.iconSize().height():
                    pixmap = pixmap.scaled(self.icon_list.iconSize(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self._thumb_cache[key] = pixmap
                for li in self._thumb_queue.get(key, []):
                    li.setIcon(QIcon(pixmap))
            self._thumb_queue.pop(key, None)

        reply.finished.connect(_on_finished)
