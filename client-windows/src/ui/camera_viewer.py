from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton
from PyQt6.QtGui import QPixmap, QTransform
from ui.camera_stream_thread import CameraStreamThread

class CameraViewer(QDialog):
    def __init__(self, api_client, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.setWindowTitle("Camera Stream")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        self.setMinimumSize(640, 480)
        self.resize(960, 720)
        layout = QVBoxLayout(self)
        self.label = QLabel("Connecting to camera…")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)

        controls = QHBoxLayout()
        self.rotate_left_btn = QPushButton("Rotate Left")
        self.rotate_right_btn = QPushButton("Rotate Right")
        controls.addWidget(self.rotate_left_btn)
        controls.addWidget(self.rotate_right_btn)
        layout.addLayout(controls)

        self._rotation = 0
        self._last_pixmap: QPixmap | None = None

        self.rotate_left_btn.clicked.connect(self._rotate_left)
        self.rotate_right_btn.clicked.connect(self._rotate_right)

        # Start streaming thread (MJPEG)
        headers = {}
        if getattr(self.api_client, 'token', None):
            headers['Authorization'] = f"Bearer {self.api_client.token}"
        self._t = CameraStreamThread(self.api_client.base_url, headers=headers, parent=self)
        self._t.frame.connect(self._on_frame)
        self._t.error.connect(self._on_error)
        self._t.start()

    def _on_frame(self, data: bytes):
        pix = QPixmap()
        if pix.loadFromData(data):
            self._last_pixmap = pix
            self._render_frame()
        else:
            self.label.setText("No frame")

    def _on_error(self, msg: str):
        self.label.setText(f"Camera error: {msg}")

    def _render_frame(self):
        if not self._last_pixmap:
            return
        pix = self._last_pixmap
        if self._rotation != 0:
            transform = QTransform()
            transform.rotate(self._rotation)
            pix = pix.transformed(transform, Qt.TransformationMode.SmoothTransformation)
        self.label.setPixmap(pix.scaled(self.label.width(), self.label.height(), aspectRatioMode=Qt.AspectRatioMode.KeepAspectRatio))

    def _rotate_left(self):
        self._rotation = (self._rotation - 90) % 360
        self._render_frame()

    def _rotate_right(self):
        self._rotation = (self._rotation + 90) % 360
        self._render_frame()

    def closeEvent(self, event):
        try:
            if getattr(self, '_t', None):
                self._t.stop()
                self._t.wait(200)
                self._t = None
            self._last_pixmap = None
        except Exception:
            pass
        return super().closeEvent(event)
