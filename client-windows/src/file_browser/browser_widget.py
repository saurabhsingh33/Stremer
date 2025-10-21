from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QAbstractItemView, QMenu
from PyQt6.QtCore import Qt, QPoint


class BrowserWidget(QWidget):
    def __init__(self, api_client, on_play, on_delete, on_copy):
        super().__init__()
        self.api_client = api_client
        self.on_play = on_play
        self.on_delete = on_delete
        self.on_copy = on_copy
        self.current_path = "/"

        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Size"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._open_context_menu)
        self.table.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self.table)

    def load_path(self, path: str = "/"):
        self.current_path = path
        if not self.api_client:
            # No API client yet; clear view
            self.table.setRowCount(0)
            return
        items = self.api_client.list_files(path)
        self.table.setRowCount(0)
        for item in items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(item.get("name", "")))
            self.table.setItem(row, 1, QTableWidgetItem(item.get("type", "file")))
            self.table.setItem(row, 2, QTableWidgetItem(str(item.get("size", ""))))
            self.table.setRowHeight(row, 24)
        self.table.resizeColumnsToContents()

    def _selected_item(self):
        idx = self.table.currentRow()
        if idx < 0:
            return None
        name = self.table.item(idx, 0).text()
        type_ = self.table.item(idx, 1).text()
        path = f"{self.current_path.rstrip('/')}/{name}" if self.current_path != "/" else f"/{name}"
        return {"name": name, "type": type_, "path": path}

    def _open_context_menu(self, pos: QPoint):
        item = self._selected_item()
        if not item:
            return
        menu = QMenu(self)
        if item["type"] == "file":
            play_act = menu.addAction("Play in VLC")
        copy_act = menu.addAction("Copy...")
        del_act = menu.addAction("Delete")
        act = menu.exec(self.table.mapToGlobal(pos))
        if act:
            if item["type"] == "file" and act.text() == "Play in VLC":
                self.on_play(item["path"])
            elif act.text() == "Copy...":
                self.on_copy(item["path"])
            elif act.text() == "Delete":
                self.on_delete(item["path"])

    def _on_double_click(self):
        item = self._selected_item()
        if not item:
            return
        if item["type"] == "dir":
            self.load_path(item["path"])  # navigate into directory

    def set_api_client(self, api_client):
        self.api_client = api_client
