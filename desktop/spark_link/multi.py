"""Optional three-device runtime using the existing version-matched RPC builder.

Two-device installations keep their user launcher until three devices are configured.
"""
import fcntl
import importlib
import ipaddress
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import time
from .state import CONFIG, STATE, read_json, write_json
from .topology import compile_topology

def manager_base(config):
    base=Path.home()/'.local/share/connect-dual-spark'
    chosen=Path(config.get('manager_base',base))
    if chosen not in (base,base/'pairs/worker3'): raise ValueError('Invalid per-worker manager location')
    return chosen

def manager_for(config):
    from dual_spark.fastload_manager import FastloadManager
    return FastloadManager(manager_base(config))


def model_command(binary, args, endpoints, mode='both'):
    options = {'--rpc', '--device', '-dev', '--tensor-split', '-ts', '--split-mode', '-sm', '--main-gpu', '-mg', '--n-gpu-layers', '--gpu-layers', '-ngl', '--load-mode', '-lm', '--spec-draft-device', '-devd', '--device-draft', '--mmproj-device', '-mmdev'}
    clean = []
    i = 0
    while i < len(args):
        name = args[i].split('=', 1)[0]
        if name in options:
            i += 1 if '=' in args[i] else 2
            continue
        clean.append(args[i]); i += 1
    if mode == 'first': endpoints = []
    devices = ['CUDA0'] + ['RPC'+str(i) for i in range(len(endpoints))]
    if mode == 'second':
        if not endpoints: raise RuntimeError('Второй Spark недоступен.')
        endpoints = endpoints[:1]
        devices = ['RPC0']
    command = [str(binary), *clean]
    if endpoints: command += ['--rpc', ','.join(endpoints)]
    command += ['--device', ','.join(devices), '--split-mode', 'layer' if len(devices)>1 else 'none', '--n-gpu-layers', 'all']
    if len(devices)==1:
        command += ['--spec-draft-device', devices[0]]
        if '--no-mmproj-offload' not in args: command += ['--mmproj-device', devices[0]]
    if len(devices)>1:
        q8 = any('DeepSeek-V4-Flash-Vision-Exp-UD-Q8_K_XL-' in arg for arg in args)
        split = '43,57' if len(devices)==2 and q8 else '28,36,36' if len(devices)==3 else '1,1'
        command += ['--tensor-split', split]
    if endpoints: command += ['--load-mode', 'dio']
    return command


def reachable(config):
    address, port = config['rpc'].rsplit(':',1)
    try:
        route = json.loads(subprocess.check_output(['ip','-j','route','get',address,'from',config['host_ip']], text=True))
        if not route or route[0].get('dev') != config['host_iface']: return False
        with socket.socket() as conn:
            conn.settimeout(1)
            conn.bind((config['host_ip'],0))
            conn.connect((address,int(port)))
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def setup_multi(topology, nodes):
    from dual_spark.fastload_manager import FastloadManager
    from dual_spark.operations import Installer
    from dual_spark.probe import Peer
    from dual_spark.system import Runner, remote_ssh
    from .inventory import identity_file
    plans = compile_topology(topology)
    base = Path.home()/'.local/share/connect-dual-spark'
    configs = []
    from .ssh_config import ensure_cluster_ssh
    ensure_cluster_ssh(nodes)
    for index, node in enumerate(nodes[1:]):
        subnet = 32+index*2
        host_ip, worker_ip = f'10.100.{subnet}.1', f'10.100.{subnet}.2'
        host_iface = next(i for i,a in plans['head']['interfaces'].items() if host_ip+'/24' in a)
        worker_iface = next(i for i,a in plans[node['id']]['interfaces'].items() if worker_ip+'/24' in a)
        from .admin import gui_runner,privileged
        installer = Installer(gui_runner(node))
        installer._show_rpc_logs = lambda: None
        pair_base=base if index==0 else base/'pairs'/node['id']
        if pair_base!=base:
            pair_base.mkdir(parents=True,exist_ok=True,mode=0o700)
            installer.base=pair_base
            installer.server=pair_base/'fastload/current/source/build/bin/llama-server'
            installer._llama_wrapper_path=lambda:pair_base/'llama-server-wrapper.py'
            # Each worker has its own verified binary manifest. Absolute source
            # paths/compiler details may differ while the RPC source is identical.
            stub=pair_base/'llama-server-wrapper.py'
            stub.write_text('#!/usr/bin/python3\nimport os,sys\nos.execv('+repr(str(base/'llama-server-wrapper.py'))+', ['+repr(str(base/'llama-server-wrapper.py'))+', *sys.argv[1:]])\n')
            stub.chmod(0o700)
        installer.peer = Peer(host_ip, host_iface, worker_ip, worker_iface, node['user'], node['home'], node['hostname'], 200000)
        installer.worker_exec_path = installer._existing_rpc_exec_path()
        installer.bootstrap = True
        installer.preflight()
        installer.install_studio()
        config = installer._llama_guard_config(installer.server)
        config['node_id']=node['id']
        config['manager_base']=str(pair_base)
        if not (base/'llama-server-wrapper.py').is_file():
            installer.install_llama_guard(allow_pending=True)
        check = 'command -v cmake && command -v rsync && dpkg-query -W libibverbs-dev librdmacm-dev >/dev/null 2>&1'
        try: installer._worker(check)
        except Exception:
            privileged(node,['bash','-c','apt-get update && apt-get install -y cmake build-essential rsync libibverbs-dev librdmacm-dev'])
        result = manager_for(config).ensure(config)
        if result.state not in ('current','promoted'):
            raise RuntimeError('Сборка RPC отложена: выгрузите активную модель.')
        installer.start_rpc()
        write_json(CONFIG/(node['id']+'-runtime.json'), config)
        configs.append(config)
    write_json(CONFIG/'cluster-runtime.json', {'version':1,'peers':configs})
    write_json(base/'llama-server-wrapper.json', configs[0])
    from .model_policy import install_gateway
    install_gateway('multi')
    print('Настроены три Spark. На следующем запуске используются доступные устройства.', flush=True)


