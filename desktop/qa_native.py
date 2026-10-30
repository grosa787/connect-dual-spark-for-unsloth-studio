"""Real ARM64 Qt interaction/render smoke; uses read-only inventory, never applies a changed network."""
import os
from pathlib import Path
import sys
import faulthandler
import signal
import time
import tempfile
qa_config=tempfile.TemporaryDirectory(prefix='spark-link-qa-config-')
os.environ['XDG_CONFIG_HOME']=qa_config.name
faulthandler.register(signal.SIGUSR1)
from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QUrl, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtTest import QTest
from spark_link.backend import Backend
from spark_link.geometry import RoundedBox, Cable

app=QGuiApplication(sys.argv)
def wait(milliseconds):
    until=time.monotonic()+milliseconds/1000
    while time.monotonic()<until:
        app.processEvents()
        time.sleep(0.01)
qmlRegisterType(RoundedBox,'SparkLink',1,0,'RoundedBox')
qmlRegisterType(Cable,'SparkLink',1,0,'CableGeometry')
backend=Backend()
engine=QQmlApplicationEngine()
messages=[]
qInstallMessageHandler(lambda kind,ctx,msg: messages.append(msg))
engine.rootContext().setContextProperty('manager',backend)
engine.rootContext().setContextProperty('initialPage',0)
engine.load(QUrl.fromLocalFile(str(Path(__file__).parent/'spark_link/qml/Main.qml')))
print('QML loaded',flush=True)
assert engine.rootObjects(), messages
window=engine.rootObjects()[0]
wait(9000)
print('Inventory waited',flush=True)
assert len(backend.nodes)==2 and all(n['online'] for n in backend.nodes), backend.nodes
folder=Path('/tmp/spark-link-qa'); folder.mkdir(exist_ok=True)
def click(name):
    item=find(name)
    assert item is not None, name
    point=item.mapToScene(QPointF(item.width()/2,item.height()/2))
    QTest.mouseClick(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(int(point.x()),int(point.y())))
    wait(350)
def find(name):
    pending=[window.contentItem()]
    while pending:
        item=pending.pop()
        if item.objectName()==name: return item
        pending.extend(item.childItems())
    return None
for page in range(5):
    click('nav_'+str(page))
    assert window.property('page')==page
    assert window.grabWindow().save(str(folder/f'page-{page}.png'))
    print('Rendered page',page,flush=True)
click('nav_1')
click('threeNodes')
assert len(backend.topology['nodes'])==3
assert not backend.nodes[2]['online']
window.grabWindow().save(str(folder/'three-nodes.png'))
click('twoNodes')
backend.refresh(); wait(6000)
combo=find('cableB_0')
assert combo is not None
combo.forceActiveFocus()
QTest.keyClick(window,Qt.Key.Key_Down)
wait(300)
assert backend.topology['cables'][0]['b_port']==1
backend.refresh(); wait(6000)
assert backend.topology['cables'][0]['b_port']==1, 'poll overwrote draft port'
assert backend.clusterText!='Spark соединены', 'draft mismatch incorrectly reported connected'
backend.setPort(0,'b',0)
backend.refresh(); wait(6000)
assert backend.clusterText=='Spark соединены', backend.clusterText
window.resize(1000,700)
wait(300)
for page in (1,2):
    click('nav_'+str(page))
    window.grabWindow().save(str(folder/f'compact-{page}.png'))
assert not [m for m in messages if ('Error' in m or 'Unable' in m or 'failed' in m)], messages
print('PASS: real two-Spark inventory; all five tabs; third-node pending state; keyboard port selection; draft persistence; real network status; six screenshots.')
window.close()
engine.deleteLater()
from PySide6.QtCore import QCoreApplication,QEvent
QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
