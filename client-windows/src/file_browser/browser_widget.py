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
    QLineEdit,
    QComboBox,
    QLabel,
    QPushButton,
    QProgressBar,
)
from PyQt6.QtCore import Qt, QPoint, QSize, QUrl, pyqtSignal, QThread, QTimer
from PyQt6.QtWidgets import QStyle
from PyQt6.QtGui import QPixmap, QIcon, QCursor
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest


class FileLoaderThread(QThread):
    """Background thread for loading file lists to avoid blocking UI."""
    items_received = pyqtSignal(list)  # Emits items progressively as they're loaded
    load_complete = pyqtSignal(bool)  # Emits (has_more) when streaming completes or limit reached
    error = pyqtSignal(str)  # Emits error message if failed

    def __init__(self, api_client, path: str, limit: int = 100, offset: int = 0):
        super().__init__()
        self.api_client = api_client
        self.path = path
        self.limit = limit  # Max items to stream before stopping
        self.offset = offset  # Skip this many items before streaming
        self._cancelled = False
        self._batch = []  # Buffer items in small batches for efficient UI updates
        self._batch_size = 10  # Emit every 10 items
        self._total_received = 0

    def cancel(self):
        self._cancelled = True

    def _emit_batch(self):
        """Emit buffered items and clear batch."""
        if self._batch and not self._cancelled:
            self.items_received.emit(self._batch[:])
            self._batch.clear()

    def _on_item(self, item):
        """Callback when server sends an item."""
        if self._cancelled:
            return False  # Signal to stop streaming

        self._total_received += 1
        self._batch.append(item)

        # Emit in small batches to avoid UI lag but keep responsiveness
        if len(self._batch) >= self._batch_size:
            self._emit_batch()

        # Stop streaming if we've reached the limit
        if self._total_received >= self.limit:
            return False  # Signal to stop streaming

        return True  # Continue streaming

    def run(self):
        try:
            # Use streaming API with callback to emit items as they arrive
            error, has_more = self.api_client.stream_files(
                self.path,
                on_item_callback=self._on_item,
                max_items=self.limit,
                offset=self.offset
            )

            if self._cancelled:
                return

            # Emit any remaining buffered items
            self._emit_batch()

            if error:
                # Surface server-side error after streaming
                self.error.emit(error)
                return

            if not self._cancelled:
                self.load_complete.emit(has_more)
        except Exception as e:
            if not self._cancelled:
                self.error.emit(str(e))
