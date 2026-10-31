"""Bounded real-HF metadata and native-dialog checks; no model launch or network mutation."""
import os
import tempfile
import time
from pathlib import Path
import sys
scratch=tempfile.TemporaryDirectory(prefix='spark-link-planner-qa-')
os.environ['XDG_CONFIG_HOME']=scratch.name
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl,QObject,QMetaObject,Q_ARG,Qt
from PySide6.QtQml import QQmlApplicationEngine,qmlRegisterType
from spark_link.backend import Backend
from spark_link.geometry import RoundedBox,Cable

app=QApplication(sys.argv)
def wait(seconds):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        app.processEvents(); time.sleep(0.01)
qmlRegisterType(RoundedBox,'SparkLink',1,0,'RoundedBox'); qmlRegisterType(Cable,'SparkLink',1,0,'CableGeometry')
manager=Backend(); engine=QQmlApplicationEngine()
for key,value in [('manager',manager),('planner',manager.planner),('devices',manager.devices),('initialPage',5)]: engine.rootContext().setContextProperty(key,value)
engine.load(QUrl.fromLocalFile(str(Path(__file__).parent/'spark_link/qml/Main.qml')))
assert engine.rootObjects()
window=engine.rootObjects()[0]
wait(8)
assert all(n.get('online') for n in manager.nodes)
planner=manager.planner
planner.analyze('https://huggingface.co/unsloth/Qwen3-0.6B-GGUF')
until=time.monotonic()+90
while planner.busy and time.monotonic()<until: wait(.1)
assert not planner.busy and planner.analysis.get('max_context'),planner.message
assert planner.result.get('fits') and planner.cacheKnown,planner.message
planner.autoAllocate()
assert planner.percentages[0]<planner.percentages[1]
planner.setPercentage(0,'40'); planner.setPercentage(1,'60')
assert planner.result['fits'] and planner.percentages==[40,60]
planner.setField('units','gib')
weights=planner.result['weights_gib']
planner.setPercentage(0,str(weights*.5)); planner.setPercentage(1,str(weights*.5))
assert all(abs(p-50)<.001 for p in planner.percentages) and planner.result['fits'], (planner.percentages,planner.message)
folder=Path('/tmp/spark-link-qa'); folder.mkdir(exist_ok=True)
for language in ('ru','en','de','es'):
    manager.setLanguage(language); wait(.3)
    assert planner.result['fits'] and abs(sum(planner.percentages)-100)<.001
    window.grabWindow().save(str(folder/f'planner-filled-{language}.png'))
manager.devices.timer.stop(); manager.devices.link_timer.stop()
manager.devices._candidates=[{'id':'fixture','address':'192.0.2.7','fingerprint':'SHA256:ExamplePublicHostKeyFingerprintForLocalUIFixture','authorized':False,'device':{}}]
manager.devices.changed.emit()
window.setProperty('page',0); wait(.3)
assert QMetaObject.invokeMethod(window,'openOnboard',Q_ARG('QVariant',0))
wait(.3)
dialog=window.findChild(QObject,'onboardDialog'); assert dialog and dialog.property('visible')
def visual(name):
    queue=[window.contentItem()]
    while queue:
        item=queue.pop()
        if item.objectName()==name: return item
        queue.extend(item.childItems())
password=visual('newSparkPassword'); assert password is not None
password.setProperty('text','dummy-ui-password')
for language in ('ru','en','de','es'):
    manager.setLanguage(language); wait(.3)
    window.grabWindow().save(str(folder/f'onboarding-{language}.png'))
dialog.setProperty('visible',False); wait(.2)
assert password.property('text')==''
print('PASS: real bounded HF metadata; declared maximum context; cache estimate; auto and manual percent/GiB allocation; four populated layouts; four masked credential dialogs; no saved model policy or device.')
window.setProperty('allowExit',True); window.close()
engine.deleteLater()
from PySide6.QtCore import QCoreApplication,QEvent
QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
