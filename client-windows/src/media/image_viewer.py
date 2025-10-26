from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl, QByteArray, QSize, QRect, QPointF, pyqtSignal, QBuffer, QIODevice, QTimer
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
    QSpinBox,
    QInputDialog,
    QMenu,
    QToolButton,
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

    # Signal emitted when a file is saved, with the server path
    file_saved = pyqtSignal(str)

    def __init__(self, url: str, auth_token: str | None = None, display_name: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._url = url
        self._token = auth_token
        # Parse base URL and server path from stream URL
        self._base_url, self._server_path = self._parse_stream_url(url)
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
        # Crop controls
        self._toolbar.addSeparator()
        self._act_crop_mode = QAction(self)
        self._act_crop_mode.setCheckable(True)
        self._act_crop_mode.setIcon(self._make_crop_icon())
        self._act_crop_mode.setToolTip("Crop mode: drag to select")
        # Disabled until an image is loaded to avoid initializing before pixmap size is known
        self._act_crop_mode.setEnabled(False)
        self._toolbar.addAction(self._act_crop_mode)

        self._act_crop_apply = QAction(self)
        try:
            self._act_crop_apply.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_DialogApplyButton))
        except Exception:
            self._act_crop_apply.setText("Apply")
        self._act_crop_apply.setToolTip("Apply crop")
        self._act_crop_apply.setEnabled(False)
        self._toolbar.addAction(self._act_crop_apply)

        # Crop output scale controls
        self._scale_label = QLabel("Scale", self)
        self._scale_label.setToolTip("Output size of the cropped image as a percentage")
        self._scale_spin = QSpinBox(self)
        self._scale_spin.setRange(10, 400)
        self._scale_spin.setSingleStep(10)
        self._scale_spin.setValue(100)
        self._scale_spin.setSuffix(" %")
        self._scale_spin.setEnabled(False)
        self._scale_label.setEnabled(False)
        self._toolbar.addWidget(self._scale_label)
        self._toolbar.addWidget(self._scale_spin)

        self._scroll = QScrollArea(self)
        # Allow the image label to grow beyond the viewport so scrollbars appear and panning works
        self._scroll.setWidgetResizable(False)
        # Center image when it's smaller than the viewport
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label = _ImageLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._scroll.setWidget(self._label)
        # Wire crop mode interactions
        self._act_crop_mode.toggled.connect(self._on_crop_toggled)
        self._act_crop_apply.triggered.connect(self._apply_crop)
        self._label.selection_changed.connect(self._on_selection_changed)

        self._status = QLabel("Loading…", self)
        self._status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        v = QVBoxLayout(self)
        v.addWidget(self._toolbar)
        v.addWidget(self._scroll, 1)
        v.addWidget(self._status)

        self._pixmap: QPixmap | None = None
        self._scale: float = 1.0
        self._fit_active: bool = True  # when True, auto-fit on resize (e.g., after maximize)

        # Saving button with dropdown menu (positioned at the right end of toolbar)
        self._toolbar.addSeparator()
        # Add spacer to push save button to the right
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._toolbar.addWidget(spacer)

        # Create modern 3D save button with dropdown
        self._save_button = QToolButton(self)
        self._save_button.setText("Save")
        self._save_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._save_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._save_button.setEnabled(False)

        # Apply modern 3D styling
        self._save_button.setStyleSheet("""
            QToolButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                          stop:0 #f0f0f0, stop:0.5 #e0e0e0, stop:1 #d0d0d0);
                border: 1px solid #a0a0a0;
                border-radius: 4px;
                padding: 4px 12px;
                font-weight: bold;
                color: #2c3e50;
                min-width: 80px;
                max-height: 28px;
                text-align: center;
            }
            QToolButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                          stop:0 #e8f4f8, stop:0.5 #d0e8f0, stop:1 #b8dce8);
                border: 1px solid #0078d4;
            }
            QToolButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                          stop:0 #c0c0c0, stop:0.5 #d0d0d0, stop:1 #e0e0e0);
                border: 1px solid #606060;
                padding-top: 5px;
                padding-left: 13px;
            }
            QToolButton:disabled {
                background: #f5f5f5;
                border: 1px solid #cccccc;
                color: #a0a0a0;
            }
            QToolButton::menu-button {
                border-left: 1px solid #a0a0a0;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
                width: 16px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                          stop:0 #f0f0f0, stop:0.5 #e0e0e0, stop:1 #d0d0d0);
            }
            QToolButton::menu-button:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                          stop:0 #e8f4f8, stop:0.5 #d0e8f0, stop:1 #b8dce8);
            }
        """)

        # Create actions for save menu
        self._act_save = QAction("Save", self)
        self._act_save.setToolTip("Save (overwrite current file)")
        self._act_save.triggered.connect(self._save)

        self._act_save_copy = QAction("Save as Copy", self)
        self._act_save_copy.setToolTip("Save as Copy (create new file)")
        self._act_save_copy.triggered.connect(self._save_as_copy)

        # Create dropdown menu
        save_menu = QMenu(self)
        save_menu.addAction(self._act_save)
        save_menu.addAction(self._act_save_copy)

        # Set default action (clicking the button itself triggers Save)
        self._save_button.setDefaultAction(self._act_save)
        self._save_button.setMenu(save_menu)

        self._toolbar.addWidget(self._save_button)

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

    def _make_crop_icon(self) -> QIcon:
        size = 24
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self._pen_color(), 2)
        p.setPen(pen)
        # Draw crop-like right-angle corners
        m = 4
        # Top-left corner
        p.drawLine(6, 6, 6, 6 + m)
        p.drawLine(6, 6, 6 + m, 6)
        # Top-right corner
        p.drawLine(size - 6, 6, size - 6, 6 + m)
        p.drawLine(size - 6 - m, 6, size - 6, 6)
        # Bottom-left corner
        p.drawLine(6, size - 6, 6, size - 6 - m)
        p.drawLine(6, size - 6, 6 + m, size - 6)
        # Bottom-right corner
        p.drawLine(size - 6, size - 6, size - 6, size - 6 - m)
        p.drawLine(size - 6 - m, size - 6, size - 6, size - 6)
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
                    # Enable saving if we know where this image came from
                    can_save = bool(self._server_path)
                    self._save_button.setEnabled(can_save)
                    # Enable crop mode now that an image is present
                    self._act_crop_mode.setEnabled(True)
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

    def _on_crop_toggled(self, enabled: bool):
        self._label.set_crop_mode(enabled)
        if enabled:
            # Initialize the crop frame to fit the currently displayed image
            # Use a deferred call to ensure label has been sized
            QTimer.singleShot(0, self._label.init_crop_to_image)
        self._scale_spin.setEnabled(enabled)
        self._scale_label.setEnabled(enabled)
        self._act_crop_apply.setEnabled(bool(enabled))
        if not enabled:
            # Reset status line to image info when leaving crop mode
            self._status.setText(self._nice_info())

    def _on_selection_changed(self, rect: object):
        # rect is a QRect in label/display coordinates, or None
        has_sel = isinstance(rect, QRect) and rect.width() > 1 and rect.height() > 1
        self._act_crop_apply.setEnabled(bool(has_sel))
        if has_sel and self._pixmap is not None:
            # Map to original image pixels by dividing by scale
            ow = max(1, int(rect.width() / max(1e-6, self._scale)))
            oh = max(1, int(rect.height() / max(1e-6, self._scale)))
            factor = self._scale_spin.value() / 100.0
            out_w = max(1, int(ow * factor))
            out_h = max(1, int(oh * factor))
            self._status.setText(f"Crop: {ow}×{oh}px @ {int(factor*100)}% → {out_w}×{out_h}px")

    def _apply_crop(self):
        if self._pixmap is None:
            return
        rect = self._label.selection_rect()
        if rect is None or rect.width() < 2 or rect.height() < 2:
            return
        # Convert to original coordinates
        sx = 1.0 / max(1e-6, self._scale)
        x = int(rect.x() * sx)
        y = int(rect.y() * sx)
        w = int(rect.width() * sx)
        h = int(rect.height() * sx)
        # Clamp to image bounds
        x = max(0, min(x, self._pixmap.width() - 1))
        y = max(0, min(y, self._pixmap.height() - 1))
        w = max(1, min(w, self._pixmap.width() - x))
        h = max(1, min(h, self._pixmap.height() - y))
        cropped = self._pixmap.copy(x, y, w, h)
        # Apply scaling factor
        factor = self._scale_spin.value() / 100.0
        if abs(factor - 1.0) > 1e-3:
            new_w = max(1, int(cropped.width() * factor))
            new_h = max(1, int(cropped.height() * factor))
            cropped = cropped.scaled(new_w, new_h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        # Replace current image and exit crop mode
        self._pixmap = cropped
        self._label.clear_selection()
        self._act_crop_mode.setChecked(False)
        self._fit_to_window()

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

    # --- Save/Upload helpers ---
    def _parse_stream_url(self, url: str) -> tuple[str | None, str | None]:
        try:
            parsed = urlparse(url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            q = parse_qs(parsed.query)
            path = q.get("path", [None])[0]
            if path:
                path = unquote(path)
            return base, path
        except Exception:
            return None, None

    def _preferred_format_for_ext(self, ext: str) -> tuple[str, str]:
        # Returns (QtFormat, mime)
        e = ext.lower().lstrip('.')
        if e in ("jpg", "jpeg"):
            return "JPEG", "image/jpeg"
        if e == "png":
            return "PNG", "image/png"
        if e == "webp":
            return "WEBP", "image/webp"
        if e == "bmp":
            return "BMP", "image/bmp"
        # Fallback
        return "PNG", "image/png"

    def _encode_current(self) -> tuple[QByteArray | None, str]:
        if not self._pixmap:
            return None, "application/octet-stream"
        # Try to preserve original extension when practical
        ext = None
        if self._server_path:
            ext = self._server_path.rsplit('.', 1)[-1] if '.' in self._server_path else None
        fmt, mime = self._preferred_format_for_ext(ext or "png")
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        ok = self._pixmap.save(buf, fmt)
        data = buf.data() if ok else None
        if not ok or data is None or data.isEmpty():
            # Fallback to PNG
            buf2 = QBuffer()
            buf2.open(QIODevice.OpenModeFlag.WriteOnly)
            ok2 = self._pixmap.save(buf2, "PNG")
            if ok2:
                return buf2.data(), "image/png"
            return None, "application/octet-stream"
        return data, mime

    def _upload_bytes(self, dest_path: str, data: QByteArray, mime: str, on_done: callable | None = None):
        if not self._base_url or not dest_path:
            QMessageBox.warning(self, "Cannot save", "Missing destination path.")
            return
        if not self._token:
            QMessageBox.warning(self, "Cannot save", "Missing auth token.")
            return
        # PUT /file?path=...
        try:
            from urllib.parse import quote
            put_url = f"{self._base_url}/file?path={quote(dest_path, safe='')}"
        except Exception:
            QMessageBox.critical(self, "Error", "Invalid server URL")
            return
        req = QNetworkRequest(QUrl(put_url))
        try:
            req.setAttribute(QNetworkRequest.Attribute.FollowRedirectsAttribute, True)
        except Exception:
            pass
        req.setRawHeader(b"Authorization", f"Bearer {self._token}".encode("utf-8"))
        if mime:
            try:
                req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, mime)
            except Exception:
                req.setRawHeader(b"Content-Type", mime.encode("utf-8"))
        reply = self._net.put(req, data)

        def _finished():
            nonlocal reply
            try:
                # Prefer HTTP status for success detection; some backends set a benign Qt error string
                try:
                    status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                except Exception:
                    status = None
                status_i = int(status) if status is not None else 0
                if 200 <= status_i < 300 or (status is None and not reply.error()):
                    if on_done:
                        try:
                            on_done()
                        except Exception:
                            pass
                    # Emit signal to notify that file was saved
                    self.file_saved.emit(dest_path)
                    QMessageBox.information(self, "Saved", "Image saved successfully.")
                    return
                # Fall back to Qt error string or HTTP status
                err_text = reply.errorString() or (f"HTTP {status_i}" if status_i else "Unknown error")
                QMessageBox.critical(self, "Save failed", err_text)
                if on_done:
                    try:
                        on_done()
                    except Exception:
                        pass
            finally:
                reply.deleteLater()
        reply.finished.connect(_finished)

    def _save(self):
        if not self._server_path:
            QMessageBox.warning(self, "Cannot save", "Unknown original path.")
            return
        data, mime = self._encode_current()
        if not data:
            QMessageBox.critical(self, "Error", "Failed to encode image.")
            return
        self._status.setText("Saving…")
        self._upload_bytes(self._server_path, data, mime, on_done=lambda: self._status.setText(self._nice_info()))

    def _save_as_copy(self):
        if not self._server_path:
            QMessageBox.warning(self, "Cannot save", "Unknown folder to save in.")
            return
        # Suggest a new name
        folder = self._server_path.rsplit('/', 1)[0] if '/' in self._server_path else ""
        base = self._server_path.rsplit('/', 1)[-1]
        name, ext = (base.rsplit('.', 1) + [""])[:2] if '.' in base else (base, "")
        suggested = f"{name} - Copy.{ext}" if ext else f"{name} - Copy"
        new_name, ok = QInputDialog.getText(self, "Save as Copy", "File name:", text=suggested)
        if not ok:
            return
        new_name = (new_name or "").strip()
        if not new_name:
            return
        # Ensure extension if missing
        if '.' not in new_name and ext:
            new_name = f"{new_name}.{ext}"
        dest_path = f"{folder}/{new_name}" if folder else f"/{new_name}"
        data, mime = self._encode_current()
        if not data:
            QMessageBox.critical(self, "Error", "Failed to encode image.")
            return
        self._status.setText("Saving copy…")
        self._upload_bytes(dest_path, data, mime, on_done=lambda: self._status.setText(self._nice_info()))


class _ImageLabel(QLabel):
    """Label that displays an image with crop selection overlay."""

    selection_changed = pyqtSignal(object)  # emits QRect or None

    def __init__(self):
        super().__init__()
        # Crop selection state
        self._crop_mode = False
        self._sel_rect: QRect | None = None  # The crop rectangle in label coordinates
        # Resize state
        self._resizing: str | None = None  # Edge/corner being resized: "left", "right", "top", "bottom", "tl", "tr", "bl", "br"
        self._resize_start_pos: QPointF | None = None
        self._resize_start_rect: QRect | None = None
        # Enable mouse tracking to receive move events without button press
        self.setMouseTracking(True)

    def wheelEvent(self, event: QWheelEvent):
        # Let dialog handle zoom via actions
        return super().wheelEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._crop_mode and self._sel_rect:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            # Dim outside the crop area
            overlay = QColor(0, 0, 0, 100)
            # Top
            if self._sel_rect.top() > 0:
                p.fillRect(0, 0, self.width(), self._sel_rect.top(), overlay)
            # Bottom
            if self._sel_rect.bottom() < self.height() - 1:
                p.fillRect(0, self._sel_rect.bottom() + 1, self.width(), self.height() - self._sel_rect.bottom() - 1, overlay)
            # Left
            if self._sel_rect.left() > 0:
                p.fillRect(0, self._sel_rect.top(), self._sel_rect.left(), self._sel_rect.height(), overlay)
            # Right
            if self._sel_rect.right() < self.width() - 1:
                p.fillRect(self._sel_rect.right() + 1, self._sel_rect.top(), self.width() - self._sel_rect.right() - 1, self._sel_rect.height(), overlay)

            # Draw border
            pen = QPen(QColor(0, 120, 215), 3, Qt.PenStyle.SolidLine)
            p.setPen(pen)
            p.drawRect(self._sel_rect)

            # Draw resize handles
            handle_size = 10
            hw = handle_size // 2

            def draw_handle(x: int, y: int):
                rect = QRect(x - hw, y - hw, handle_size, handle_size)
                p.fillRect(rect, QColor(255, 255, 255))
                p.setPen(QPen(QColor(0, 120, 215), 2))
                p.drawRect(rect)

            # Corner handles
            draw_handle(self._sel_rect.left(), self._sel_rect.top())
            draw_handle(self._sel_rect.right(), self._sel_rect.top())
            draw_handle(self._sel_rect.left(), self._sel_rect.bottom())
            draw_handle(self._sel_rect.right(), self._sel_rect.bottom())

            # Edge handles
            draw_handle((self._sel_rect.left() + self._sel_rect.right()) // 2, self._sel_rect.top())
            draw_handle((self._sel_rect.left() + self._sel_rect.right()) // 2, self._sel_rect.bottom())
            draw_handle(self._sel_rect.left(), (self._sel_rect.top() + self._sel_rect.bottom()) // 2)
            draw_handle(self._sel_rect.right(), (self._sel_rect.top() + self._sel_rect.bottom()) // 2)

            p.end()

    def set_crop_mode(self, enabled: bool):
        self._crop_mode = bool(enabled)
        if not enabled:
            self._sel_rect = None
        self.update()

    def crop_mode_active(self) -> bool:
        return bool(self._crop_mode)

    def init_crop_to_image(self):
        """Initialize crop selection to fit the entire displayed image."""
        if not self._crop_mode:
            return
        pm = self.pixmap()
        if pm and not pm.isNull():
            # Use pixmap size which is the actual displayed image size
            w = pm.width()
            h = pm.height()
            if w > 0 and h > 0:
                self._sel_rect = QRect(0, 0, w, h)
                self.selection_changed.emit(self._sel_rect)
                self.update()
            else:
                # Pixmap has invalid size, try again after a short delay
                QTimer.singleShot(50, self.init_crop_to_image)

    def clear_selection(self):
        self._sel_rect = None
        self.selection_changed.emit(None)
        self.update()

    def selection_rect(self) -> QRect | None:
        return self._sel_rect

    def _hit_test(self, pos: QPointF) -> str | None:
        """Determine which part of the selection rectangle is at the given position."""
        if not self._sel_rect:
            return None

        margin = 10  # Detection margin for edges/corners
        x = pos.x()
        y = pos.y()

        # Check edges
        near_left = abs(x - self._sel_rect.left()) <= margin
        near_right = abs(x - self._sel_rect.right()) <= margin
        near_top = abs(y - self._sel_rect.top()) <= margin
        near_bottom = abs(y - self._sel_rect.bottom()) <= margin

        in_h_range = self._sel_rect.top() - margin <= y <= self._sel_rect.bottom() + margin
        in_v_range = self._sel_rect.left() - margin <= x <= self._sel_rect.right() + margin

        # Check corners first
        if near_left and near_top:
            return "tl"
        if near_right and near_top:
            return "tr"
        if near_left and near_bottom:
            return "bl"
        if near_right and near_bottom:
            return "br"

        # Check edges
        if near_left and in_h_range:
            return "left"
        if near_right and in_h_range:
            return "right"
        if near_top and in_v_range:
            return "top"
        if near_bottom and in_v_range:
            return "bottom"

        return None

    def _update_cursor(self, hit: str | None):
        """Update cursor based on hit test result."""
        if hit in ("left", "right"):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif hit in ("top", "bottom"):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif hit in ("tl", "br"):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif hit in ("tr", "bl"):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        if self._crop_mode and self._sel_rect and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            hit = self._hit_test(pos)
            if hit:
                self._resizing = hit
                self._resize_start_pos = pos
                self._resize_start_rect = QRect(self._sel_rect)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position()

        if self._resizing and self._resize_start_pos and self._resize_start_rect:
            # Calculate delta
            dx = int(pos.x() - self._resize_start_pos.x())
            dy = int(pos.y() - self._resize_start_pos.y())

            # Start with original rect
            rect = QRect(self._resize_start_rect)

            # Apply resize based on which edge/corner is being dragged
            # Corners resize both horizontally and vertically
            if self._resizing == "tl":
                new_left = max(0, min(rect.left() + dx, rect.right() - 10))
                new_top = max(0, min(rect.top() + dy, rect.bottom() - 10))
                rect.setLeft(new_left)
                rect.setTop(new_top)
            elif self._resizing == "tr":
                new_right = min(self.width() - 1, max(rect.right() + dx, rect.left() + 10))
                new_top = max(0, min(rect.top() + dy, rect.bottom() - 10))
                rect.setRight(new_right)
                rect.setTop(new_top)
            elif self._resizing == "bl":
                new_left = max(0, min(rect.left() + dx, rect.right() - 10))
                new_bottom = min(self.height() - 1, max(rect.bottom() + dy, rect.top() + 10))
                rect.setLeft(new_left)
                rect.setBottom(new_bottom)
            elif self._resizing == "br":
                new_right = min(self.width() - 1, max(rect.right() + dx, rect.left() + 10))
                new_bottom = min(self.height() - 1, max(rect.bottom() + dy, rect.top() + 10))
                rect.setRight(new_right)
                rect.setBottom(new_bottom)
            # Edges resize only in one direction
            elif self._resizing == "left":
                new_left = max(0, min(rect.left() + dx, rect.right() - 10))
                rect.setLeft(new_left)
            elif self._resizing == "right":
                new_right = min(self.width() - 1, max(rect.right() + dx, rect.left() + 10))
                rect.setRight(new_right)
            elif self._resizing == "top":
                new_top = max(0, min(rect.top() + dy, rect.bottom() - 10))
                rect.setTop(new_top)
            elif self._resizing == "bottom":
                new_bottom = min(self.height() - 1, max(rect.bottom() + dy, rect.top() + 10))
                rect.setBottom(new_bottom)

            self._sel_rect = rect
            self.selection_changed.emit(self._sel_rect)
            self.update()
            event.accept()
        elif self._crop_mode and self._sel_rect:
            # Update cursor based on hover
            hit = self._hit_test(pos)
            self._update_cursor(hit)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._resizing:
            self._resizing = None
            self._resize_start_pos = None
            self._resize_start_rect = None
            event.accept()
        super().mouseReleaseEvent(event)

