from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QLabel,
    QStyle,
    QListWidget,
    QWidget,
)
from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QPixmap, QPainter, QPen, QBrush, QColor
import json
import math
import os
import random
import struct
import subprocess
import threading
import shutil
from pathlib import Path
import requests
import vlc


class VisualizerWidget(QWidget):
    def __init__(self, bars: int = 16, parent=None):
        super().__init__(parent)
        self.bars = bars
        self.levels = [0.0] * bars
        self.setMinimumHeight(40)

    def set_levels(self, levels: list[float]):
        self.levels = [max(0.0, min(1.0, lv)) for lv in levels[: self.bars]]
        if len(self.levels) < self.bars:
            self.levels += [0.0] * (self.bars - len(self.levels))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar_width = max(4, self.width() / max(1, self.bars))
        for idx, level in enumerate(self.levels):
            height = level * self.height()
            x = idx * bar_width
            y = self.height() - height
            rect = QRectF(x + 2, y, bar_width - 4, height)
            color = QColor.fromHsv(180 + int(level * 60), 220, 230)
            painter.fillRect(rect, color)
        painter.end()


class MusicPlayer(QDialog):
    def __init__(self, url: str, token: str = None, display_name: str = None, parent=None, playlist=None, start_index=0):
        super().__init__(parent)

        # Playlist support: each item is {url, token, display_name}
        self.playlist = playlist if playlist else [{"url": url, "token": token, "display_name": display_name or "Audio"}]
        self.current_index = start_index

        self.is_seeking = False
        self.is_playing = False
        self._last_visualizer_time = 0
        self._visualizer_thread = None
        self._visualizer_stop = threading.Event()
        self._visualizer_proc = None
        self._ffmpeg_path = shutil.which("ffmpeg")
        self._visualizer_prev_levels = [0.0] * 16
        self._settings = self._load_settings()
        self._settings_timer = QTimer(self)
        self._settings_timer.setSingleShot(True)
        self._settings_timer.setInterval(500)
        self._settings_timer.timeout.connect(self._persist_settings)

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
        self._apply_saved_geometry()
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

        self.visualizer = VisualizerWidget()
        self.visualizer.setMaximumHeight(50)
        text_col.addWidget(self.visualizer)

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
        self.volume_slider.setMaximumWidth(100)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        saved_volume = None
        if isinstance(self._settings, dict):
            saved_volume = self._settings.get("volume")
        if not isinstance(saved_volume, int):
            saved_volume = 50
        saved_volume = max(0, min(100, saved_volume))
        self.volume_slider.setValue(saved_volume)

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

            # Launch real analyzer if available
            self._start_visualizer_analyzer(current['url'])

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
        self.visualizer.set_levels([0] * self.visualizer.bars)
        self._stop_visualizer_analyzer()

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

        # Update visualizer
        self._refresh_visualizer(position, length)

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
        self._queue_settings_save()

    def _on_slider_pressed(self):
        self.is_seeking = True

    def _on_slider_released(self):
        self.player.set_time(self.seek_slider.value())
        self.is_seeking = False

    def _on_slider_moved(self, position):
        self.position_label.setText(self._format_time(position))

    def _refresh_visualizer(self, position: int, length: int):
        if not self.is_playing or length <= 0:
            self.visualizer.set_levels([0] * self.visualizer.bars)
            return
        delta = max(1, position - self._last_visualizer_time)
        self._last_visualizer_time = position
        if self._visualizer_thread and self._visualizer_thread.is_alive():
            return  # analyzer thread controls levels once running
        # fallback animation using volume/time when analyzer unavailable
        energy = min(1.0, (delta / 500.0) + 0.2)
        levels = []
        volume = max(0.1, min(1.0, self.player.audio_get_volume() / 100.0))
        for idx in range(self.visualizer.bars):
            base = energy * ((idx + 1) / self.visualizer.bars)
            ripple = 0.15 * random.random()
            scale = (base + ripple) * (0.5 + 0.5 * volume)
            levels.append(min(1.0, max(0.05, scale)))
        self.visualizer.set_levels(levels)

    def _start_visualizer_analyzer(self, url: str):
        self._stop_visualizer_analyzer()
        if not self._ffmpeg_path:
            return
        args = [
            self._ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            url,
            "-f",
            "f32le",
            "-ac",
            "1",
            "-" ,
        ]
        try:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except Exception:
            return
        stop_event = threading.Event()
        self._visualizer_proc = proc
        self._visualizer_stop = stop_event
        def worker():
            chunk_bytes = 4096 * 4
            while not stop_event.is_set():
                data = proc.stdout.read(chunk_bytes)
                if not data:
                    break
                num_vals = len(data) // 4
                if num_vals == 0:
                    continue
                values = struct.unpack("<%df" % num_vals, data)
                bands = [0.0] * self.visualizer.bars
                counts = [0] * self.visualizer.bars
                for idx, value in enumerate(values):
                    band_idx = min(self.visualizer.bars - 1, int(idx / num_vals * self.visualizer.bars))
                    bands[band_idx] += value * value
                    counts[band_idx] += 1
                levels = []
                for idx in range(self.visualizer.bars):
                    avg = bands[idx] / max(1, counts[idx])
                    freq_weight = 1.2 - (idx / self.visualizer.bars) * 0.7
                    level = min(1.0, math.sqrt(avg) * 25 * freq_weight)
                    smooth = self._visualizer_prev_levels[idx] * 0.65 + level * 0.35
                    self._visualizer_prev_levels[idx] = smooth
                    levels.append(smooth)
                QTimer.singleShot(0, lambda lv=list(levels): self.visualizer.set_levels(lv))
            proc.stdout.close()
            proc.wait()
        thread = threading.Thread(target=worker, daemon=True)
        self._visualizer_thread = thread
        thread.start()

    def _stop_visualizer_analyzer(self):
        if self._visualizer_thread and self._visualizer_thread.is_alive():
            self._visualizer_stop.set()
            if self._visualizer_proc:
                try:
                    self._visualizer_proc.terminate()
                except Exception:
                    pass
            self._visualizer_thread.join(timeout=0.1)
        self._visualizer_thread = None
        self._visualizer_proc = None
        self._visualizer_prev_levels = [0.0] * self.visualizer.bars

    def _settings_file(self) -> Path:
        appdata = os.getenv('APPDATA')
        if appdata:
            base = Path(appdata) / 'Stremer'
        else:
            base = Path.home() / '.stremer'
        base.mkdir(parents=True, exist_ok=True)
        return base / 'player_settings.json'

    def _load_settings(self) -> dict:
        try:
            text = self._settings_file().read_text()
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _persist_settings(self):
        if not hasattr(self, 'volume_slider'):
            return
        data = {
            'volume': self.volume_slider.value(),
            'geometry': {
                'x': self.x(),
                'y': self.y(),
                'width': self.width(),
                'height': self.height(),
            }
        }
        try:
            self._settings_file().write_text(json.dumps(data))
        except Exception:
            pass

    def _queue_settings_save(self):
        if self._settings_timer.isActive():
            self._settings_timer.stop()
        self._settings_timer.start()

    def _apply_saved_geometry(self):
        geometry = self._settings.get('geometry') if isinstance(self._settings, dict) else None
        if not isinstance(geometry, dict):
            return
        try:
            width = geometry.get('width')
            height = geometry.get('height')
            if isinstance(width, int) and width > 0 and isinstance(height, int) and height > 0:
                self.resize(width, height)
            x = geometry.get('x')
            y = geometry.get('y')
            if isinstance(x, int) and isinstance(y, int):
                self.move(x, y)
        except Exception:
            pass

    def moveEvent(self, event):
        super().moveEvent(event)
        self._queue_settings_save()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._queue_settings_save()

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
        self._stop_visualizer_analyzer()
        self._settings_timer.stop()
        self._persist_settings()
        super().closeEvent(event)
