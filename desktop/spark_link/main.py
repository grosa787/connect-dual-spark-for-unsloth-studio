import argparse
import os
from pathlib import Path
import sys
from PySide6.QtCore import QTimer, QUrl, QLockFile
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from .backend import Backend
from .geometry import RoundedBox, Cable
from .state import STATE

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--screenshot')
    parser.add_argument('--page', type=int, default=0)
    args = parser.parse_args()
    QGuiApplication.setApplicationName('Spark Link')
    QGuiApplication.setOrganizationName('Connect Dual Spark')
    os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')
    app = QGuiApplication(sys.argv)
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
    engine.rootContext().setContextProperty('initialPage', args.page)
    engine.load(QUrl.fromLocalFile(str(root / 'qml/Main.qml')))
    if not engine.rootObjects(): return 1
    def raise_window():
        client=server.nextPendingConnection()
        if client:
            window=engine.rootObjects()[0]
            window.showNormal()
            window.raise_()
            window.requestActivate()
            client.deleteLater()
    server.newConnection.connect(raise_window)
    if args.screenshot:
        def capture():
            window = engine.rootObjects()[0]
            image = window.grabWindow()
            image.save(args.screenshot)
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
