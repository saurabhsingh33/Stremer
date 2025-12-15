from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QSlider,
    QSizePolicy,
)
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

        self.lens_combo = QComboBox()
        self.lens_combo.addItems(["Back", "Front"])
        controls.addWidget(QLabel("Lens:"))
        controls.addWidget(self.lens_combo)

        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(-100, 100)
        self.brightness_slider.setValue(0)
        self.brightness_slider.setSingleStep(5)
        self.brightness_slider.setPageStep(10)
        self.brightness_slider.setFixedWidth(160)
        controls.addWidget(QLabel("Brightness"))
        controls.addWidget(self.brightness_slider)

        self.sharpness_slider = QSlider(Qt.Orientation.Horizontal)
        self.sharpness_slider.setRange(0, 100)
        self.sharpness_slider.setValue(60)
        self.sharpness_slider.setSingleStep(5)
        self.sharpness_slider.setPageStep(10)
        self.sharpness_slider.setFixedWidth(160)
        controls.addWidget(QLabel("Sharpness"))
        controls.addWidget(self.sharpness_slider)

        controls.addStretch(1)

        self.rotate_left_btn = QPushButton("Rotate Left")
        self.rotate_right_btn = QPushButton("Rotate Right")
        controls.addWidget(self.rotate_left_btn)
        controls.addWidget(self.rotate_right_btn)

        layout.addLayout(controls)

        self._rotation = 0
        self._last_pixmap: QPixmap | None = None

        self.rotate_left_btn.clicked.connect(self._rotate_left)
        self.rotate_right_btn.clicked.connect(self._rotate_right)
        self.lens_combo.currentIndexChanged.connect(self._switch_lens)
        self.brightness_slider.sliderReleased.connect(self._adjust_settings)
        self.sharpness_slider.sliderReleased.connect(self._adjust_settings)

        self._is_switching = False
        self._start_stream()

    def _on_frame(self, data: bytes):
        pix = QPixmap()
        if pix.loadFromData(data):
            self._last_pixmap = pix
            self._render_frame()
        else:
            self.label.setText("No frame")

    def _on_error(self, msg: str):
        if not self._is_switching:
            self.label.setText(f"Camera error: {msg}")

    def _on_status(self, msg: str):
        self.label.setText(msg)

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

    def _switch_lens(self):
        self._is_switching = True
        self.label.setText("Switching camera...")
        try:
            if getattr(self, '_t', None):
                self._t.stop(suppress_errors=True)
                self._t.wait(1000)
        except Exception:
            pass
        self._start_stream()
        self._is_switching = False

    def _adjust_settings(self):
        # Don't show message, just reconnect silently with new settings
        self._is_switching = True
        try:
            if getattr(self, '_t', None):
                self._t.stop(suppress_errors=True)
                self._t.wait(1000)
        except Exception:
            pass
        self._start_stream()
        self._is_switching = False

    def _start_stream(self):
        headers = {}
        if getattr(self.api_client, 'token', None):
            headers['Authorization'] = f"Bearer {self.api_client.token}"
        lens = "front" if self.lens_combo.currentIndex() == 1 else "back"
        params = {
            "lens": lens,
            "brightness": self.brightness_slider.value(),
            "sharpness": self.sharpness_slider.value(),
        }
        self._t = CameraStreamThread(self.api_client.base_url, headers=headers, params=params, parent=self)
        self._t.frame.connect(self._on_frame)
        self._t.error.connect(self._on_error)
        self._t.status.connect(self._on_status)
        self._t.start()

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
