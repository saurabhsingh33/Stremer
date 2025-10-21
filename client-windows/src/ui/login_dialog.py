from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QLabel, QPushButton, QHBoxLayout, QCheckBox


class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Connect to Android Server")
        layout = QVBoxLayout(self)

        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("http://192.168.1.9:8080")
        self.host_input.setText("http://192.168.1.9:8080")

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Username")

        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_input.setPlaceholderText("Password")

        layout.addWidget(QLabel("Server URL"))
        layout.addWidget(self.host_input)
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
