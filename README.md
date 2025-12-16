# Stremer

Stremer is a lightweight, LAN-first media streaming solution consisting of:

- A Windows desktop client (PyQt6) for browsing and playing media
- An Android server app that hosts your files and streams them over HTTP to your LAN

It’s designed for quick setup, smooth playback, and a simple, familiar UI for real-world use.

## Features

### Windows Client (Desktop)

- File browser with list and icon views
- Context menus for common actions (Open, Open with…, Play in Mini Player, Delete, Properties)
- Music Player (Full):
  - Playlist auto-assembly from the current folder
  - Play/Pause/Stop, volume control, repeat modes, progress/seek bar
  - Always-on-top toggle
  - Audio visualizer (if ffmpeg is available in PATH)
  - Album art fetching (best effort)
  - Switch to Mini Player without interrupting playback
- Mini Music Player:
  - Compact, docked to the right edge of your screen
  - Always-on-top toggle
  - Play/Pause/Stop, progress/seek bar
  - “Play in Mini Player” from file browser context menu or toolbar button
  - Seamless switching back to full player preserving position and state
  - Reuses the existing mini/full player window when opening a new track (prevents duplicate windows)
- Camera Viewer (if configured)
- Robust session handling: gracefully closes and releases VLC without crashes

### Android Server (Mobile)

- Serves files over HTTP to your local network
- Simple setup; runs as a background service while the app is open
- Generates stream URLs consumable by the Windows client

## What To Expect

- Instant playback on local network without cloud dependency
- Smooth switching between full and mini music players without losing your place
- Familiar file browsing with right-click context actions
- Minimal setup: just run server on your phone and point the client at it

## Getting Started

### Prerequisites (Windows Client)

- Windows 10/11 (x64)
- Python 3.10+
- VLC Media Player (64-bit) installed (required by `python-vlc`)
- Optional: `ffmpeg` in PATH for the audio visualizer

### Install (Windows Client)

1. Open a terminal in `client-windows`.
2. Create/activate a virtual environment (recommended).
3. Install dependencies:

```powershell
cd client-windows
pip install -r requirements.txt
```

4. Run the app:

```powershell
python .\src\main.py
```

### Run (Android Server)

- Open the `server-android` project in Android Studio
- Build and install the app on your Android device (debug or release)
- Start the server within the app; note the displayed base URL (e.g., `http://phone-ip:8080`)
- Ensure the phone and PC are on the same Wi‑Fi/LAN

## Using Stremer (Windows Client)

### Connect to Server

- On launch, enter your server base URL (e.g., `http://192.168.1.50:8080`)
- If the server allows anonymous access, the client may auto-connect; otherwise, log in

### Browse Files

- Navigate directories via the left tree and the main browser
- Use list or icons view; right-click files for actions

### Play Music

- Double‑click an audio file to open the full Music Player
- The player automatically builds a playlist from audio files in the current folder
- Use the controls for play/pause/stop, volume, seek, and repeat
- Toggle always‑on‑top to keep the player visible

### Mini Player

- If the folder has audio files, a Mini Player toolbar button appears in the browser
- Right‑click any audio → “Play in Mini Player”
- Switch between full and mini using the ⇄ button; playback position and state are preserved
- When you open another song from the browser, the existing player window is reused and starts that track

### Camera Viewer

- Open camera streams (if configured in your environment) from the toolbar or context as applicable

## Tips & Notes

- VLC requirement: `python-vlc` loads the VLC runtime—install VLC (64‑bit). If VLC isn’t found, playback can fail.
- Visualizer: requires `ffmpeg` in your PATH. Without it, the visualizer gracefully falls back.
- Anonymous access: The client attempts anonymous login when credentials aren’t required. Otherwise, use your server login.
- Position/State Preservation: Switching full ↔ mini preserves playback position and whether audio is playing/paused.
- Single Instance Reuse: Opening a new audio from the browser focuses the existing player (full or mini) rather than spawning new windows.

## Known Limitations

- LAN-focused: Designed for local networks; WAN usage not covered
- Album art retrieval is best-effort and may not be available for all files
- Camera setup depends on your environment; not all streams are guaranteed to work

## Troubleshooting

- “No audio / cannot play” → Make sure VLC (64‑bit) is installed and accessible to `python-vlc`.
- “Visualizer not working” → Install `ffmpeg` and ensure it’s in PATH.
- “Can’t connect to server” → Confirm the Android device and PC are on the same network; verify the server URL and port; ensure the app is running.
- “Playback restarts on switch” → This has been addressed; ensure you’re using the latest build and try again.

## Development

- Windows client: `client-windows`
  - Entry point: `src/main.py`
  - UI modules: `src/ui/*`
  - Browser: `src/file_browser/*`
  - Media helpers: `src/media/*`
- Android server: `server-android` (Android Studio project)

## Roadmap

- Windows installer (NSIS/Inno Setup) and signed distribution
- Android signed release APK
- Auto-update for Windows client
- Optional TLS and authentication hardening

---

If you run into issues or have suggestions during testing, please open an issue with steps to reproduce, logs (if any), and your environment details.
