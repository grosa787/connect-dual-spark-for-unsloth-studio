"""Bounded read-only inventory. Never runs model loads or privileged commands."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from .topology import INTERFACES, safe_target

PROBE = r'''
import json, os, pathlib, platform, shutil, socket, subprocess
def run(args):
    try:
        return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=6).stdout.strip()
    except Exception:
        return ''
mem = {}
for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
    key, val = line.split(':', 1)
    mem[key] = int(val.strip().split()[0])
interfaces = {}
addresses = json.loads(run(['ip', '-j', '-4', 'addr']) or '[]')
for item in addresses:
    name = item['ifname']
    driver = run(['ethtool', '-i', name]) if 'np' in name else ''
    if 'mlx5_core' not in driver:
        continue
    base = pathlib.Path('/sys/class/net') / name
    def read(attr, default='0'):
        try: return (base / attr).read_text().strip()
        except OSError: return default
    interfaces[name] = {'carrier': read('carrier') == '1', 'speed': max(0, int(read('speed', '0'))),
        'addresses': [x['local'] for x in item.get('addr_info', []) if x['family'] == 'inet']}
studio = pathlib.Path.home() / '.unsloth/studio/unsloth_studio/bin/unsloth'
disk = shutil.disk_usage(pathlib.Path.home())
print(json.dumps({'hostname': socket.gethostname(), 'user': os.environ.get('USER', ''), 'home': str(pathlib.Path.home()),
    'arch': platform.machine(), 'gpu': run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader']),
    'memory_total': mem['MemTotal'], 'memory_available': mem['MemAvailable'], 'memory_used': mem['MemTotal']-mem['MemAvailable'],
    'disk_available': disk.free, 'interfaces': interfaces, 'model_active': bool(run(['pgrep', '-x', 'llama-server'])),
    'studio_installed': studio.is_file(), 'version': run([str(studio), '--version']) if studio.is_file() else '',
    'studio_service': run(['systemctl', '--user', 'is-active', 'connect-dual-spark-studio.service']),
    'rpc_service': run(['systemctl', 'is-active', 'connect-dual-spark-rpc.service'])}))
'''


def identity_file(target='10.100.32.2'):
    try:
        output = subprocess.check_output(['ssh', '-G', safe_target(target)], text=True, stderr=subprocess.DEVNULL)
        for line in output.splitlines():
            if line.startswith('identityfile '):
                path = Path(line.split(' ', 1)[1]).expanduser()
                if path.is_file():
                    return str(path)
    except (OSError, subprocess.SubprocessError):
        pass
    return identity_file() if target != '10.100.32.2' else ''


def ssh_argv(target, tty=False, identity=None):
    command = ['ssh', '-tt' if tty else '-T', '-o', 'ConnectTimeout=5',
               '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
               '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new']
    identity = identity or identity_file(target)
    if identity:
        command += ['-i', identity]
    return command + [safe_target(target)]


def probe(node):
    if not node.get('local') and not node.get('ssh'):
        return {**node, 'online': False, 'error': 'Укажите SSH-имя или подключите Spark через NVIDIA Sync.'}
    command = [sys.executable, '-c', PROBE] if node.get('local') else ssh_argv(node['ssh'], identity=node.get('identity')) + ['python3 -c ' + shlex.quote(PROBE)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=28)
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[-350:] or 'Spark не ответил на диагностику.')
        data = json.loads(result.stdout)
        if 'GB10' not in data['gpu']:
            raise RuntimeError('На устройстве не обнаружена GPU GB10.')
        return {**node, **data, 'online': True, 'error': ''}
    except Exception as exc:
        return {**node, 'online': False, 'error': str(exc)}


def scan(topology):
    with ThreadPoolExecutor(max_workers=3) as pool:
        return list(pool.map(probe, topology['nodes']))


def discover_worker():
    guard = Path.home() / '.local/share/connect-dual-spark/llama-server-wrapper.json'
    try:
        config = json.loads(guard.read_text())
        address = config['rpc'].split(':')[0]
        node = {'id': 'worker2', 'name': 'Второй Spark', 'ssh': config['worker_user'] + '@' + address, 'local': False}
        data = probe(node)
        if data['online']:
            node['identity'] = identity_file(node['ssh'])
            node['ssh'] = config['worker_user'] + '@' + data['hostname'] + '.local'
            return node
    except (OSError, ValueError, KeyError):
        pass
    # Only entries explicitly configured by NVIDIA Sync/user, never a subnet scan.
    path = Path.home() / '.ssh/config'
    try:
        candidates = re.findall(r'^Host\s+([^*?\s]+)\s*$', path.read_text(), re.MULTILINE)
    except OSError:
        candidates = []
    local_name = os.uname().nodename
    for target in candidates[:12]:
        node = {'id': 'worker2', 'name': 'Второй Spark', 'ssh': target, 'local': False}
        data = probe(node)
        if data.get('online') and data['hostname'] != local_name:
            node['identity'] = identity_file(target)
            node['ssh'] = data['user'] + '@' + data['hostname'] + '.local'
            return node
    return None
