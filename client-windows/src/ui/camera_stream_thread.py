import requests
from PyQt6 import QtCore

class CameraStreamThread(QtCore.QThread):
    frame = QtCore.pyqtSignal(bytes)
    error = QtCore.pyqtSignal(str)

    def __init__(self, base_url: str, headers: dict[str, str] | None = None, parent=None):
        super().__init__(parent)
        self.base_url = base_url.rstrip('/')
        self.headers = headers or {}
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        url = f"{self.base_url}/camera/stream"
        boundary = b"--frame"
        try:
            with requests.get(url, headers=self.headers, stream=True, timeout=10) as resp:
                resp.raise_for_status()
                buf = b""
                for chunk in resp.iter_content(chunk_size=4096):
                    if not self._running:
                        break
                    if not chunk:
                        continue
                    buf += chunk
                    while True:
                        # Find boundary
                        bidx = buf.find(boundary)
                        if bidx == -1:
                            break
                        # Ensure we have the full header after boundary
                        hdr_start = bidx + len(boundary)
                        # Find header terminator \r\n\r\n
                        h_end = buf.find(b"\r\n\r\n", hdr_start)
                        if h_end == -1:
                            break
                        header = buf[hdr_start:h_end].decode(errors='ignore')
                        # Parse Content-Length
                        length = None
                        for line in header.split("\r\n"):
                            if line.lower().startswith("content-length:"):
                                try:
                                    length = int(line.split(":",1)[1].strip())
                                except Exception:
                                    length = None
                                break
                        if length is None:
                            # Drop up to header end and continue
                            buf = buf[h_end+4:]
                            continue
                        # Ensure full frame present
                        frame_start = h_end + 4
                        if len(buf) < frame_start + length + 2:
                            # wait for more bytes (+2 for trailing \r\n)
                            break
                        frame_bytes = buf[frame_start:frame_start+length]
                        # Emit
                        try:
                            self.frame.emit(frame_bytes)
                        except Exception:
                            pass
                        # Move buffer past this frame and trailing CRLF
                        buf = buf[frame_start+length+2:]
        except Exception as e:
            try:
                self.error.emit(str(e))
            except Exception:
                pass
