import sys
import traceback
from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
from PyQt6.QtWidgets import QApplication, QMessageBox
from ui.main_window import MainWindow
from ui.theme import apply_theme


def _qt_message_handler(mode: QtMsgType, context, message: str):
    try:
        mode_name = {
            QtMsgType.QtDebugMsg: "DEBUG",
            QtMsgType.QtInfoMsg: "INFO",
            QtMsgType.QtWarningMsg: "WARNING",
            QtMsgType.QtCriticalMsg: "CRITICAL",
            QtMsgType.QtFatalMsg: "FATAL",
        }.get(mode, str(mode))
    except Exception:
        mode_name = str(mode)
    # Print Qt messages to stdout so we can see pre-crash diagnostics
    print(f"[Qt-{mode_name}] {message}")
    # Note: QtFatalMsg will terminate after this handler returns


def _excepthook(exctype, value, tb):
    # Log any uncaught Python exceptions instead of silent exit
    print("[PyException] Uncaught exception:")
    traceback.print_exception(exctype, value, tb)
    try:
        QMessageBox.critical(None, "Unhandled Error", f"{exctype.__name__}: {value}\n\n" + ''.join(traceback.format_tb(tb)))
    except Exception:
        pass


def main():
    # Install robust logging hooks for early-crash diagnostics
    sys.excepthook = _excepthook
    qInstallMessageHandler(_qt_message_handler)

    app = QApplication(sys.argv)
    apply_theme(app)

    # Log lifecycle events
    app.aboutToQuit.connect(lambda: print("[App] aboutToQuit signaled"))

    window = MainWindow()
    window.show()

    print("[App] Entering Qt event loop")
    rc = app.exec()
    print(f"[App] Qt event loop exited with code {rc}")
    sys.exit(rc)


if __name__ == "__main__":
    main()
