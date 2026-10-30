"""Auditable management jobs, usable independently of the graphical application."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from .inventory import scan, ssh_argv, identity_file
from .state import CONFIG, STATE, read_json, write_json
from .topology import compile_topology, validate_topology

GUARD = Path.home() / '.local/share/connect-dual-spark/llama-server-wrapper.json'
STUDIO = Path.home() / '.unsloth/studio/unsloth_studio/bin/unsloth'
SERVICE = 'connect-dual-spark-studio.service'


def run(command, **kwargs):
    print('Выполняется: ' + shlex.join([str(x) for x in command]), flush=True)
    return subprocess.run([str(x) for x in command], check=True, **kwargs)


def assert_idle(nodes):
    if any(not n.get('online') for n in nodes):
        raise RuntimeError('Не все Spark доступны. Сначала проверьте SSH и выбранные порты.')
    if any(n.get('model_active') for n in nodes):
        raise RuntimeError('Сначала выгрузите модели в Studio. Сейчас выполняется llama-server.')


def plan_matches(node, plan):
    interfaces = node.get('interfaces', {})
    for iface, addresses in plan['interfaces'].items():
        expected = {a.split('/')[0] for a in addresses}
        actual = {a for a in interfaces.get(iface, {}).get('addresses', []) if a.startswith('10.100.')}
        if expected != actual:
            return False
    return True


def remote_output(node, command):
    return subprocess.check_output(ssh_argv(node['ssh'], identity=node.get('identity')) + [command], text=True, timeout=20).strip()


def verify_links(topology, nodes, plans):
    lookup = {node['id']: node for node in nodes}
    for cable in topology['cables']:
        first, second = cable['a'], cable['b']
        left = plans[first]['interfaces']
        right = plans[second]['interfaces']
        iface = 'enp1s0f'+str(cable['a_port'])+'np'+str(cable['a_port'])
        other_iface = 'enp1s0f'+str(cable['b_port'])+'np'+str(cable['b_port'])
        source, target = left[iface][0].split('/')[0], right[other_iface][0].split('/')[0]
        for node, local_ip, remote_ip, device in [(lookup[first],source,target,iface),(lookup[second],target,source,other_iface)]:
            route_command = ['ip','-j','route','get',remote_ip,'from',local_ip]
            text = subprocess.check_output(route_command,text=True,timeout=5) if node.get('local') else remote_output(node,shlex.join(route_command))
            route = json.loads(text)
            if not route or route[0].get('dev') != device:
                raise RuntimeError(f"{node['name']}: маршрут к соседу идёт через другой интерфейс.")
            ping = ['ping','-c','2','-W','2','-I',local_ip,remote_ip]
            run(ping if node.get('local') else ssh_argv(node['ssh'],identity=node.get('identity'))+[shlex.join(ping)], stdout=subprocess.DEVNULL, timeout=12)


def apply_topology(topology):
    topology = validate_topology(topology)
    plans = compile_topology(topology)
    nodes = scan(topology)
    assert_idle(nodes)
    for node in nodes:
        for iface, addresses in plans[node['id']]['interfaces'].items():
            if addresses and not node['interfaces'].get(iface, {}).get('carrier'):
                raise RuntimeError(f"{node['name']}: в выбранном порту нет физического линка. Переставьте кабель, затем примените схему.")
    applied = []
    old_guard = GUARD.read_bytes() if GUARD.is_file() else None
    helper = Path(__file__).with_name('network_helper.py')
    try:
        # Management SSH is used here, so relocating QSFP does not disconnect the control channel.
        for node in sorted(nodes, key=lambda n: n.get('local', False)):
            plan = plans[node['id']]
            if plan_matches(node, plan):
                print(f"{node['name']}: адреса уже соответствуют схеме.", flush=True)
                continue
            with tempfile.TemporaryDirectory(prefix='spark-link-net-') as temp:
                path = Path(temp) / 'plan.json'
                write_json(path, plan)
                if node.get('local'):
                    result = run(['sudo', '/usr/bin/python3', helper, '--plan', path], stdout=subprocess.PIPE, text=True)
                    location = str(helper)
                else:
                    remote = remote_output(node, 'mktemp -d /tmp/spark-link-net.XXXXXX')
                    if not re.fullmatch(r'/tmp/spark-link-net\.[A-Za-z0-9]+', remote):
                        raise RuntimeError('Некорректный временный путь второго Spark.')
                    scp = ['scp', '-o', 'BatchMode=yes']
                    identity = node.get('identity') or identity_file(node['ssh'])
                    if identity: scp += ['-i', identity]
                    run(scp + [helper, path, node['ssh'] + ':' + remote + '/'])
                    location = remote + '/network_helper.py'
                    command = 'sudo /usr/bin/python3 ' + shlex.quote(location) + ' --plan ' + shlex.quote(remote + '/plan.json')
                    result = run(ssh_argv(node['ssh'], tty=True, identity=node.get('identity')) + [command], stdout=subprocess.PIPE, text=True)
                print(result.stdout, flush=True)
                receipts = [json.loads(line) for line in result.stdout.splitlines() if line.strip().startswith('{')]
                if not receipts: raise RuntimeError('Сетевая операция не вернула подтверждение.')
                applied.append((node, location, receipts[-1]['backup']))
        # Check actual direct routes, not just successful netplan commands.
        after = scan(topology)
        if not all(plan_matches(node, plans[node['id']]) for node in after):
            raise RuntimeError('Итоговые IP-адреса не совпадают со схемой.')
        verify_links(topology, after, plans)
        from .ssh_config import ensure_cluster_ssh
        ensure_cluster_ssh(after)
        head = plans['head']['interfaces']
        if len(nodes) == 2 and GUARD.is_file():
            config = read_json(GUARD)
            iface = next(i for i, a in head.items() if '10.100.32.1/24' in a)
            config['host_iface'] = iface
            config['host_ip'] = '10.100.32.1'
            write_json(GUARD, config)
            runtime = read_json(CONFIG / 'cluster-runtime.json')
            if runtime:
                runtime['peers'] = [config]
                write_json(CONFIG / 'cluster-runtime.json', runtime)
        elif len(nodes) == 3:
            from .multi import setup_multi
            setup_multi(topology, after)
        write_json(CONFIG / 'topology.json', topology)
        write_json(CONFIG / 'applied-topology.json', topology)
        print('Схема применена. Адреса проверены на всех Spark.', flush=True)
    except BaseException:
        if old_guard is not None:
            GUARD.write_bytes(old_guard)
        for node, location, backup in reversed(applied):
            print(f"Откат сети: {node['name']}", flush=True)
            try:
                if node.get('local'):
                    run(['sudo', '/usr/bin/python3', location, '--rollback', backup])
                else:
                    run(ssh_argv(node['ssh'], tty=True) + [shlex.join(['sudo', '/usr/bin/python3', location, '--rollback', backup])])
            except Exception as exc:
                print('Не удалось автоматически откатить сеть: ' + str(exc), flush=True)
        raise


def update_studio():
    topology = read_json(CONFIG / 'topology.json')
    if topology:
        assert_idle(scan(validate_topology(topology)))
    elif subprocess.run(['pgrep', '-x', 'llama-server'], stdout=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError('Выгрузите активную модель перед обновлением.')
    if not STUDIO.is_file():
        raise RuntimeError('Studio ещё не установлена. Откройте вкладку «Установка».')
    manager = GUARD.with_name('fastload_manager.py')
    backup = STATE / ('update-backup-' + time.strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True, exist_ok=False)
    for name in ('llama-server-wrapper.py', 'llama-server-wrapper.json', 'model_placement.py'):
        path = GUARD.with_name(name)
        if path.is_file(): shutil.copy2(path, backup / name)
    active = subprocess.run(['systemctl', '--user', 'is-active', '--quiet', SERVICE]).returncode == 0
    watcher = 'connect-dual-spark-refresh.path'
    watching = subprocess.run(['systemctl', '--user', 'is-active', '--quiet', watcher]).returncode == 0
    try:
        if watching: run(['systemctl', '--user', 'stop', watcher])
        if active: run(['systemctl', '--user', 'stop', SERVICE])
        run([STUDIO, 'studio', 'update'])
        if manager.is_file():
            run([sys.executable, manager, 'refresh', '--config', GUARD])
            run([sys.executable, manager, 'status', '--config', GUARD])
        print('Unsloth и версия RPC согласованы. Пользовательская оболочка сохранена.', flush=True)
    finally:
        if watching: run(['systemctl', '--user', 'start', watcher])
        if active: run(['systemctl', '--user', 'start', SERVICE])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['install', 'update', 'update-app', 'refresh', 'check', 'rpc-logs', 'start-rpc', 'topology', 'start-studio'])
    parser.add_argument('--plan')
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    try:
        if args.action == 'rpc-logs':
            topology=validate_topology(read_json(CONFIG/'topology.json'))
            run(['journalctl','--user','-u',SERVICE,'-n','50','--no-pager','-o','cat'])
            for node in topology['nodes'][1:]:
                print('\n'+node['name']+' — RPC:',flush=True)
                print(remote_output(node,'journalctl -u connect-dual-spark-rpc.service -n 70 --no-pager -o cat'),flush=True)
        elif args.action == 'update-app':
            with tempfile.TemporaryDirectory(prefix='spark-link-update-') as temporary:
                script = Path(temporary)/'install-desktop.sh'
                run(['curl','-fL','--retry','3','https://raw.githubusercontent.com/grosa787/connect-dual-spark-for-unsloth-studio/main/desktop/install-desktop.sh','-o',script])
                run(['bash',script,'--no-launch'])
            print('Spark Link обновлён. Закройте и снова откройте приложение.')
        elif args.action == 'topology':
            apply_topology(read_json(args.plan))
        elif args.action == 'update':
            update_studio()
        elif args.action == 'refresh' and GUARD.with_name('fastload_manager.py').is_file():
            nodes = scan(read_json(CONFIG / 'topology.json'))
            assert_idle(nodes)
            run([sys.executable, GUARD.with_name('fastload_manager.py'), 'refresh', '--config', GUARD])
        elif args.action == 'start-studio':
            run(['systemctl', '--user', 'start', SERVICE])
            from urllib.request import urlopen
            for attempt in range(30):
                try:
                    with urlopen('http://127.0.0.1:8888/api/health',timeout=2) as response:
                        if response.status==200: break
                except Exception:
                    time.sleep(1)
            else: raise RuntimeError('Studio не ответила на проверку готовности. Посмотрите журнал и свободную память.')
        elif args.action in ('install', 'start-rpc') and len(read_json(CONFIG / 'topology.json', {}).get('nodes', [])) == 3:
            from .multi import setup_multi
            topology = validate_topology(read_json(CONFIG / 'topology.json'))
            nodes = scan(topology)
            assert_idle(nodes)
            if not all(plan_matches(n, compile_topology(topology)[n['id']]) for n in nodes):
                raise RuntimeError('Сначала примените сетевую схему трёх Spark.')
            setup_multi(topology, nodes)
        elif args.action == 'check':
            from dual_spark.fastload_manager import FastloadManager
            topology = validate_topology(read_json(CONFIG / 'topology.json'))
            nodes = scan(topology)
            if any(not n.get('online') for n in nodes):
                raise RuntimeError('Один из выбранных Spark недоступен по SSH.')
            plans = compile_topology(topology)
            if not all(plan_matches(n, plans[n['id']]) for n in nodes):
                raise RuntimeError('Фактические адреса не совпадают с выбранными портами. Примените схему.')
            configs = read_json(CONFIG / 'cluster-runtime.json', {}).get('peers') or [read_json(GUARD)]
            for config in configs:
                if not config: raise RuntimeError('RPC ещё не настроен. Откройте «Установка».')
                status = FastloadManager(GUARD.parent).status(config)
                print(config['rpc'] + ': ' + status['message'])
                if status['state'] != 'current': raise RuntimeError('Версия RPC не согласована. Откройте «Обновления».')
            print('SSH, выбранные порты и версии RPC проверены.')
        else:
            from dual_spark.operations import Installer
            from dual_spark.system import Runner
            from dual_spark.language import set_language
            from dual_spark.workflow import SetupWorkflow
            set_language('ru')
            installer = Installer(Runner(verbose=True))
            installer._show_rpc_logs = lambda: None
            if args.action == 'install':
                # Existing custom launchers are user-owned and must survive app installation.
                custom = GUARD.with_name('model_placement.py').is_file()
                if custom and STUDIO.is_file():
                    installer.detect_cluster()
                    installer.install_studio()
                    run([sys.executable, GUARD.with_name('fastload_manager.py'), 'ensure', '--config', GUARD])
                    print('Существующая пользовательская установка проверена и сохранена.')
                else:
                    installer.bootstrap = True
                    installer.offer_studio = lambda: False
                    SetupWorkflow(installer).run()
            elif args.action == 'check':
                installer.check()
                installer.status()
            elif args.action == 'start-rpc':
                installer.detect_cluster()
                installer.start_rpc()
        print('Операция завершена успешно.', flush=True)
        return 0
    except Exception as exc:
        print('Ошибка: ' + str(exc), file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
