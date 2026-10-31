"""Local, durable update rollback and offline service reconciliation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from .state import CONFIG,STATE,read_json,write_json

PENDING=CONFIG/'update-pending.json'

def flush_tree(path):
    if path.is_file():
        with path.open('rb') as stream: os.fsync(stream.fileno())
        return
    for directory,dirs,files in os.walk(path):
        for filename in files:
            target=Path(directory)/filename
            if target.is_file() and not target.is_symlink():
                with target.open('rb') as stream: os.fsync(stream.fileno())
        descriptor=os.open(directory,os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)

def runtime_roots():
    home=Path.home()
    studio=home/'.unsloth/studio'
    return [studio/'unsloth_studio',home/'.unsloth/llama.cpp',studio/'studio.db',studio/'auth/auth.db',studio/'rag/rag.db']

def make_snapshot(roots=None,base=None,pending=None):
    roots=roots or runtime_roots()
    base=base or STATE/'update-backups'
    pending=pending or PENDING
    directory=base/str(time.time_ns())
    directory.mkdir(parents=True,mode=0o700)
    records=[]
    print('Сохраняем работающую версию перед обновлением…',flush=True)
    for index,source in enumerate(roots):
        source=Path(source)
        if not source.exists(): continue
        if source.is_symlink(): raise RuntimeError('Cannot snapshot an externally linked runtime')
        target=directory/str(index)
        if source.is_dir(): shutil.copytree(source,target,symlinks=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        else: shutil.copy2(source,target)
        flush_tree(target)
        records.append({'source':str(source),'backup':str(target),'directory':source.is_dir()})
    record={'version':1,'snapshot':str(directory),'roots':records,'created_at':time.time()}
    write_json(pending,record)
    return record

def restore_snapshot(record=None,allowed_roots=None,base=None,pending=None):
    pending=pending or PENDING
    record=record or read_json(pending)
    if not record: return False
    allowed={str(Path(p)) for p in (allowed_roots or runtime_roots())}
    base=(base or STATE/'update-backups').resolve()
    snapshot=Path(record['snapshot']).resolve()
    if not snapshot.is_relative_to(base) or snapshot==base or not snapshot.is_dir(): raise RuntimeError('Invalid update snapshot location')
    print('Восстанавливаем последнюю рабочую версию после прерванного обновления…',flush=True)
    for entry in record['roots']:
        source=Path(entry['source']); backup=Path(entry['backup'])
        if str(source) not in allowed or not backup.resolve().is_relative_to(snapshot): raise RuntimeError('Invalid update restoration path')
        temporary=source.with_name(source.name+'.restore-'+str(time.time_ns()))
        if entry['directory']: shutil.copytree(backup,temporary,symlinks=True)
        else: shutil.copy2(backup,temporary)
        flush_tree(temporary)
        if source.exists() or source.is_symlink():
            os.replace(source,source.with_name(source.name+'.before-rollback-'+str(time.time_ns())))
        os.replace(temporary,source)
        # Preserve a newer SQLite journal instead of replaying it onto the restored DB.
        if source.suffix=='.db':
            for suffix in ('-wal','-shm'):
                journal=Path(str(source)+suffix)
                if journal.exists(): os.replace(journal,Path(str(journal)+'.before-rollback-'+str(time.time_ns())))
    write_json(pending,None)
    return True

def reconcile_guard_routes():
    from .topology import INTERFACES
    address_data=json.loads(subprocess.check_output(['ip','-j','-4','addr'],text=True))
    interfaces={item['ifname']:{a['local'] for a in item.get('addr_info',[])} for item in address_data if item['ifname'] in INTERFACES}
    paths=[Path.home()/'.local/share/connect-dual-spark/llama-server-wrapper.json']
    runtime=read_json(CONFIG/'cluster-runtime.json')
    if runtime:
        configs=runtime.get('peers',[])
    else: configs=[]
    standalone=[read_json(path) for path in paths]
    changed=False
    for config in [c for c in standalone+configs if c]:
        source=config.get('host_ip')
        device=next((name for name,addresses in interfaces.items() if source in addresses),None)
        if not device: continue
        target=config.get('rpc','').split(':')[0]
        try: routes=json.loads(subprocess.check_output(['ip','-j','route','get',target,'from',source],text=True,stderr=subprocess.DEVNULL))
        except subprocess.SubprocessError: continue
        if routes and routes[0].get('dev')==device and config.get('host_iface')!=device:
            config['host_iface']=device
            changed=True
    if changed:
        if standalone[0]: write_json(paths[0],standalone[0])
        if runtime: write_json(CONFIG/'cluster-runtime.json',runtime)
    return changed

def recover(topology,interactive=True):
    from .inventory import scan,node_ssh
    from .credentials import Vault,credential_id,VaultUnavailable
    from .admin import privileged
    from .jobs import STUDIO,SERVICE,GUARD
    nodes=scan(topology)
    active=any(node.get('model_active') for node in nodes)
    if read_json(PENDING):
        if active: raise RuntimeError('An interrupted update needs restoration after unloading active models')
        subprocess.run(['systemctl','--user','stop',SERVICE],check=False)
        restore_snapshot()
    reconcile_guard_routes()
    if not active and GUARD.with_name('fastload_manager.py').is_file():
        result=subprocess.run(['/usr/bin/python3',str(GUARD.with_name('fastload_manager.py')),'ensure','--config',str(GUARD)],check=False)
        if result.returncode: print('Согласование RPC отложено до возвращения всех нужных устройств.',flush=True)
    for node in nodes:
        if not node.get('online'):
            print(node['name']+': устройство выключено или недоступно; настройки сохранены.',flush=True)
            continue
        if node.get('local'):
            if node.get('studio_installed') and node.get('studio_service')!='active':
                subprocess.run(['systemctl','--user','start',SERVICE],check=True)
        elif node.get('rpc_service')!='active' and not active:
            if not interactive:
                try: password=Vault().get(credential_id(node),unlock=False)
                except VaultUnavailable: password=None
                if not password:
                    print(node['name']+': требуется разрешение администратора для восстановления RPC.',flush=True)
                    continue
            privileged(node,['systemctl','start','connect-dual-spark-rpc.service'])
    print('Локальные настройки и доступные службы проверены. Интернет для этого не требуется.',flush=True)
