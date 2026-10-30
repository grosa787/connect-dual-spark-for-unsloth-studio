"""Physical QSFP topology, independent of Qt and the installed CLI."""
import copy
import re

INTERFACES = ('enp1s0f0np0', 'enp1s0f1np1', 'enP2p1s0f0np0', 'enP2p1s0f1np1')


def safe_target(value):
    if not isinstance(value, str) or len(value) > 200 or not re.fullmatch(r'(?:[a-zA-Z0-9_][a-zA-Z0-9_.-]*@)?[a-zA-Z0-9][a-zA-Z0-9_.-]*', value):
        raise ValueError('Введите SSH-имя Spark без команд и пробелов.')
    return value


def default_topology(count=2):
    nodes = [{'id': 'head', 'name': 'Первый Spark', 'ssh': '', 'local': True},
             {'id': 'worker2', 'name': 'Второй Spark', 'ssh': '', 'local': False}]
    cables = [{'a': 'head', 'a_port': 0, 'b': 'worker2', 'b_port': 0}]
    if count == 3:
        nodes.append({'id': 'worker3', 'name': 'Третий Spark', 'ssh': '', 'local': False})
        cables.extend([{'a': 'head', 'a_port': 1, 'b': 'worker3', 'b_port': 0},
                       {'a': 'worker2', 'a_port': 1, 'b': 'worker3', 'b_port': 1}])
    return {'version': 1, 'nodes': nodes, 'cables': cables}


def validate_topology(value, require_targets=True):
    if not isinstance(value, dict) or value.get('version') != 1:
        raise ValueError('Неизвестный формат схемы подключения.')
    nodes, cables = value.get('nodes', []), value.get('cables', [])
    if not isinstance(nodes,list) or not isinstance(cables,list) or any(not isinstance(n,dict) for n in nodes) or any(not isinstance(c,dict) for c in cables):
        raise ValueError('Повреждена схема подключения.')
    if len(nodes) not in (2, 3) or len(cables) != (1 if len(nodes) == 2 else 3):
        raise ValueError('Для двух Spark нужен один кабель, для трёх — треугольник из трёх.')
    ids = [n.get('id') for n in nodes]
    if ids != ['head', 'worker2', 'worker3'][:len(nodes)]:
        raise ValueError('Некорректные устройства в схеме.')
    if any(n.get('local') is not (i==0) for i,n in enumerate(nodes)):
        raise ValueError('Первым устройством должен быть этот компьютер.')
    targets = []
    for node in nodes[1:]:
        target = node.get('ssh', '')
        if target or require_targets:
            targets.append(safe_target(target))
    if len(targets) != len(set(targets)):
        raise ValueError('Каждый Spark должен иметь отдельное SSH-имя.')
    ports, edges = set(), set()
    for cable in cables:
        a, b = cable.get('a'), cable.get('b')
        if a not in ids or b not in ids or a == b:
            raise ValueError('Кабель должен соединять два разных Spark.')
        edge = tuple(sorted((a, b)))
        if edge in edges:
            raise ValueError('Дублирующий кабель в схеме.')
        edges.add(edge)
        for side in ('a', 'b'):
            port = cable.get(side + '_port')
            if type(port) is not int or port not in (0, 1):
                raise ValueError('У Spark есть только порт 0 и порт 1.')
            endpoint = (cable[side], port)
            if endpoint in ports:
                raise ValueError('Один физический порт нельзя подключить к двум кабелям.')
            ports.add(endpoint)
    return copy.deepcopy(value)


def compile_topology(value):
    value = validate_topology(value)
    plans = {n['id']: {'version': 1, 'node': n['id'], 'interfaces': {i: [] for i in INTERFACES}} for n in value['nodes']}
    pairs = [('head', 'worker2'), ('head', 'worker3'), ('worker2', 'worker3')]
    for cable in value['cables']:
        edge = tuple(sorted((cable['a'], cable['b']), key=lambda x: ['head', 'worker2', 'worker3'].index(x)))
        subnet = 32 + 2 * pairs.index(edge)
        for side in ('a', 'b'):
            node, port = cable[side], cable[side + '_port']
            suffix = 1 if node == edge[0] else 2
            for rail, prefix in enumerate(('enp1s0f', 'enP2p1s0f')):
                iface = f'{prefix}{port}np{port}'
                plans[node]['interfaces'][iface] = [f'10.100.{subnet + rail}.{suffix}/24']
    return plans
