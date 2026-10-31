#!/usr/bin/env python3
"""Per-user native app installation from the extracted, self-contained release."""
import argparse
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import time

VERSION = '1.4.1'
PACKAGES = ['python3-venv', 'libxcb-cursor0', 'libxkbcommon-x11-0', 'libxcb-icccm4', 'libxcb-image0',
            'libxcb-keysyms1', 'libxcb-render-util0', 'libgl1', 'libegl1', 'libopengl0', 'gnome-terminal',
            'xdg-utils', 'openssh-client', 'rsync', 'curl', 'ethtool', 'gnome-keyring', 'avahi-utils', 'lldpd']


def desktop_entry(executable, icon):
    def quote(value):
        return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$')+'"'
    return '[Desktop Entry]\nType=Application\nVersion=1.0\nName=Spark Link\nComment=Unsloth, RPC и подключение DGX Spark\nExec='+quote(executable)+'\nIcon='+str(icon)+'\nTerminal=false\nCategories=System;\nStartupNotify=true\nStartupWMClass=Spark Link\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-launch', action='store_true')
    parser.add_argument('--use-runtime', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if platform.system()!='Linux' or platform.machine() not in ('aarch64','arm64'):
        raise SystemExit('Spark Link предназначен для Ubuntu 24.04+ ARM64 на NVIDIA DGX Spark.')
    source = Path(__file__).resolve().parent
    for name in ('spark_link','dual_spark'):
        if not (source/name).is_dir(): raise SystemExit('Архив неполный: нет '+name)
    missing = []
    for package in PACKAGES:
        result = subprocess.run(['dpkg-query','-W','-f=${Status}',package], capture_output=True,text=True)
        if result.returncode or result.stdout.strip()!='install ok installed': missing.append(package)
    if missing:
        print('Нужны системные библиотеки: '+', '.join(missing),flush=True)
        subprocess.run(['sudo','apt-get','update'],check=True)
        subprocess.run(['sudo','apt-get','install','-y',*missing],check=True)
    base = Path.home()/'.local/share/spark-link'
    destination = base/'releases'/(VERSION+'-'+str(time.time_ns()))
    destination.mkdir(parents=True)
    for name in ('spark_link','dual_spark'):
        shutil.copytree(source/name,destination/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('LICENSE','CLI-LICENSE','THIRD_PARTY_NOTICES.md'):
        if (source/name).is_file(): shutil.copy2(source/name,destination/name)
    runtime = destination/'runtime'
    if args.use_runtime:
        runtime.symlink_to(Path(args.use_runtime).resolve(),target_is_directory=True)
    else:
        subprocess.run([sys.executable,'-m','venv',str(runtime)],check=True)
        wheels = source/'wheels'
        command = [str(runtime/'bin/python'),'-m','pip','install','--disable-pip-version-check']
        if wheels.is_dir(): command += ['--no-index','--find-links',str(wheels)]
        command += ['PySide6==6.8.3','SecretStorage==3.3.3']
        subprocess.run(command,check=True)
    subprocess.run([str(runtime/'bin/python'),'-c','from PySide6.QtQuick3D import QQuick3DGeometry; from PySide6.QtQml import QQmlApplicationEngine'],check=True)
    current = base/'current'
    temporary = base/('.current-'+str(os.getpid()))
    temporary.symlink_to(destination,target_is_directory=True)
    os.replace(temporary,current)
    executable = Path.home()/'.local/bin/spark-link'
    executable.parent.mkdir(parents=True,exist_ok=True)
    executable.write_text('#!/bin/sh\nset -eu\napp='+shlex.quote(str(current))+'\nexport PYTHONPATH="$app${PYTHONPATH:+:$PYTHONPATH}"\nexec "$app/runtime/bin/python" -m spark_link "$@"\n')
    executable.chmod(0o755)
    applications = Path.home()/'.local/share/applications'
    applications.mkdir(parents=True,exist_ok=True)
    icon = current/'spark_link/assets/spark-link.svg'
    entry = applications/'spark-link.desktop'
    entry.write_text(desktop_entry(executable,icon))
    entry.chmod(0o755)
    import json
    preferences=Path.home()/'.config/spark-link/preferences.json'
    try: startup=json.loads(preferences.read_text()).get('startup',True)
    except (OSError,ValueError): startup=True
    if startup:
        autostart=Path.home()/'.config/autostart/spark-link.desktop'
        autostart.parent.mkdir(parents=True,exist_ok=True)
        text=entry.read_text()
        import re
        autostart.write_text(re.sub(r'^Exec=(.*)$',r'Exec=\1 --background',text,flags=re.MULTILINE)+'X-GNOME-Autostart-enabled=true\n')
    subprocess.run(['loginctl','enable-linger',str(os.environ.get('USER') or subprocess.check_output(['id','-un'],text=True).strip())],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        desktop = Path(subprocess.check_output(['xdg-user-dir','DESKTOP'],text=True).strip())
    except (OSError,subprocess.SubprocessError): desktop=Path.home()/'Desktop'
    desktop.mkdir(parents=True,exist_ok=True)
    shortcut = desktop/'Spark Link.desktop'
    shutil.copy2(entry,shortcut)
    shortcut.chmod(0o755)
    env=os.environ.copy()
    env.setdefault('DBUS_SESSION_BUS_ADDRESS','unix:path=/run/user/'+str(os.getuid())+'/bus')
    subprocess.run(['gio','set',str(shortcut),'metadata::trusted','true'],env=env,check=False)
    legacy=desktop/'Connect-Dual-Spark-arm64.run'
    if legacy.is_file():
        terminal=applications/'connect-dual-spark-terminal.desktop'
        terminal.write_text('[Desktop Entry]\nType=Application\nName=Connect Dual Spark (терминал)\nExec=gnome-terminal -- bash "'+str(legacy).replace('"','\\"')+'"\nIcon=utilities-terminal\nTerminal=false\nCategories=System;\n')
        terminal.chmod(0o755)
        terminal_shortcut=desktop/'Connect Dual Spark.desktop'
        shutil.copy2(terminal,terminal_shortcut)
        subprocess.run(['gio','set',str(terminal_shortcut),'metadata::trusted','true'],env=env,check=False)
    if shutil.which('update-desktop-database'):
        subprocess.run(['update-desktop-database',str(applications)],check=False)
    guard=Path.home()/'.local/share/connect-dual-spark/llama-server-wrapper.py'
    if guard.is_file():
        env=os.environ.copy(); env['PYTHONPATH']=str(current)
        subprocess.run([str(runtime/'bin/python'),'-c','from spark_link.model_policy import install_gateway; install_gateway()'],env=env,check=True)
    print('\nSpark Link установлен. Откройте меню приложений или ярлык «Spark Link» на рабочем столе.\n'+str(executable),flush=True)
    if not args.no_launch and (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        subprocess.Popen([str(executable)],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

if __name__=='__main__': main()
