import requests
from urllib.parse import urlencode
from PyQt6 import QtCore

class CameraStreamThread(QtCore.QThread):
    frame = QtCore.pyqtSignal(bytes)
    error = QtCore.pyqtSignal(str)
    status = QtCore.pyqtSignal(str)

    def __init__(self, base_url: str, headers: dict[str, str] | None = None, params: dict | None = None, parent=None):
        super().__init__(parent)
        self.base_url = base_url.rstrip('/')
        self.headers = headers or {}
        self.params = params or {}
        self._running = True
        self._response = None
        self._suppress_errors = False

    def stop(self, suppress_errors=False):
        self._running = False
        self._suppress_errors = suppress_errors
        try:
            if self._response:
                self._response.close()
        except Exception:
            pass

    def run(self):
        query = urlencode({k: v for k, v in self.params.items() if v is not None})
        url = f"{self.base_url}/camera/stream" + (f"?{query}" if query else "")
        boundary = b"--frame"
        try:
            self._response = requests.get(url, headers=self.headers, stream=True, timeout=10)
            self._response.raise_for_status()
            with self._response as resp:
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
            if not self._suppress_errors and self._running:
                try:
                    # Don't show raw errors, use friendly messages
                    if "NoneType" in str(e) or "read" in str(e).lower():
                        self.status.emit("Reconnecting...")
                    else:
                        self.error.emit(str(e))
                except Exception:
                    pass
