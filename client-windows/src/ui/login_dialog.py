import socket
import requests
from PyQt6 import QtCore
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QLabel, QPushButton, QHBoxLayout, QCheckBox, QListWidget, QListWidgetItem


class ScanThread(QtCore.QThread):
    results_ready = QtCore.pyqtSignal(list)

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
        for i in range(1, 255):
            if not self._running:
                break
            ip = base + str(i)
            # perform a lightweight HTTP probe against /files to verify Stremer server
            try:
                url = f"http://{ip}:{self.port}/ping"
                r = requests.get(url, timeout=self.timeout)
                # treat 200 (OK) as evidence of a Stremer server (ping is unauthenticated)
                if r.status_code == 200:
                    found.append(f"http://{ip}:{self.port}")
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
        layout = QVBoxLayout(self)

        # Host input + scan button
        host_row = QHBoxLayout()
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("http://192.168.0.0:8080")
        self.host_input.setText("")
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
        self._scan_thread = ScanThread(prefix, 8080, timeout=0.18)
        self._scan_thread.results_ready.connect(self._on_scan_results)
        self._scan_thread.start()

    def _on_scan_results(self, results: list):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Scan LAN")
        # Show results dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Select server")
        v = QVBoxLayout(dlg)
        listw = QListWidget()
        for url in results:
            item = QListWidgetItem(url)
            listw.addItem(item)
        v.addWidget(listw)
        btn_row = QHBoxLayout()
        ok = QPushButton("Select")
        cancel = QPushButton("Cancel")
        btn_row.addWidget(ok)
        btn_row.addWidget(cancel)
        v.addLayout(btn_row)

        def on_select():
            it = listw.currentItem()
            if it:
                self.host_input.setText(it.text())
                dlg.accept()

        ok.clicked.connect(on_select)
        cancel.clicked.connect(dlg.reject)

        # Double-click to select
        listw.itemDoubleClicked.connect(lambda it: (self.host_input.setText(it.text()), dlg.accept()))

        dlg.exec()
