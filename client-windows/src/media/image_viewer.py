from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl, QByteArray, QSize
from PyQt6.QtGui import QAction, QPixmap, QWheelEvent, QIcon, QPainter, QPen, QColor, QPalette
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolBar,
    QWidget,
    QSizePolicy,
    QMessageBox,
)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from urllib.parse import urlparse, parse_qs, unquote


class ImageViewer(QDialog):
    """
    A lightweight in-memory image viewer that fetches image bytes over HTTP
    (with optional Authorization header) and displays without writing to disk.

    Controls:
    - Mouse wheel: Zoom in/out
    - Ctrl+0: Fit to window
    - Drag while holding left mouse to pan when zoomed
    - Toolbar buttons: Zoom In, Zoom Out, Fit
    """

    def __init__(self, url: str, auth_token: str | None = None, display_name: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._url = url
        self._token = auth_token
        # Title: prefer provided display_name, else derive from URL path query
        self.setWindowTitle(self._derive_title(display_name))
        # Enable maximize (and minimize) buttons on the title bar
        try:
            self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
            self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        except Exception:
            pass
        self.resize(1000, 700)

        self._net = QNetworkAccessManager(self)

        # UI
        self._toolbar = QToolBar(self)
        self._toolbar.setMovable(False)
        self._toolbar.setIconSize(QSize(20, 20))
        # Actions with icons
        self._act_zoom_in = QAction(self)
        self._act_zoom_out = QAction(self)
        self._act_fit = QAction(self)
        # Use custom-drawn icons (magnifier +/- and a frame for fit)
        self._act_zoom_in.setIcon(self._make_zoom_icon(plus=True))
        self._act_zoom_out.setIcon(self._make_zoom_icon(plus=False))
        self._act_fit.setIcon(self._make_fit_icon())
        self._act_zoom_in.setToolTip("Zoom In")
        self._act_zoom_out.setToolTip("Zoom Out")
        self._act_fit.setToolTip("Fit to window (Ctrl+0)")
        self._act_zoom_in.triggered.connect(lambda: self._apply_zoom(1.25))
        self._act_zoom_out.triggered.connect(lambda: self._apply_zoom(0.8))
        self._act_fit.triggered.connect(self._fit_to_window)
        self._toolbar.addAction(self._act_zoom_in)
        self._toolbar.addAction(self._act_zoom_out)
        self._toolbar.addAction(self._act_fit)

        self._scroll = QScrollArea(self)
        # Allow the image label to grow beyond the viewport so scrollbars appear and panning works
        self._scroll.setWidgetResizable(False)
        # Center image when it's smaller than the viewport
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label = _ImageLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._scroll.setWidget(self._label)

        self._status = QLabel("Loading…", self)
        self._status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        v = QVBoxLayout(self)
        v.addWidget(self._toolbar)
        v.addWidget(self._scroll, 1)
        v.addWidget(self._status)

        self._pixmap: QPixmap | None = None
        self._scale: float = 1.0
        self._fit_active: bool = True  # when True, auto-fit on resize (e.g., after maximize)

        self._fetch()

    def _pen_color(self) -> QColor:
        try:
            return self.palette().color(QPalette.ColorRole.WindowText)
        except Exception:
            return QColor(60, 60, 60)

    def _make_zoom_icon(self, plus: bool) -> QIcon:
        size = 24
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self._pen_color(), 2)
        p.setPen(pen)
        # Lens
        cx, cy, r = 10, 10, 7
        p.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)
        # Handle
        p.drawLine(cx + 4, cy + 4, cx + 10, cy + 10)
        # Plus / minus
        p.drawLine(cx - 3, cy, cx + 3, cy)
        if plus:
            p.drawLine(cx, cy - 3, cx, cy + 3)
        p.end()
        return QIcon(pm)

    def _make_fit_icon(self) -> QIcon:
        size = 24
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self._pen_color(), 2)
        p.setPen(pen)
        # Outer frame
        rect_x, rect_y, rect_w, rect_h = 5, 6, 14, 12
        p.drawRect(rect_x, rect_y, rect_w, rect_h)
        # Corner marks (short L-shapes inside frame)
        m = 3
        # Top-left
        p.drawLine(rect_x + 1, rect_y + m, rect_x + 1, rect_y + 1)
        p.drawLine(rect_x + 1, rect_y + 1, rect_x + m, rect_y + 1)
        # Top-right
        p.drawLine(rect_x + rect_w - 1, rect_y + m, rect_x + rect_w - 1, rect_y + 1)
        p.drawLine(rect_x + rect_w - m, rect_y + 1, rect_x + rect_w - 1, rect_y + 1)
        # Bottom-left
        p.drawLine(rect_x + 1, rect_y + rect_h - m, rect_x + 1, rect_y + rect_h - 1)
        p.drawLine(rect_x + 1, rect_y + rect_h - 1, rect_x + m, rect_y + rect_h - 1)
        # Bottom-right
        p.drawLine(rect_x + rect_w - 1, rect_y + rect_h - m, rect_x + rect_w - 1, rect_y + rect_h - 1)
        p.drawLine(rect_x + rect_w - m, rect_y + rect_h - 1, rect_x + rect_w - 1, rect_y + rect_h - 1)
        p.end()
        return QIcon(pm)

    def _derive_title(self, display_name: str | None) -> str:
        if display_name:
            return display_name
        # Try to extract `path` query param and take basename
        try:
            parsed = urlparse(self._url)
            q = parse_qs(parsed.query)
            p = q.get("path", [""])[0]
            if p:
                p = unquote(p)
                base = p.rstrip("/").split("/")[-1]
                if base:
                    return base
        except Exception:
            pass
        return "Image Viewer"

    def _fetch(self):
        req = QNetworkRequest(QUrl(self._url))
        # Follow redirects (some servers may redirect /stream)
        try:
            req.setAttribute(QNetworkRequest.Attribute.FollowRedirectsAttribute, True)
        except Exception:
            pass
        # Prefer images but accept anything
        req.setRawHeader(b"Accept", b"image/*, */*;q=0.8")
        if self._token:
            req.setRawHeader(b"Authorization", f"Bearer {self._token}".encode("utf-8"))
        reply = self._net.get(req)

        def _finished():
            nonlocal reply
            try:
                # Gather HTTP status and content-type for diagnostics
                try:
                    status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                except Exception:
                    status = None
                try:
                    reason = reply.attribute(QNetworkRequest.Attribute.HttpReasonPhraseAttribute)
                except Exception:
                    reason = None
                try:
                    ctype = reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader)
                except Exception:
                    ctype = None

                # Try to decode regardless of Qt network 'error' if we received data
                data: QByteArray = reply.readAll()
                pm = QPixmap()
                loaded = pm.loadFromData(bytes(data)) if data and len(data) > 0 else False
                if loaded:
                    self._pixmap = pm
                    self._scale = 1.0
                    self._update_view(reset=True)
                    # Show only image details (no debugging info)
                    size_bytes = len(data) if data is not None else 0
                    size_text = f" | {self._fmt_bytes(size_bytes)}" if size_bytes > 0 else ""
                    self._status.setText(self._nice_info() + size_text)
                    return

                # If not loaded, report concise error (no debug preview)
                size = len(data) if data is not None else 0
                if reply.error():
                    msg = f"Error: {reply.errorString()}"
                elif size == 0:
                    msg = "No image data received"
                else:
                    msg = "Unsupported image format"
                self._status.setText(msg)
                return
            finally:
                reply.deleteLater()

        reply.finished.connect(_finished)

    def _nice_info(self) -> str:
        if not self._pixmap:
            return ""
        w = self._pixmap.width()
        h = self._pixmap.height()
        zw = int(w * self._scale)
        zh = int(h * self._scale)
        return f"{w}×{h}px  |  Zoom {int(self._scale*100)}%  |  Display {zw}×{zh}px"

    def _fmt_bytes(self, n: int) -> str:
        try:
            units = ["B", "KB", "MB", "GB", "TB"]
            size = float(n)
            i = 0
            while size >= 1024 and i < len(units) - 1:
                size /= 1024.0
                i += 1
            return f"{size:.1f} {units[i]}" if i > 0 else f"{int(size)} {units[i]}"
        except Exception:
            return f"{n} B"

    def _update_view(self, reset: bool = False):
        if not self._pixmap:
            return
        if reset:
            self._label.setPixmap(self._pixmap)
            self._label.adjustSize()
            self._fit_to_window()  # start fitted by default
            return
        scaled = self._pixmap.scaled(self._scaled_size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._label.setPixmap(scaled)
        self._label.adjustSize()
        self._status.setText(self._nice_info())

    def _scaled_size(self) -> QSize:
        if not self._pixmap:
            return QSize(0, 0)
        return QSize(int(self._pixmap.width() * self._scale), int(self._pixmap.height() * self._scale))

    def _apply_zoom(self, factor: float):
        if not self._pixmap:
            return
        new_scale = max(0.05, min(10.0, self._scale * factor))
        if abs(new_scale - self._scale) < 1e-3:
            return
        self._scale = new_scale
        self._fit_active = False  # manual zoom disables auto-fit
        self._update_view()

    def _fit_to_window(self):
        if not self._pixmap:
            return
        avail_w = max(1, self._scroll.viewport().width() - 2)
        avail_h = max(1, self._scroll.viewport().height() - 2)
        if self._pixmap.width() == 0 or self._pixmap.height() == 0:
            return
        sx = avail_w / self._pixmap.width()
        sy = avail_h / self._pixmap.height()
        self._scale = min(sx, sy, 1.0)  # don't upscale on fit
        self._fit_active = True
        self._update_view()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # If user has chosen Fit mode (or initial state), keep fitting on resize/maximize
        if getattr(self, "_fit_active", False):
            # Avoid jitter: only refit if we already have a pixmap
            if self._pixmap is not None:
                self._fit_to_window()

    # Optional: keyboard shortcuts
    def keyPressEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier and e.key() == Qt.Key.Key_0:
            self._fit_to_window()
            e.accept()
            return
        super().keyPressEvent(e)


class _ImageLabel(QLabel):
    """Label with wheel-zoom and left-drag panning when larger than viewport."""

    def __init__(self):
        super().__init__()
        self._dragging = False
        self._last_pos = None

    def wheelEvent(self, event: QWheelEvent):
        # Let dialog handle zoom via actions; Nothing here so parent can intercept if needed
        # Alternatively, we could emit a signal and let the dialog adjust scale.
        return super().wheelEvent(event)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_pos = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._dragging:
            # Find ancestor scroll area
            scroll = None
            p = self.parent()
            while p is not None:
                if isinstance(p, QScrollArea):
                    scroll = p
                    break
                p = p.parent()
            if scroll is not None:
                delta = e.position() - self._last_pos
                self._last_pos = e.position()
                h = scroll.horizontalScrollBar()
                v = scroll.verticalScrollBar()
                h.setValue(h.value() - int(delta.x()))
                v.setValue(v.value() - int(delta.y()))
                e.accept()
                return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            e.accept()
            return
        super().mouseReleaseEvent(e)
