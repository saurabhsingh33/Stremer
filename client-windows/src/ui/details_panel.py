from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFormLayout, QSizePolicy
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
import json


def fmt_size(n):
    try:
        if n is None:
            return "-"
        n = int(n)
        units = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        f = float(n)
        while f >= 1024 and i < len(units) - 1:
            f /= 1024.0
            i += 1
        return f"{int(f) if i==0 else f'{f:.1f}'} {units[i]}"
    except Exception:
        return str(n)


def fmt_duration(ms):
    try:
        if ms is None:
            return "-"
        ms = int(ms)
        s = ms // 1000
        h = s // 3600
        m = (s % 3600) // 60
        s = s % 60
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
    except Exception:
        return "-"


class DetailsPanel(QWidget):
    def __init__(self, api_client, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self._net = QNetworkAccessManager(self)
        self.title = QLabel("No selection")
        self.title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.title.setWordWrap(True)
        self.title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_type = QLabel("-")
        self.lbl_size = QLabel("-")
        self.lbl_dim = QLabel("-")
        self.lbl_len = QLabel("-")
        self.lbl_owner = QLabel("-")
        self.lbl_mime = QLabel("-")
        self.lbl_items = QLabel("-")

        # Wrap long values instead of widening the panel
        for lbl in (self.lbl_type, self.lbl_size, self.lbl_dim, self.lbl_len, self.lbl_owner, self.lbl_mime, self.lbl_items):
            lbl.setWordWrap(True)
            lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        self.form.addRow("Type:", self.lbl_type)
        self.form.addRow("Size:", self.lbl_size)
        self.form.addRow("Dimensions:", self.lbl_dim)
        self.form.addRow("Length:", self.lbl_len)
        self.form.addRow("Owner:", self.lbl_owner)
        self.form.addRow("MIME:", self.lbl_mime)
        self.form.addRow("Items:", self.lbl_items)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addLayout(self.form)
        layout.addStretch(1)

    def set_api_client(self, api_client):
        self.api_client = api_client

    def clear(self):
        self.title.setText("No selection")
        self.lbl_type.setText("-")
        self.lbl_size.setText("-")
        self.lbl_dim.setText("-")
        self.lbl_len.setText("-")
        self.lbl_owner.setText("-")
        self.lbl_mime.setText("-")
        self.lbl_items.setText("-")

    def show_item(self, item: dict):
        # Basic fields
        self.title.setText(item.get("path", item.get("name", "")))
        t = item.get("type", "")
        self.lbl_type.setText(t)
        # Pre-populate size if available from list
        initial_size = item.get("size")
        if initial_size is not None:
            self.lbl_size.setText(fmt_size(initial_size))
        # Fetch metadata
        if not self.api_client:
            return
        url = self.api_client.meta_url(item.get("path", "/"))
        req = QNetworkRequest(QUrl(url))
        # Request JSON and use auth header
        req.setRawHeader(b"Accept", b"application/json")
        if getattr(self.api_client, 'token', None):
            req.setRawHeader(b"Authorization", f"Bearer {self.api_client.token}".encode("utf-8"))
        reply = self._net.get(req)

        def _done():
            data = reply.readAll()
            reply.deleteLater()
            # If network error, keep pre-populated fields
            if reply.error():
                return
            try:
                meta = json.loads(bytes(data)) if data else {}
            except Exception:
                meta = {}
            # Populate fields
            size = meta.get("size")
            w = meta.get("width")
            h = meta.get("height")
            dur = meta.get("durationMs")
            mime = meta.get("mime")
            item_count = meta.get("itemCount")

            self.lbl_size.setText(fmt_size(size))
            self.lbl_dim.setText(f"{w} x {h}" if w and h else "-")
            self.lbl_len.setText(fmt_duration(dur))
            self.lbl_mime.setText(mime or "-")
            self.lbl_items.setText(str(item_count) if item_count is not None else "-")
            # Owner not available from SAF; placeholder "-"
            self.lbl_owner.setText("-")

        reply.finished.connect(_done)
