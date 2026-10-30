"""Administrative netplan transaction. No arbitrary interfaces or commands accepted."""
import argparse
import copy
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

INTERFACES = ('enp1s0f0np0', 'enp1s0f1np1', 'enP2p1s0f0np0', 'enP2p1s0f1np1')
DESTINATION = Path('/etc/netplan/99-nvidia-sync-cluster.yaml')
BACKUPS = Path('/etc/netplan/.spark-link-backups')


def checked_plan(plan):
    if not isinstance(plan, dict) or plan.get('version') != 1 or set(plan.get('interfaces', {})) != set(INTERFACES):
        raise ValueError('План может изменять только четыре интерфейса ConnectX-7.')
    seen = set()
    for addresses in plan['interfaces'].values():
        if not isinstance(addresses, list) or len(addresses) > 1:
            raise ValueError('Неожиданный список адресов.')
        for address in addresses:
            parsed = ipaddress.ip_interface(address)
            octets = str(parsed.ip).split('.')
            if parsed.version != 4 or parsed.network.prefixlen != 24 or octets[:2] != ['10', '100'] or int(octets[2]) not in range(32, 38) or octets[3] not in ('1', '2') or address in seen:
                raise ValueError('Разрешены только выделенные адреса кластера 10.100.32–37.x/24.')
            seen.add(address)
    return copy.deepcopy(plan)


def network_document(previous, plan):
    plan = checked_plan(plan)
    document = copy.deepcopy(previous or {'network': {'version': 2}})
    network = document.setdefault('network', {'version': 2})
    ethernet = network.setdefault('ethernets', {})
    for iface, addresses in plan['interfaces'].items():
        # Keep management NICs and unrelated network configuration untouched.
        ethernet[iface] = {'dhcp4': False, 'dhcp6': False, 'optional': True,
                           'link-local': ['ipv4', 'ipv6'], 'addresses': addresses,
                           'renderer': 'NetworkManager'}
    return document


def atomic_bytes(path, content):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        stream.write(content)
        name = stream.name
    os.chmod(name, 0o600)
    os.replace(name, path)


def restore(backup):
    backup = Path(backup).resolve()
    if backup.parent != BACKUPS.resolve() or not backup.is_file():
        raise ValueError('Неизвестная резервная копия сети.')
    receipt = json.loads(backup.read_text())
    if receipt['existed']:
        atomic_bytes(DESTINATION, receipt['text'].encode())
    elif DESTINATION.exists():
        DESTINATION.unlink()
    subprocess.run(['netplan', 'apply'], check=True, timeout=45)


def apply(plan):
    import yaml
    plan = checked_plan(plan)
    if subprocess.run(['pgrep', '-x', 'llama-server'], stdout=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError('Сначала выгрузите модель. Сеть активной генерации менять нельзя.')
    for iface, addresses in plan['interfaces'].items():
        if addresses:
            base = Path('/sys/class/net') / iface
            if (base / 'carrier').read_text().strip() != '1':
                raise RuntimeError(f'{iface}: кабель в выбранном порту не обнаружен.')
            driver = subprocess.check_output(['ethtool', '-i', iface], text=True)
            if 'mlx5_core' not in driver:
                raise RuntimeError('Выбранный интерфейс не ConnectX-7.')
    existed = DESTINATION.exists()
    previous = DESTINATION.read_text() if existed else ''
    document = network_document(yaml.safe_load(previous) if previous else None, plan)
    BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = BACKUPS / f'{time.time_ns()}.json'
    atomic_bytes(backup, json.dumps({'existed': existed, 'text': previous}).encode())
    try:
        atomic_bytes(DESTINATION, yaml.safe_dump(document, sort_keys=False).encode())
        subprocess.run(['netplan', 'generate'], check=True, timeout=30)
        subprocess.run(['netplan', 'apply'], check=True, timeout=45)
        actual = json.loads(subprocess.check_output(['ip', '-j', '-4', 'addr'], text=True))
        found = {x['ifname']: {a['local'] for a in x.get('addr_info', [])} for x in actual}
        for iface, addresses in plan['interfaces'].items():
            if not {a.split('/')[0] for a in addresses}.issubset(found.get(iface, set())):
                raise RuntimeError(f'Адрес не применился на {iface}.')
        print(json.dumps({'backup': str(backup), 'state': 'applied'}), flush=True)
    except BaseException:
        restore(backup)
        raise


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--plan')
    group.add_argument('--rollback')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Этот шаг требует sudo для настройки ConnectX-7.')
    if args.rollback:
        restore(args.rollback)
    else:
        apply(json.loads(Path(args.plan).read_text()))


if __name__ == '__main__':
    main()
