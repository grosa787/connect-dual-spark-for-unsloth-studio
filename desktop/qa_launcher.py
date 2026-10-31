"""Run under xvfb-run after release installation; activates the real menu entry."""
import os
from pathlib import Path
import signal
import subprocess
import time

lock=Path.home()/'.local/state/spark-link/window.lock'
if lock.exists():
    previous=int(lock.read_text().splitlines()[0])
    assert not Path(f'/proc/{previous}/cmdline').exists(), 'Close the existing Spark Link window before launcher QA.'
entry=Path.home()/'.local/share/applications/spark-link.desktop'
subprocess.run(['desktop-file-validate',str(entry)],check=True)
subprocess.run(['gio','launch',str(entry)],check=True)
pid=None
try:
    for _ in range(100):
        if lock.exists():
            candidate=int(lock.read_text().splitlines()[0])
            try: command=Path(f'/proc/{candidate}/cmdline').read_bytes()
            except FileNotFoundError: command=b''
            if b'spark_link' in command and b'/spark-link/' in command:
                pid=candidate
                tree=subprocess.check_output(['xwininfo','-root','-tree'],text=True)
                if 'Spark Link' in tree: break
        time.sleep(0.2)
    else: raise AssertionError('Desktop launcher did not create a Spark Link window.')
    command=Path(f'/proc/{pid}/cmdline').read_bytes()
    assert b'spark_link' in command and b'/spark-link/' in command, command
    print('PASS: desktop entry validated and launched the independent installed native application.')
finally:
    if pid and Path(f'/proc/{pid}/cmdline').exists():
        command=Path(f'/proc/{pid}/cmdline').read_bytes()
        if b'spark_link' in command: os.kill(pid,signal.SIGTERM)
