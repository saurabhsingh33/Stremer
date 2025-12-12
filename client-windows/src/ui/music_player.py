from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel, QStyle
)
from PyQt6.QtCore import Qt, QTimer
import vlc


class MusicPlayer(QDialog):
    def __init__(self, url: str, token: str = None, display_name: str = None, parent=None):
        super().__init__(parent)
        self.url = url
        self.token = token
        self.display_name = display_name or "Audio"
        self.is_seeking = False
        self.is_playing = False

        self.setWindowTitle(f"Music Player - {self.display_name}")
        self.setMinimumWidth(450)
        self.setMinimumHeight(150)

        # Setup VLC player
        self.instance = vlc.Instance('--no-video')
        self.player = self.instance.media_player_new()

        # Timer for position updates
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._update_position)
        self.update_timer.setInterval(100)  # Update every 100ms

        self._setup_ui()
        self._load_audio()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Title label
        self.title_label = QLabel(self.display_name)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px; padding: 8px;")
        layout.addWidget(self.title_label)

        # Status label
        self.status_label = QLabel("Loading...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # Time labels and seek slider
        time_layout = QHBoxLayout()
        self.position_label = QLabel("0:00")
        self.duration_label = QLabel("0:00")

        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self.seek_slider.sliderReleased.connect(self._on_slider_released)
        self.seek_slider.sliderMoved.connect(self._on_slider_moved)

        time_layout.addWidget(self.position_label)
        time_layout.addWidget(self.seek_slider, 1)
        time_layout.addWidget(self.duration_label)
        layout.addLayout(time_layout)

        # Control buttons
        controls_layout = QHBoxLayout()

        self.play_button = QPushButton()
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.play_button.clicked.connect(self._toggle_play)
        self.play_button.setFixedSize(40, 40)

        self.stop_button = QPushButton()
        self.stop_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.stop_button.clicked.connect(self._stop)
        self.stop_button.setFixedSize(40, 40)

        # Volume control
        volume_icon = QLabel("🔊")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.setMaximumWidth(100)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        # Set initial volume for VLC (0-100 range)
        self.player.audio_set_volume(50)

        controls_layout.addStretch()
        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.stop_button)
        controls_layout.addStretch()
        controls_layout.addWidget(volume_icon)
        controls_layout.addWidget(self.volume_slider)

        layout.addLayout(controls_layout)

    def _load_audio(self):
        """Load and start streaming the audio file"""
        try:
            print(f"MusicPlayer: Loading {self.url}")

            # Set media from URL
            media = self.instance.media_new(self.url)
            self.player.set_media(media)
            self.status_label.setText("Ready")

            # Auto-play after loading
            QTimer.singleShot(500, self._play)
        except Exception as e:
            print(f"MusicPlayer: Error loading audio: {e}")
            self.status_label.setText(f"Error: {e}")

    def _toggle_play(self):
        if self.is_playing:
            self._pause()
        else:
            self._play()

    def _play(self):
        self.player.play()
        self.is_playing = True
        self.update_timer.start()
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        self.status_label.setText("Playing...")

    def _pause(self):
        self.player.pause()
        self.is_playing = False
        self.update_timer.stop()
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.status_label.setText("Paused")

    def _stop(self):
        self.player.stop()
        self.is_playing = False
        self.update_timer.stop()
        self.seek_slider.setValue(0)
        self.position_label.setText("0:00")
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.status_label.setText("Stopped")

    def _update_position(self):
        """Update position from VLC player"""
        if self.is_seeking:
            return

        # Get position in milliseconds
        position = self.player.get_time()
        length = self.player.get_length()

        if position >= 0:
            self.seek_slider.setValue(position)
            self.position_label.setText(self._format_time(position))

        if length > 0 and self.seek_slider.maximum() != length:
            self.seek_slider.setRange(0, length)
            self.duration_label.setText(self._format_time(length))

    def _on_volume_changed(self, value):
        self.player.audio_set_volume(value)

    def _on_slider_pressed(self):
        self.is_seeking = True

    def _on_slider_released(self):
        self.player.set_time(self.seek_slider.value())
        self.is_seeking = False

    def _on_slider_moved(self, position):
        self.position_label.setText(self._format_time(position))

    def _format_time(self, ms):
        """Format milliseconds to MM:SS"""
        seconds = ms // 1000
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes}:{seconds:02d}"

    def closeEvent(self, event):
        """Clean up when closing"""
        self.update_timer.stop()
        self.player.stop()
        self.player.release()
        super().closeEvent(event)
