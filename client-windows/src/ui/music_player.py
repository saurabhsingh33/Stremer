from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel, QStyle, QListWidget
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QPainter, QPen, QBrush
import vlc
import requests


class MusicPlayer(QDialog):
    def __init__(self, url: str, token: str = None, display_name: str = None, parent=None, playlist=None, start_index=0):
        super().__init__(parent)

        # Playlist support: each item is {url, token, display_name}
        self.playlist = playlist if playlist else [{"url": url, "token": token, "display_name": display_name or "Audio"}]
        self.current_index = start_index

        self.is_seeking = False
        self.is_playing = False

        # Repeat modes: "no_repeat", "repeat_one", "repeat_all"
        self.repeat_mode = "no_repeat"

        self.setWindowTitle(f"Music Player")
        self.setMinimumWidth(500)
        self.setMinimumHeight(250)

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

        # Top info row: album art (left) and text (right)
        top_row = QHBoxLayout()

        self.art_label = QLabel()
        self.art_label.setFixedSize(140, 140)
        self.art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.art_label.setStyleSheet("border: 1px solid #444; background: #222;")
        self._set_placeholder_art()
        top_row.addWidget(self.art_label)

        text_col = QVBoxLayout()
        text_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.title_label = QLabel()
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px; padding: 4px 4px 2px 4px;")
        text_col.addWidget(self.title_label)

        self.status_label = QLabel("Loading...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.status_label.setStyleSheet("padding: 0 4px 4px 4px; color: #ccc;")
        text_col.addWidget(self.status_label)

        # Spacer to push text to top if art is taller
        text_col.addStretch()

        top_row.addLayout(text_col, 1)
        layout.addLayout(top_row)

        # Playlist widget (only show if multiple tracks)
        if len(self.playlist) > 1:
            self.playlist_widget = QListWidget()
            self.playlist_widget.setMaximumHeight(100)
            for item in self.playlist:
                self.playlist_widget.addItem(item["display_name"])
            self.playlist_widget.itemDoubleClicked.connect(self._on_playlist_item_clicked)
            layout.addWidget(self.playlist_widget)
        else:
            self.playlist_widget = None

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

        # Previous button (only if playlist has multiple tracks)
        if len(self.playlist) > 1:
            self.prev_button = QPushButton()
            self.prev_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward))
            self.prev_button.clicked.connect(self._previous_track)
            self.prev_button.setFixedSize(40, 40)
        else:
            self.prev_button = None

        self.play_button = QPushButton()
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.play_button.clicked.connect(self._toggle_play)
        self.play_button.setFixedSize(40, 40)

        self.stop_button = QPushButton()
        self.stop_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.stop_button.clicked.connect(self._stop)
        self.stop_button.setFixedSize(40, 40)

        # Next button (only if playlist has multiple tracks)
        if len(self.playlist) > 1:
            self.next_button = QPushButton()
            self.next_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward))
            self.next_button.clicked.connect(self._next_track)
            self.next_button.setFixedSize(40, 40)
        else:
            self.next_button = None

        # Volume control
        volume_icon = QLabel("🔊")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.setMaximumWidth(100)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        # Set initial volume for VLC (0-100 range)
        self.player.audio_set_volume(50)

        # Repeat mode button
        self.repeat_button = QPushButton("Repeat: Off")
        self.repeat_button.setMinimumWidth(90)
        self.repeat_button.setToolTip("Click to cycle: Off → All → One")
        self.repeat_button.clicked.connect(self._toggle_repeat_mode)
        self.repeat_button.setStyleSheet("QPushButton { padding: 5px; }")

        controls_layout.addStretch()
        if self.prev_button:
            controls_layout.addWidget(self.prev_button)
        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.stop_button)
        if self.next_button:
            controls_layout.addWidget(self.next_button)
        controls_layout.addStretch()
        controls_layout.addWidget(self.repeat_button)
        controls_layout.addWidget(volume_icon)
        controls_layout.addWidget(self.volume_slider)

        layout.addLayout(controls_layout)

        # Update UI with current track info
        self._update_track_info()

        # Update UI with current track info
        self._update_track_info()

    def _update_track_info(self):
        """Update UI to show current track information"""
        current = self.playlist[self.current_index]
        if len(self.playlist) > 1:
            title = f"{current['display_name']} ({self.current_index + 1}/{len(self.playlist)})"
        else:
            title = current['display_name']
        self.title_label.setText(title)

        # Highlight current track in playlist
        if self.playlist_widget:
            self.playlist_widget.setCurrentRow(self.current_index)

    def _load_audio(self):
        """Load and start streaming the audio file"""
        try:
            current = self.playlist[self.current_index]
            print(f"MusicPlayer: Loading {current['url']}")

            # Set media from URL
            media = self.instance.media_new(current['url'])
            self.player.set_media(media)
            self.status_label.setText("Ready")

            # Update track info
            self._update_track_info()

            # Reset art to placeholder before fetching
            self._set_placeholder_art()

            # Try to fetch album art shortly after loading
            QTimer.singleShot(600, self._load_album_art)

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

        # Auto-advance to next track when current track ends
        if length > 0 and position >= length - 200 and self.is_playing:
            if self.repeat_mode == "repeat_one":
                # Hard restart current song to ensure playback resumes
                def _restart_current():
                    self.player.stop()
                    self.player.set_time(0)
                    self.player.play()
                    self.is_playing = True
                    self.update_timer.start()
                QTimer.singleShot(50, _restart_current)
            elif self.repeat_mode == "repeat_all":
                # Go to next track, or loop back to first
                if self.current_index < len(self.playlist) - 1:
                    QTimer.singleShot(100, self._next_track)
                else:
                    # Loop back to first track
                    self.current_index = 0
                    QTimer.singleShot(100, lambda: (self._stop(), self._load_audio()))
            elif self.repeat_mode == "no_repeat":
                # Only advance if not at last track
                if self.current_index < len(self.playlist) - 1:
                    QTimer.singleShot(100, self._next_track)

    def _on_volume_changed(self, value):
        self.player.audio_set_volume(value)

    def _on_slider_pressed(self):
        self.is_seeking = True

    def _on_slider_released(self):
        self.player.set_time(self.seek_slider.value())
        self.is_seeking = False

    def _on_slider_moved(self, position):
        self.position_label.setText(self._format_time(position))

    def _toggle_repeat_mode(self):
        """Cycle through repeat modes"""
        if self.repeat_mode == "no_repeat":
            self.repeat_mode = "repeat_all"
            self.repeat_button.setText("Repeat: All")
            self.repeat_button.setStyleSheet("QPushButton { padding: 5px; background-color: #4CAF50; color: white; font-weight: bold; }")
        elif self.repeat_mode == "repeat_all":
            self.repeat_mode = "repeat_one"
            self.repeat_button.setText("Repeat: One")
            self.repeat_button.setStyleSheet("QPushButton { padding: 5px; background-color: #2196F3; color: white; font-weight: bold; }")
        else:  # repeat_one
            self.repeat_mode = "no_repeat"
            self.repeat_button.setText("Repeat: Off")
            self.repeat_button.setStyleSheet("QPushButton { padding: 5px; }")

    def _set_placeholder_art(self):
        """Set a simple placeholder when no album art is available"""
        placeholder = QPixmap(140, 140)
        placeholder.fill(Qt.GlobalColor.darkGray)
        # Draw a simple music note
        painter = QPainter(placeholder)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(Qt.GlobalColor.white, 3))
        painter.setBrush(QBrush(Qt.GlobalColor.white))
        # Note stem and head
        painter.drawLine(85, 40, 85, 95)
        painter.drawLine(85, 40, 110, 30)
        painter.drawEllipse(70, 90, 25, 18)
        # Small second head
        painter.drawEllipse(95, 76, 22, 16)
        painter.end()
        self.art_label.setPixmap(placeholder)

    def _load_album_art(self):
        """Attempt to load album art from VLC metadata"""
        try:
            media = self.player.get_media()
            if not media:
                return
            art_url = media.get_meta(vlc.Meta.ArtworkURL)
            if not art_url:
                return

            # Fetch artwork (supports http/https or file paths)
            if art_url.startswith("http://") or art_url.startswith("https://"):
                resp = requests.get(art_url, timeout=3)
                resp.raise_for_status()
                data = resp.content
            else:
                with open(art_url, "rb") as f:
                    data = f.read()

            pix = QPixmap()
            if pix.loadFromData(data):
                self.art_label.setPixmap(pix.scaled(140, 140, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            else:
                self._set_placeholder_art()
        except Exception as e:
            print(f"MusicPlayer: album art load failed: {e}")
            self._set_placeholder_art()

    def _next_track(self):
        """Play next track in playlist"""
        if self.current_index < len(self.playlist) - 1:
            self.current_index += 1
            self._stop()
            self._load_audio()

    def _previous_track(self):
        """Play previous track in playlist"""
        if self.current_index > 0:
            self.current_index -= 1
            self._stop()
            self._load_audio()

    def _on_playlist_item_clicked(self, item):
        """Handle playlist item double-click"""
        index = self.playlist_widget.row(item)
        if index != self.current_index:
            self.current_index = index
            self._stop()
            self._load_audio()

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
