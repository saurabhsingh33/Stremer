import os
import subprocess

DEFAULT_VLC_PATHS = [
    r"C:\\Program Files\\VideoLAN\\VLC\\vlc.exe",
    r"C:\\Program Files (x86)\\VideoLAN\\VLC\\vlc.exe"
]


def find_vlc():
    for p in DEFAULT_VLC_PATHS:
        if os.path.exists(p):
            return p
    return None


def play_url(url: str):
    """Stream the URL directly in VLC with stream-friendly flags."""
    vlc = find_vlc()
    if vlc:
        subprocess.Popen([
            vlc,
            "--http-reconnect",
            "--network-caching=4000",
            "--avcodec-hw=none",  # force software decoding to avoid driver quirks
            "--vout=direct3d11,direct3d9,opengl,wingdi",  # try multiple video outputs
            url
        ])
    else:
        # Fallback: let Windows open default handler
        os.startfile(url)
