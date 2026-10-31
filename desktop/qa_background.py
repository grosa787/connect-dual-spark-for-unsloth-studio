"""Installed native main-loop smoke: hidden start, IPC reopen, hide, independent RPC."""
import os
from pathlib import Path
import sys
import tempfile
from urllib.request import urlopen

scratch=tempfile.TemporaryDirectory(prefix='spark-link-background-qa-')
os.environ['XDG_STATE_HOME']=scratch.name
sys.path.insert(0,str(Path.home()/'.local/share/spark-link/current'))
from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication
from spark_link import main

original=QApplication.exec
errors=[]; measurements={}; sockets=[]
def rss():
    return int(next(line for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('VmRSS:')).split()[1])/1024
def guarded(function):
    def call():
        try: function()
        except Exception as exc:
            errors.append(exc); QApplication.instance().quit()
    return call
def window(): return next(w for w in QApplication.topLevelWindows() if w.title()=='Spark Link')
def hidden():
    assert not window().isVisible()
    measurements['hidden_start_mib']=round(rss(),1)
    client=QLocalSocket(); sockets.append(client)
    client.connectToServer('spark-link-'+str(os.getuid()))
def reopened():
    assert window().isVisible(), 'IPC failed to reopen native window'
    measurements['visible_mib']=round(rss(),1)
    window().hide()
def finish():
    assert not window().isVisible()
    measurements['hidden_again_mib']=round(rss(),1)
    with urlopen('http://127.0.0.1:8888/api/health',timeout=3) as response: assert response.status==200
    import socket
    with socket.create_connection(('10.100.32.2',50053),timeout=3): pass
    print('PASS: installed native hidden startup, IPC reopening, hide, Studio health and independent RPC; RSS MiB:',measurements,flush=True)
    window().setProperty('allowExit',True)
    QApplication.instance().quit()
def loop(self):
    QTimer.singleShot(2500,guarded(hidden))
    QTimer.singleShot(5000,guarded(reopened))
    QTimer.singleShot(8000,guarded(finish))
    return original()
QApplication.exec=loop
sys.argv=['spark-link','--background']
result=main.main()
if errors: raise errors[0]
raise SystemExit(result)
