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
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtTest import QTest
from spark_link.backend import Backend
from spark_link.geometry import RoundedBox, Cable

app=QApplication(sys.argv)
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
engine.rootContext().setContextProperty('planner',backend.planner)
engine.rootContext().setContextProperty('devices',backend.devices)
engine.rootContext().setContextProperty('initialPage',0)
engine.load(QUrl.fromLocalFile(str(Path(__file__).parent/'spark_link/qml/Main.qml')))
print('QML loaded',flush=True)
assert engine.rootObjects(), messages
window=engine.rootObjects()[0]
window.setPersistentGraphics(False)
window.setPersistentSceneGraph(True)
wait(9000)
print('Inventory waited',flush=True)
assert len(backend.nodes)==2 and all(n['online'] for n in backend.nodes), backend.nodes
folder=Path('/tmp/spark-link-qa'); folder.mkdir(exist_ok=True)
def click(name):
    item=find(name)
    assert item is not None, name
    point=item.mapToScene(QPointF(item.width()/2,item.height()/2))
    QTest.mouseClick(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(int(point.x()),int(point.y())))
    QTest.mouseMove(window,QPoint(260,40))
    wait(350)
def find(name):
    pending=[window.contentItem()]
    while pending:
        item=pending.pop()
        if item.objectName()==name: return item
        pending.extend(item.childItems())
    return None
def assert_chassis_rendered():
    scene=find('cableScene')
    origin=scene.mapToScene(QPointF(0,0))
    shot=window.grabWindow()
    gold=0
    for y in range(int(origin.y()+60),int(origin.y()+scene.height()-50),2):
        for x in range(int(origin.x()+10),int(origin.x()+scene.width()-10),2):
            c=shot.pixelColor(x,y)
            gold+=c.red()>c.green()+5 and c.green()>c.blue()*1.15
    assert gold>300, f'Chassis vanished from rendered scene: {gold} gold samples'
for page in range(6):
    click('nav_'+str(page))
    assert window.property('page')==page
    assert window.grabWindow().save(str(folder/f'page-{page}.png'))
    print('Rendered page',page,flush=True)
click('nav_1')
click('languageSelector')
window.grabWindow().save(str(folder/'language-popup.png'))
QTest.keyClick(window,Qt.Key.Key_Escape); wait(200)
scene=find('cableScene')
assert scene is not None
for name,yaw,pitch in (('cameraFront',180,18),('cameraTop',0,85),('cameraRear',0,18),('cameraReset',18,25)):
    click(name)
    assert scene.property('yaw')==yaw and scene.property('pitch')==pitch
    assert window.grabWindow().save(str(folder/(name+'.png')))
orientation=find('orientation_0')
assert orientation is not None
orientation.forceActiveFocus(); QTest.keyClick(window,Qt.Key.Key_Down); wait(500)
assert backend.orientations[0] is True
window.grabWindow().save(str(folder/'upright-mixed.png'))
backend.setOrientation(1,True); wait(500)
assert backend.orientations==[True,True]
window.grabWindow().save(str(folder/'upright-both.png'))
for language in ('en','de','es','ru'):
    backend.setLanguage(language); wait(250)
    for page in range(6):
        click('nav_'+str(page))
        window.grabWindow().save(str(folder/f'{language}-{page}.png'))
    assert backend.orientations==[True,True]
    from spark_link.preferences import ViewPreferences
    restored=ViewPreferences()
    assert restored.language==language and restored.vertical('head') and restored.vertical('worker2')
click('nav_1')
click('threeNodes')
assert len(backend.topology['nodes'])==3
assert not backend.nodes[2]['online']
click('cameraFront'); click('cameraReset')
assert scene.property('yaw')==0 and scene.property('pitch')==32
from spark_link.topology import validate_topology
validate_topology(backend._topology,require_targets=False)
click('selectCable_2')
assert window.property('activeCable')==2
click('selectCable_0')
combo=find('cableA_0'); combo.forceActiveFocus()
QTest.keyClick(window,Qt.Key.Key_Down); wait(300)
assert backend.topology['cables'][0]['a_port']==1
assert backend.topology['cables'][1]['a_port']==0
validate_topology(backend._topology,require_targets=False)
backend.setPort(0,'a',0); wait(300)
window.grabWindow().save(str(folder/'three-nodes.png'))
backend.setOrientation(2,True); wait(400)
for language in ('ru','en','de','es'):
    backend.setLanguage(language); wait(300)
    window.grabWindow().save(str(folder/f'triangle-{language}.png'))
window.resize(1000,700); wait(400)
window.grabWindow().save(str(folder/'triangle-compact.png'))
window.resize(1240,820); backend.setLanguage('ru'); wait(300)
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
known_macs={v['mac'].lower() for n in backend._nodes if n.get('online') for v in n.get('interfaces',{}).values() if v.get('mac')}
assert not any(c.get('mac','').lower() in known_macs for c in backend.devices.candidates), 'Existing worker offered as new'
assert_chassis_rendered()
window.hide(); backend.setVisible(False); window.releaseResources(); wait(600)
assert backend.timer.interval()==60000
window.show(); backend.setVisible(True); wait(500)
assert backend.timer.interval()==15000
window.resize(1000,700)
wait(300)
for page in (1,2,5):
    click('nav_'+str(page))
    if page==1: assert_chassis_rendered()
    window.grabWindow().save(str(folder/f'compact-{page}.png'))
assert not [m for m in messages if ('Error' in m or 'Unable' in m or 'failed' in m)], messages
print('PASS: two-Spark inventory; six tabs; upright/mixed chassis and cables; four languages; persisted view preferences; pending third; port draft; hidden-window resource release; compact layouts.')
window.close()
engine.deleteLater()
from PySide6.QtCore import QCoreApplication,QEvent
QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
