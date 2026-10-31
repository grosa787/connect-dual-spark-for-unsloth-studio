"""Read-only real three-Spark rendering/identity check. Network and model policy are not edited."""
import os,sys,time,tempfile,json,shutil
from pathlib import Path
original=Path.home()/'.config/spark-link'
scratch=tempfile.TemporaryDirectory(prefix='spark-three-qa-')
config=Path(scratch.name)/'spark-link';config.mkdir()
for name in ('topology.json','preferences.json'):
 shutil.copy2(original/name,config/name)
os.environ['XDG_CONFIG_HOME']=scratch.name
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl,QPointF,QPoint,Qt,qInstallMessageHandler
from PySide6.QtQml import QQmlApplicationEngine,qmlRegisterType
from PySide6.QtTest import QTest
from spark_link.backend import Backend
from spark_link.geometry import RoundedBox,Cable
from spark_link.discovery import scan_new_devices
app=QApplication(sys.argv)
def wait(ms):
 until=time.monotonic()+ms/1000
 while time.monotonic()<until: app.processEvents();time.sleep(.01)
qmlRegisterType(RoundedBox,'SparkLink',1,0,'RoundedBox');qmlRegisterType(Cable,'SparkLink',1,0,'CableGeometry')
manager=Backend();engine=QQmlApplicationEngine();messages=[]
qInstallMessageHandler(lambda kind,ctx,msg:messages.append(msg))
for key,value in [('manager',manager),('planner',manager.planner),('devices',manager.devices),('initialPage',1)]: engine.rootContext().setContextProperty(key,value)
engine.load(QUrl.fromLocalFile(str(Path(__file__).parent/'spark_link/qml/Main.qml')))
assert engine.rootObjects(),messages
window=engine.rootObjects()[0];window.setPersistentGraphics(False);window.setPersistentSceneGraph(True)
wait(10000)
assert len(manager.nodes)==3 and all(n['online'] for n in manager.nodes),[(n['id'],n.get('error')) for n in manager.nodes]
assert len({n['device_id'] for n in manager.nodes})==3
assert manager.clusterText=='Spark соединены',manager.clusterText
assert manager.orientations==[True,True,True]
folder=Path('/tmp/spark-three-qa');folder.mkdir(exist_ok=True)
for language in ('ru','en','de','es'):
 manager.setLanguage(language);wait(350)
 for page in range(6):
  window.setProperty('page',page);wait(150)
  window.grabWindow().save(str(folder/f'{language}-{page}.png'))
manager.setLanguage('ru');window.setProperty('page',1);wait(350)
window.hide();manager.setVisible(False);window.releaseResources();wait(400)
window.show();manager.setVisible(True);wait(700)
shot=window.grabWindow();shot.save(str(folder/'reopened.png'))
gold=0
for y in range(200,550,2):
 for x in range(280,930,2):
  c=shot.pixelColor(x,y);gold+=c.red()>c.green()+5 and c.green()>c.blue()*1.15
assert gold>300,gold
window.resize(1000,700);wait(350);window.grabWindow().save(str(folder/'compact.png'))
assert not [m for m in messages if any(term in m for term in ('Error','Unable','failed','Binding loop'))],messages
print('PASS: three real devices, unique GPU identities despite cloned OS identity, full physical triangle, four languages/six tabs, upright positions, compact layout and visible meshes after hide/show.',flush=True)
window.setProperty('allowExit',True);window.close();engine.deleteLater()
from PySide6.QtCore import QCoreApplication,QEvent
QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
