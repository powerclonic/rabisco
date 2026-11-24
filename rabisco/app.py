"""Ponto de entrada: instância única, tema, tray, atalho global e loop do Qt."""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QLocale, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from .config import APP_ID, APP_NAME, DATA_FILE, ICON_PATH, IS_WIN, SERVER_NAME, install_excepthook
from .store import Store
from .ui.panel import Panel
from .ui.theme import dark_palette, make_fallback_icon, stylesheet

if IS_WIN:
    from .winapi import GlobalHotkey

def notify_running_instance() -> bool:
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(300):
        return False
    sock.write(b"show")
    sock.flush()
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


def main() -> int:
    install_excepthook()
    if IS_WIN:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (OSError, AttributeError):
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    if notify_running_instance():  # já aberto: só pede pra mostrar
        return 0

    QLocale.setDefault(QLocale("pt_BR"))
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    font = QFont()
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "sans-serif"])
    font.setPointSizeF(10)
    app.setFont(font)
    app.setStyleSheet(stylesheet())

    icon = QIcon(str(ICON_PATH)) if ICON_PATH.exists() else make_fallback_icon()
    app.setWindowIcon(icon)

    store = Store(DATA_FILE)
    panel = Panel(store, icon)

    server = QLocalServer(app)
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def on_conn():
        conn = server.nextPendingConnection()
        if conn:
            conn.disconnected.connect(conn.deleteLater)
        panel.show_panel()

    server.newConnection.connect(on_conn)

    hotkey = None
    if IS_WIN:
        hotkey = GlobalHotkey(store.settings["hotkey"], panel.toggle_from_hotkey)
        app.installNativeEventFilter(hotkey)
    panel.set_hotkey_status(bool(hotkey and hotkey.ok))

    def on_quit():
        store.save_now()
        if hotkey:
            hotkey.unregister()

    app.aboutToQuit.connect(on_quit)

    if "--hidden" not in sys.argv:
        QTimer.singleShot(0, panel.show_panel)
    return app.exec()
