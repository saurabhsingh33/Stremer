import socket
import requests
from PyQt6 import QtCore
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLineEdit,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QCheckBox,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
)


class ScanThread(QtCore.QThread):
    results_ready = QtCore.pyqtSignal(list)
    progress = QtCore.pyqtSignal(int, int, str)  # current index, total, current ip
    found = QtCore.pyqtSignal(str)  # url found

    def __init__(self, prefix: str, port: int = 8080, timeout: float = 0.25, parent=None):
        super().__init__(parent)
        self.prefix = prefix
        self.port = port
        self.timeout = timeout
        self._running = True

    def run(self):
        found = []
        parts = self.prefix.split('.')
        if len(parts) < 3:
            self.results_ready.emit(found)
            return
        base = '.'.join(parts[:3]) + '.'
        # scan 1..254
        total = 254
        for i in range(1, 255):
            if not self._running:
                break
            ip = base + str(i)
            # emit progress before probing
            try:
                self.progress.emit(i, total, ip)
            except Exception:
                pass
            # perform a lightweight HTTP probe against /files to verify Stremer server
            try:
                url = f"http://{ip}:{self.port}/ping"
                r = requests.get(url, timeout=self.timeout)
                # treat 200 (OK) as evidence of a Stremer server (ping is unauthenticated)
                if r.status_code == 200:
                    server_url = f"http://{ip}:{self.port}"
                    found.append(server_url)
                    try:
                        self.found.emit(server_url)
                    except Exception:
                        pass
            except Exception:
                # ignore timeouts and connection errors
                pass
        self.results_ready.emit(found)

    def stop(self):
        self._running = False




class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Connect to Android Server")
        # Wider dialog so fields and scan results are fully visible
        try:
            self.setMinimumWidth(320)
        except Exception:
            pass
        layout = QVBoxLayout(self)

        # Host input + scan button
        host_row = QHBoxLayout()
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("http://192.168.0.0:8080")
        self.host_input.setText(f"http://192.168.{0}.{0}:8080")
        self.scan_btn = QPushButton("Scan LAN")
        host_row.addWidget(self.host_input)
        host_row.addWidget(self.scan_btn)

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Username")

        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_input.setPlaceholderText("Password")

        layout.addWidget(QLabel("Server URL"))
        layout.addLayout(host_row)
        layout.addWidget(QLabel("Username"))
        layout.addWidget(self.user_input)
        layout.addWidget(QLabel("Password"))
        layout.addWidget(self.pass_input)

        # Remember me
        self.remember_check = QCheckBox("Remember me for 30 days")
        self.remember_check.setChecked(True)
        layout.addWidget(self.remember_check)

        btns = QHBoxLayout()
        self.login_btn = QPushButton("Login")
        self.cancel_btn = QPushButton("Cancel")
        btns.addWidget(self.login_btn)
        btns.addWidget(self.cancel_btn)
        layout.addLayout(btns)

        self.cancel_btn.clicked.connect(self.reject)

        # Scan handling
        self._scan_thread = None
        self.scan_btn.clicked.connect(self._on_scan_clicked)

    def _get_local_ip(self) -> str | None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return None

    def _on_scan_clicked(self):
        # Derive prefix from local IP
        local = self._get_local_ip()
        if not local:
            # fallback to common prefixes
            prefix = "192.168.1."
        else:
            parts = local.split('.')
            if len(parts) >= 3:
                prefix = '.'.join(parts[:3]) + '.'
            else:
                prefix = '192.168.1.'

        # Disable button while scanning
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Scanning…")

        # Prepare live results dialog immediately
        self._scan_dialog = QDialog(self)
        self._scan_dialog.setWindowTitle("Scanning LAN for Stremer servers…")
        v = QVBoxLayout(self._scan_dialog)
        self._scan_status = QLabel("Starting scan…")
        v.addWidget(self._scan_status)
        self._scan_progress = QProgressBar()
        self._scan_progress.setRange(0, 254)
        self._scan_progress.setValue(0)
        v.addWidget(self._scan_progress)
        self._scan_list = QListWidget()
        v.addWidget(self._scan_list)
        btn_row = QHBoxLayout()
        self._scan_select_btn = QPushButton("Select")
        self._scan_select_btn.setEnabled(False)
        self._scan_cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(self._scan_select_btn)
        btn_row.addWidget(self._scan_cancel_btn)
        v.addLayout(btn_row)

        # Enable Select only when item chosen
        self._scan_list.itemSelectionChanged.connect(
            lambda: self._scan_select_btn.setEnabled(self._scan_list.currentItem() is not None)
        )

        # Wire button actions
        def _select_current():
            it = self._scan_list.currentItem()
            if it:
                self.host_input.setText(it.text())
                self._stop_scan_thread()
                self.scan_btn.setEnabled(True)
                self.scan_btn.setText("Scan LAN")
                self._scan_dialog.accept()

        def _cancel_scan():
            self._stop_scan_thread()
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText("Scan LAN")
            self._scan_dialog.reject()

        self._scan_select_btn.clicked.connect(_select_current)
        self._scan_cancel_btn.clicked.connect(_cancel_scan)
        self._scan_list.itemDoubleClicked.connect(lambda it: (_select_current()))

        # Start scanning thread and show dialog
        self._scan_thread = ScanThread(prefix, 8080, timeout=0.18)
        self._scan_thread.progress.connect(self._on_scan_progress)
        self._scan_thread.found.connect(self._on_scan_found)
        self._scan_thread.results_ready.connect(self._on_scan_complete)
        self._scan_thread.start()
        self._scan_dialog.show()

    def _on_scan_progress(self, current: int, total: int, ip: str):
        # Update progress UI
        try:
            self._scan_progress.setMaximum(total)
            self._scan_progress.setValue(current)
            self._scan_status.setText(f"Scanning: {ip}")
        except Exception:
            pass

    def _on_scan_found(self, url: str):
        # Add found server if not already listed
        try:
            for i in range(self._scan_list.count()):
                if self._scan_list.item(i).text() == url:
                    return
            self._scan_list.addItem(QListWidgetItem(url))
        except Exception:
            pass

    def _on_scan_complete(self, results: list):
        # Finalize UI state; keep dialog open for selection
        try:
            self._scan_status.setText("Scan complete")
            self._scan_progress.setValue(self._scan_progress.maximum())
            # Populate any remaining results that may not have been added (safety)
            existing = {self._scan_list.item(i).text() for i in range(self._scan_list.count())}
            for url in results:
                if url not in existing:
                    self._scan_list.addItem(QListWidgetItem(url))
        except Exception:
            pass
        # Re-enable the Scan LAN button
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Scan LAN")

    def _stop_scan_thread(self):
        try:
            if self._scan_thread and self._scan_thread.isRunning():
                self._scan_thread.stop()
                self._scan_thread.wait(100)
        except Exception:
            pass