class BrowserWidget(QWidget):
    path_changed = pyqtSignal(str)
    selection_changed = pyqtSignal(dict)
    selection_cleared = pyqtSignal()

    def __init__(self, api_client, on_play, on_delete, on_copy, on_open=None, on_rename=None, on_properties=None, on_new_folder=None, on_new_file=None, on_open_with=None, on_upload=None, on_camera=None, on_play_mini=None):
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
        self.on_camera = on_camera
        self.on_play_mini = on_play_mini
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
        self._last_search_items: list[dict] | None = None
        self._last_search_path: str | None = None
        self.sort_field = "name"  # name, date, size, type
        self.sort_ascending = True

        # File loading thread and progressive rendering
        self._loader_thread: FileLoaderThread | None = None
        self._all_loaded_items = []  # All items loaded so far
        self._is_loading = False
        self._load_complete = False
        self._has_more_items = False  # Track if more items are available
        self._initial_load_limit = 100  # Load 100 items initially

        layout = QVBoxLayout(self)

        # Toolbar with upload button
        toolbar_layout = QHBoxLayout()

        self.upload_btn = QToolButton()
        self.upload_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        self.upload_btn.setToolTip("Upload files/folders")
        self.upload_btn.clicked.connect(self._on_upload_clicked)
        toolbar_layout.addWidget(self.upload_btn)

        # Advanced search controls
        toolbar_layout.addSpacing(8)
        toolbar_layout.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Name contains...")
        self.search_input.setFixedWidth(180)
        toolbar_layout.addWidget(self.search_input)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Any", "File", "Folder"])
        self.type_combo.setFixedWidth(90)
        toolbar_layout.addWidget(self.type_combo)

        self.size_min = QLineEdit(); self.size_min.setPlaceholderText("Min KB")
        self.size_min.setFixedWidth(70)
        toolbar_layout.addWidget(self.size_min)
        self.size_max = QLineEdit(); self.size_max.setPlaceholderText("Max KB")
        self.size_max.setFixedWidth(70)
        toolbar_layout.addWidget(self.size_max)

        self.search_btn = QPushButton("🔍 Filter")
        self.search_btn.setFixedWidth(90)
        self.search_btn.setMinimumHeight(28)
        self.search_btn.setEnabled(False)  # Disabled until filters are entered
        self.search_btn.setStyleSheet(
            "QPushButton { "
            "background-color: #0078d4; color: white; border: none; border-radius: 4px; "
            "font-weight: bold; font-size: 11px; padding: 6px 12px; "
            "} "
            "QPushButton:hover:enabled { background-color: #106ebe; } "
            "QPushButton:pressed:enabled { background-color: #005a9e; } "
            "QPushButton:disabled { background-color: #cccccc; color: #666; }"
        )
        self.search_btn.clicked.connect(self._on_search)
        toolbar_layout.addWidget(self.search_btn)

        # Connect filter fields to enable/disable the search button
        self.search_input.textChanged.connect(self._update_filter_button_state)
        self.size_min.textChanged.connect(self._update_filter_button_state)
        self.size_max.textChanged.connect(self._update_filter_button_state)
        self.type_combo.currentTextChanged.connect(self._update_filter_button_state)

        self.clear_search_btn = QPushButton("✕ Clear")
        self.clear_search_btn.setFixedWidth(85)
        self.clear_search_btn.setMinimumHeight(28)
        self.clear_search_btn.setStyleSheet(
            "QPushButton { "
            "background-color: #6c757d; color: white; border: none; border-radius: 4px; "
            "font-weight: bold; font-size: 11px; padding: 6px 12px; "
            "} "
            "QPushButton:hover { background-color: #5a6268; } "
            "QPushButton:pressed { background-color: #4e555b; }"
        )
        self.clear_search_btn.clicked.connect(self._clear_search)
        toolbar_layout.addWidget(self.clear_search_btn)

        # Mini Player button (shown when audio files exist)
        self.mini_player_btn = QToolButton()
        self.mini_player_btn.setText("🎵 Mini Player")
        self.mini_player_btn.setToolTip("Play audio in mini player")
        self.mini_player_btn.setFixedHeight(28)
        self.mini_player_btn.setAutoRaise(True)
        self.mini_player_btn.setStyleSheet(
            "QToolButton { font-weight: bold; padding: 4px 10px; }"
        )
        self.mini_player_btn.clicked.connect(self._open_mini_player_for_first_audio)
        self.mini_player_btn.setVisible(False)  # Hidden by default

        # Camera streaming button (added later to right side)
        self.camera_btn = QToolButton()
        self.camera_btn.setText("Camera")
        self.camera_btn.setToolTip("Open live camera stream")
        self.camera_btn.setFixedHeight(28)
        self.camera_btn.setAutoRaise(True)
        self.camera_btn.setStyleSheet(
            "QToolButton { font-weight: bold; padding: 4px 10px; }"
        )
        self.camera_btn.clicked.connect(self._open_camera)

        # Sorting controls
        toolbar_layout.addSpacing(16)
        toolbar_layout.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Name", "Date", "Size", "Type"])
        self.sort_combo.setFixedWidth(90)
        self.sort_combo.currentTextChanged.connect(self._on_sort_changed)
        toolbar_layout.addWidget(self.sort_combo)

        self.sort_order_btn = QPushButton("↑")
        self.sort_order_btn.setFixedWidth(40)
        self.sort_order_btn.setMinimumHeight(28)
        self.sort_order_btn.setToolTip("Click to toggle sort order (ascending/descending)")
        self.sort_order_btn.setStyleSheet(
            "QPushButton { "
            "background-color: #6c757d; color: white; border: none; border-radius: 4px; "
            "font-weight: bold; font-size: 12px; padding: 4px; "
            "} "
            "QPushButton:hover { background-color: #5a6268; } "
            "QPushButton:pressed { background-color: #4e555b; }"
        )
        self.sort_order_btn.clicked.connect(self._toggle_sort_order)
        toolbar_layout.addWidget(self.sort_order_btn)

        toolbar_layout.addStretch()
        # Place mini player and camera buttons at the far right
        toolbar_layout.addWidget(self.mini_player_btn)
        toolbar_layout.addWidget(self.camera_btn)
        layout.addLayout(toolbar_layout)

        # Loading indicator
        self.loading_label = QLabel("Loading files...")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.setStyleSheet("QLabel { color: #666; font-size: 14px; padding: 20px; }")
        self.loading_label.hide()
        layout.addWidget(self.loading_label)

        # List (table) view
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Size"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._open_context_menu)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        # Connect scroll event for lazy loading
        self.table.verticalScrollBar().valueChanged.connect(self._on_table_scroll)

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
        # Connect scroll event for lazy loading
        self.icon_list.verticalScrollBar().valueChanged.connect(self._on_icon_scroll)

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

    def _on_sort_changed(self, text):
        """Handle sort field selection change."""
        sort_map = {"Name": "name", "Date": "date", "Size": "size", "Type": "type"}
        self.sort_field = sort_map.get(text, "name")
        # Re-render current items with new sort
        if self._last_search_items is not None:
            # Re-render search results
            if self.view_mode == "list":
                self._render_table(self._last_search_items, self.current_path)
            else:
                self._render_icons(self._last_search_items, self.current_path)
        else:
            # Re-load current path
            self.load_path(self.current_path)

    def _toggle_sort_order(self):
        """Toggle between ascending and descending sort order."""
        self.sort_ascending = not self.sort_ascending
        # Update button appearance
        self.sort_order_btn.setText("↑" if self.sort_ascending else "↓")
        # Re-render with new sort order
        if self._last_search_items is not None:
            # Re-render search results
            if self.view_mode == "list":
                self._render_table(self._last_search_items, self.current_path)
            else:
                self._render_icons(self._last_search_items, self.current_path)
        else:
            # Re-load current path
            self.load_path(self.current_path)

    def _sort_items(self, items):
        """Sort items based on current sort_field and sort_ascending settings."""
        def get_sort_key(item):
            if self.sort_field == "name":
                return item.get("name", "").lower()
            elif self.sort_field == "date":
                # lastModified is unix timestamp (int), sort numerically
                modified = item.get("lastModified")
                return modified if modified is not None else 0
            elif self.sort_field == "size":
                # Size in bytes, treat folders as 0
                if item.get("type") == "dir":
                    return -1  # Folders at top when sorting by size
                size = item.get("size")
                return size if size is not None else 0
            elif self.sort_field == "type":
                # Folders first (dir < file alphabetically), then by name
                type_val = item.get("type", "file")
                name = item.get("name", "").lower()
                return (type_val, name)
            return ""

        return sorted(items, key=get_sort_key, reverse=not self.sort_ascending)

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
            # No API client yet; clear and hide views
            self.table.setRowCount(0)
            self.icon_list.clear()
            self.table.hide()
            self.icon_list.hide()
            self.loading_label.hide()
            self._is_loading = False
            self._load_complete = False
            self.path_changed.emit(self.current_path)
            self.selection_cleared.emit()
            return

        # Cancel any existing loader thread IMMEDIATELY
        if self._loader_thread and self._loader_thread.isRunning():
            self._loader_thread.cancel()
            self._loader_thread.quit()
            self._loader_thread.wait(100)  # Wait max 100ms, then force continue

        # Reset state
        self._all_loaded_items.clear()
        self._is_loading = True
        self._load_complete = False
        self._has_more_items = False

        # Clear search state
        self._last_search_items = None
        self._last_search_path = None

        # Clear current view
        self.table.setRowCount(0)
        self.icon_list.clear()
        self.table.clearSelection()
        self.icon_list.clearSelection()

        # Show loading indicator prominently
        self.loading_label.setText(f"Loading {path}...")
        self.loading_label.show()

        # Hide views while loading
        self.table.hide()
        self.icon_list.hide()

        # Set cursor to wait
        self.setCursor(QCursor(Qt.CursorShape.WaitCursor))

        # Notify listeners that path has changed (updates nav buttons)
        self.path_changed.emit(self.current_path)
        self.selection_cleared.emit()

        # Start background loading with initial limit
        self._loader_thread = FileLoaderThread(self.api_client, path, limit=self._initial_load_limit)
        self._loader_thread.items_received.connect(self._on_items_received)
        self._loader_thread.load_complete.connect(self._on_load_complete)
        self._loader_thread.error.connect(self._on_load_error)
        self._loader_thread.start()

    def _on_items_received(self, items: list):
        """Called progressively as batches of items are loaded."""
        # On first batch, hide loading indicator and show view
        if len(self._all_loaded_items) == 0:
            self.loading_label.hide()
            if self.view_mode == "list":
                self.table.show()
                self.icon_list.hide()
            else:
                self.table.hide()
                self.icon_list.show()

        # Add new items to collection
        self._all_loaded_items.extend(items)

        # Just append new items without re-sorting (we'll sort on completion)
        if self.view_mode == "list":
            # Append new items to table
            self._render_table_chunk(items, self.current_path)
        else:
            # Append new items to icon list
            self._render_icons_chunk(items, self.current_path)
            # Immediately prioritize visible thumbnails after rendering
            if self.view_mode == "thumbnails":
                QTimer.singleShot(0, self._load_visible_thumbnails)

    def _on_load_complete(self, has_more: bool = False):
        """Called when streaming completes or limit reached."""
        self._is_loading = False
        self._load_complete = not has_more  # Only truly complete if no more items
        self._has_more_items = has_more
        self.unsetCursor()

    def _on_table_scroll(self, value):
        """Called when table is scrolled - load more items if near bottom."""
        if not self._has_more_items or self._is_loading:
            return

        scrollbar = self.table.verticalScrollBar()
        # Load more when scrolled 80% to bottom
        if scrollbar.maximum() > 0:
            scroll_percentage = value / scrollbar.maximum()
            if scroll_percentage > 0.8:
                self._load_more_items()

    def _on_icon_scroll(self, value):
        """Called when icon list is scrolled - load more items if near bottom."""
        # Load more file items if near bottom
        if self._has_more_items and not self._is_loading:
            scrollbar = self.icon_list.verticalScrollBar()
            # Load more when scrolled 80% to bottom
            if scrollbar.maximum() > 0:
                scroll_percentage = value / scrollbar.maximum()
                if scroll_percentage > 0.8:
                    self._load_more_items()

        # Also load thumbnails for newly visible items
        if self.view_mode == "thumbnails":
            self._load_visible_thumbnails()
        """Load next batch of items when scrolled near bottom."""
        if self._is_loading or self._load_complete:
            return

        # Cancel any existing thread first
        if self._loader_thread and self._loader_thread.isRunning():
            self._loader_thread.cancel()
            self._loader_thread.quit()
            self._loader_thread.wait(100)

        self._is_loading = True
        self.setCursor(Qt.CursorShape.WaitCursor)

        # Load next batch (100 more items) starting from current offset
        # We use offset = len(all_loaded_items) to skip items already loaded
        offset = len(self._all_loaded_items)
        self._loader_thread = FileLoaderThread(
            self.api_client,
            self.current_path,
            limit=100,
            offset=offset
        )
        self._loader_thread.items_received.connect(self._on_items_received)
        self._loader_thread.load_complete.connect(self._on_load_complete)
        self._loader_thread.error.connect(self._on_load_error)
        self._loader_thread.start()

    def _on_load_error(self, error_msg: str):
        """Called when file loading fails."""
        self._is_loading = False
        self._load_complete = True
        self.loading_label.setText(f"Error loading files: {error_msg}")
        self.loading_label.show()
        self.unsetCursor()
        # Show empty view
        self.table.show()
        self.icon_list.hide()
        self.table.setRowCount(0)

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

    def _render_table(self, items, base_path: str):
        """Legacy method - renders all items at once. Now replaced by chunked rendering."""
        self.table.setRowCount(0)
        sorted_items = self._sort_items(items)
        self._render_table_chunk(sorted_items, base_path)
        self.table.resizeColumnsToContents()

    def _render_table_chunk(self, items, base_path: str):
        """Render a chunk of items to the table view."""
        for item in items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name = item.get("name", "")
            type_ = item.get("type", "file")
            size_val = item.get("size", None)
            path_full = item.get("path") or (f"{base_path.rstrip('/')}/{name}" if base_path != "/" else f"/{name}")
            name_item = QTableWidgetItem(name)
            # Attach metadata to first column item for retrieval
            name_item.setData(Qt.ItemDataRole.UserRole, {"name": name, "type": type_, "path": path_full, "size": size_val})
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(type_))
            size_text = self._fmt_size(item.get("size", None)) if item.get("type") == "file" else "-"
            self.table.setItem(row, 2, QTableWidgetItem(size_text))
            self.table.setRowHeight(row, 24)

    def _render_icons(self, items, base_path: str):
        """Legacy method - renders all items at once. Now replaced by chunked rendering."""
        self.icon_list.clear()
        sorted_items = self._sort_items(items)
        self._render_icons_chunk(sorted_items, base_path)

    def _render_icons_chunk(self, items, base_path: str):
        """Render a chunk of items to the icon/thumbnail view."""
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
            path_full = it.get("path") or (f"{base_path.rstrip('/')}/{name}" if base_path != "/" else f"/{name}")
            item.setData(Qt.ItemDataRole.UserRole, {"name": name, "type": type_, "path": path_full, "size": size_val})
            self.icon_list.addItem(item)

            # If thumbnails view and item is a file, request a thumbnail from server
            # Request thumbnails for all file types so server-generated fallback
            # icons (PDF, TXT, DOC, ZIP, etc.) are displayed.
            if self.view_mode == "thumbnails" and type_ == "file":
                self._load_thumbnail_async(item, path_full)

    def _update_filter_button_state(self):
        """Enable search button only if at least one filter criterion is entered."""
        has_name = bool(self.search_input.text().strip())
        has_size_min = bool(self.size_min.text().strip())
        has_size_max = bool(self.size_max.text().strip())
        has_type = self.type_combo.currentText() != "Any"

        # Enable button if any filter is set
        has_filters = has_name or has_size_min or has_size_max or has_type
        self.search_btn.setEnabled(has_filters)

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

    def _on_search(self):
        if not self.api_client:
            return
        q = self.search_input.text().strip()
        type_map = {"Any": None, "File": "file", "Folder": "dir"}
        type_val = type_map.get(self.type_combo.currentText(), None)
        def _to_int(val):
            try:
                return int(float(val)) if val != "" else None
            except Exception:
                return None
        size_min = _to_int(self.size_min.text())
        size_max = _to_int(self.size_max.text())
        try:
            items = self.api_client.search(
                path=self.current_path,
                q=q or None,
                type_=type_val,
                size_min=size_min * 1024 if size_min is not None else None,
                size_max=size_max * 1024 if size_max is not None else None,
            )
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Search failed", str(e))
            return
        self._last_search_items = items
        self._last_search_path = self.current_path
        # Render search results
        if self.view_mode == "list":
            self._render_table(items, self.current_path)
        else:
            self._render_icons(items, self.current_path)
        self.path_changed.emit(self.current_path + " (search)")
        self.selection_cleared.emit()

    def _clear_search(self):
        self.search_input.clear()
        self.size_min.clear()
        self.size_max.clear()
        self.type_combo.setCurrentIndex(0)  # Reset to "Any"
        if self._last_search_items is not None:
            self._last_search_items = None
            self.load_path(self.current_path)
        self._update_filter_button_state()

    def _open_context_menu(self, pos: QPoint):
        item = self._selected_item()
        menu = QMenu(self)
        if item:
            if item["type"] == "file":
                name_lower = item["name"].lower()
                is_audio = self._is_audio(name_lower)
                is_video = self._is_video(name_lower)
                if is_video:
                    menu.addAction("Play in VLC")
                if is_audio and self.on_play_mini:
                    menu.addAction("Play in Mini Player")
                # Always include Open for files
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
                elif act.text() == "Play in Mini Player" and item["type"] == "file" and self._is_audio(name_lower) and self.on_play_mini:
                    self.on_play_mini(item["path"])
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
                is_audio = self._is_audio(name_lower)
                is_video = self._is_video(name_lower)
                if is_video:
                    menu.addAction("Play in VLC")
                if is_audio and self.on_play_mini:
                    menu.addAction("Play in Mini Player")
                # Always include Open for files
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
                elif act.text() == "Play in Mini Player" and data["type"] == "file" and self._is_audio(name_lower) and self.on_play_mini:
                    self.on_play_mini(data["path"])
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

    def _open_mini_player_for_first_audio(self):
        """Open the first audio file in the current directory in mini player"""
        if not self.on_play_mini:
            return
        # Find first audio file
        if self.view_mode == "list":
            for row in range(self.table.rowCount()):
                item_widget = self.table.item(row, 0)
                if item_widget:
                    item_data = item_widget.data(Qt.ItemDataRole.UserRole)
                    if item_data and item_data.get("type") == "file":
                        name_lower = item_data.get("name", "").lower()
                        if self._is_audio(name_lower):
                            self.on_play_mini(item_data["path"])
                            return
        else:
            for i in range(self.icon_list.count()):
                item_widget = self.icon_list.item(i)
                if item_widget:
                    item_data = item_widget.data(Qt.ItemDataRole.UserRole)
                    if item_data and item_data.get("type") == "file":
                        name_lower = item_data.get("name", "").lower()
                        if self._is_audio(name_lower):
                            self.on_play_mini(item_data["path"])
                            return

    def _open_camera(self):
        if self.on_camera:
            self.on_camera()

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

    def _is_audio(self, name_lower: str) -> bool:
        return name_lower.endswith((
            ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".opus"
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

        # Check if item is currently visible in the view
        is_visible = False
        try:
            rect = self.icon_list.visualItemRect(list_item)
            viewport_rect = self.icon_list.viewport().rect()
            is_visible = viewport_rect.intersects(rect)
        except:
            pass

        # Priority queue: visible items go to front, others to back
        if is_visible:
            self._thumb_pending.insert(0, (key, url))  # Front of queue
        else:
            self._thumb_pending.append((key, url))  # Back of queue

        self._start_next_thumb()

    def _load_visible_thumbnails(self):
        """Load thumbnails for items currently visible (plus a small buffer) in the viewport."""
        if self.view_mode != "thumbnails" or not self.api_client:
            return

        viewport_rect = self.icon_list.viewport().rect()
        # Expand rect to prefetch thumbnails just below/above the viewport
        buffer = viewport_rect.height() // 2
        expanded_rect = viewport_rect.adjusted(0, -buffer, 0, buffer)

        for i in range(self.icon_list.count()):
            item = self.icon_list.item(i)
            if not item:
                continue

            # Check if item is visible or near-visible
            item_rect = self.icon_list.visualItemRect(item)
            if expanded_rect.intersects(item_rect):
                data = item.data(Qt.ItemDataRole.UserRole)
                if data and data.get("type") == "file":
                    path = data.get("path")
                    if path:
                        self._load_thumbnail_async(item, path)

    def _start_next_thumb(self):
        # Limit concurrent thumbnail fetches; tuned higher to leverage >10 Mbps LAN
        MAX_CONCURRENT = 32
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