def main():
    from dual_spark.fastload_manager import FastloadManager
    args = sys.argv[1:]
    base = Path.home()/'.local/share/connect-dual-spark'
    runtime = read_json(CONFIG/'cluster-runtime.json')
    if not runtime or not runtime.get('peers'):
        raise SystemExit('Нет настроенной схемы RPC. Откройте Spark Link → Кабели и Spark.')
    peers = [c for c in runtime['peers'] if reachable(c)]
    mode = 'both'
    try:
        sys.path.insert(0,str(base))
        placement = importlib.import_module('model_placement')
        policy = placement.load(base/'model-placement.json')
        entry = placement.select_entry(policy['entries'],args)
        if entry: mode = entry['mode']
    except ImportError:
        pass
    if mode == 'second':
        selected = runtime['peers'][0]
        if not reachable(selected): raise SystemExit('Выбран второй Spark, но он недоступен.')
        peers = [selected]
    informational = any(a in ('--help','-h','--version') for a in args)
    if informational or mode=='first' or not peers:
        binary = Path(runtime['peers'][0]['upstream_root'])/'build/bin/llama-server'
        if not informational:
            for i,arg in enumerate(args):
                if arg in ('-m','--model') and i+1<len(args):
                    path=Path(args[i+1])
                    files=list(path.parent.glob(path.name.split('-00001-of-')[0]+'*.gguf')) if '-00001-of-' in path.name else [path]
                    size=sum(p.stat().st_size for p in files)
                    available=int(next(l for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')).split()[1])*1024
                    if size>available*0.8: raise SystemExit('Модель не помещается на одном Spark. Подключите второй Spark.')
        command = [str(binary),*args] if informational else model_command(binary,args,[],mode='first')
    else:
        for config in peers:
            result = manager_for(config).ensure(config)
            if result.state not in ('current','promoted'): raise SystemExit('Версии RPC ещё не согласованы.')
        for selected_base in sorted({manager_base(config) for config in peers}):
            descriptor = os.open(selected_base/'fastload/.selection.lock',os.O_CREAT|os.O_RDWR,0o600)
            fcntl.flock(descriptor,fcntl.LOCK_SH)
            os.set_inheritable(descriptor,True)
        for config in peers:
            if not reachable(config) or manager_for(config).status(config)['state']!='current': raise SystemExit('Подключение изменилось. Повторите запуск модели.')
        binary = peers[0]['binary']
        endpoints = [c['rpc'] for c in peers]
        command = [str(binary),'--rpc',','.join(endpoints),'--list-devices'] if '--list-devices' in args else model_command(binary,args,endpoints,mode)
        os.environ['GGML_RPC_NO_HASH_CACHE']='1'
    for key in ('LLAMA_ARG_RPC','LLAMA_ARG_DEVICE','LLAMA_ARG_TENSOR_SPLIT','LLAMA_ARG_SPLIT_MODE','CUDA_VISIBLE_DEVICES'):
        os.environ.pop(key,None)
    print('Spark Link: '+shlex.join(command),file=sys.stderr,flush=True)
    os.execv(str(binary),command)
