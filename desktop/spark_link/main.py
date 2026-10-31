import argparse
import os
from pathlib import Path
import sys
from PySide6.QtCore import QTimer, QUrl, QLockFile
from PySide6.QtGui import QGuiApplication, QIcon, QAction, QWindow
from PySide6.QtWidgets import QApplication,QSystemTrayIcon,QMenu
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from .backend import Backend
from .geometry import RoundedBox, Cable
from .state import STATE

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--screenshot')
    parser.add_argument('--page', type=int, default=0)
    parser.add_argument('--background',action='store_true')
    args = parser.parse_args()
    QGuiApplication.setApplicationName('Spark Link')
    QGuiApplication.setOrganizationName('Connect Dual Spark')
    os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setDesktopFileName('spark-link')
    STATE.mkdir(parents=True,exist_ok=True)
    lock = QLockFile(str(STATE/'window.lock'))
    server = QLocalServer(app)
    server_name = 'spark-link-'+str(os.getuid())
    if not args.screenshot:
        if not lock.tryLock(0):
            client = QLocalSocket()
            client.connectToServer(server_name)
            if client.waitForConnected(1000):
                client.write(b'raise')
                client.waitForBytesWritten(1000)
            return 0
        QLocalServer.removeServer(server_name)
        server.listen(server_name)
    root = Path(__file__).parent
    app.setWindowIcon(QIcon(str(root / 'assets/spark-link.svg')))
    qmlRegisterType(RoundedBox, 'SparkLink', 1, 0, 'RoundedBox')
    qmlRegisterType(Cable, 'SparkLink', 1, 0, 'CableGeometry')
    backend = Backend()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('manager', backend)
    engine.rootContext().setContextProperty('planner', backend.planner)
    engine.rootContext().setContextProperty('devices', backend.devices)
    engine.rootContext().setContextProperty('initialPage', args.page)
    engine.load(QUrl.fromLocalFile(str(root / 'qml/Main.qml')))
    if not engine.rootObjects(): return 1
    window=engine.rootObjects()[0]
    window.setPersistentGraphics(False)
    window.setPersistentSceneGraph(False)
    tray=QSystemTrayIcon(QIcon(str(root/'assets/spark-link.svg')),app)
    menu=QMenu()
    show_action=QAction(app)
    quit_action=QAction(app)
    menu.addAction(show_action); menu.addSeparator(); menu.addAction(quit_action)
    tray.setContextMenu(menu)
    def labels():
        show_action.setText(backend.translate('Открыть Spark Link'))
        quit_action.setText(backend.translate('Выход'))
        tray.setToolTip('Spark Link')
    labels(); backend.languageChanged.connect(labels)
    def show_window():
        window.showNormal(); window.raise_(); window.requestActivate()
    show_action.triggered.connect(show_window)
    def quit_app():
        if backend.busy: show_window(); return
        window.setProperty('allowExit',True)
        app.quit()
    quit_action.triggered.connect(quit_app)
    tray.activated.connect(lambda reason: show_window() if reason==QSystemTrayIcon.ActivationReason.Trigger else None)
    if QSystemTrayIcon.isSystemTrayAvailable(): tray.show()
    def availability():
        title=backend.translate('Найден новый Spark')
        message=backend.translate('Откройте Spark Link, чтобы добавить и настроить устройство.')
        if QSystemTrayIcon.isSystemTrayAvailable(): tray.showMessage(title,message)
        else:
            import shutil,subprocess
            if shutil.which('notify-send'): subprocess.Popen(['notify-send','--app-name=Spark Link',title,message],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    backend.devices.found.connect(availability)
    def visibility_changed(*args):
        visible=window.isVisible() and window.visibility()!=QWindow.Visibility.Minimized
        backend.setVisible(visible)
        if not visible: QTimer.singleShot(0,lambda:window.releaseResources() if not window.isVisible() or window.visibility()==QWindow.Visibility.Minimized else None)
    window.visibilityChanged.connect(visibility_changed)
    if args.background: window.hide()
    if not args.screenshot:
        def startup_recovery():
            if (Path.home()/'.local/share/connect-dual-spark/llama-server-wrapper.json').is_file() and all(n.get('ssh') for n in backend._topology['nodes'][1:]):
                backend.action('recover-auto')
        QTimer.singleShot(11000,startup_recovery)
    def raise_window():
        client=server.nextPendingConnection()
        if client:
            show_window()
            client.deleteLater()
    server.newConnection.connect(raise_window)
    if args.screenshot:
        def capture():
            window = engine.rootObjects()[0]
            image = window.grabWindow()
            image.save(args.screenshot)
            window.setProperty('allowExit',True)
            app.quit()
        QTimer.singleShot(12000, capture)
    result = app.exec()
    # Destroy QML objects while their context properties are still alive.
    engine.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return result

if __name__ == '__main__':
    raise SystemExit(main())
