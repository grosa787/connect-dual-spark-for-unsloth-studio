"""Physical QSFP topology, independent of Qt and the installed CLI."""
import copy
import re
import ipaddress

INTERFACES = ('enp1s0f0np0', 'enp1s0f1np1', 'enP2p1s0f0np0', 'enP2p1s0f1np1')


def safe_target(value):
    if isinstance(value,str) and '@' in value and '%' in value:
        user,address=value.split('@',1)
        ip,interface=address.rsplit('%',1)
        try:
            if re.fullmatch(r'[a-z_][a-z0-9_-]*[$]?',user) and interface in INTERFACES and ipaddress.IPv6Address(ip).is_link_local:
                return value
        except ValueError: pass
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


def select_port(value, cable_index, side, port):
    """Edit one endpoint without breaking the triangle or mutating the caller."""
    result=validate_topology(value,require_targets=False)
    if (type(cable_index) is not int or not 0<=cable_index<len(result['cables'])
            or side not in ('a','b') or type(port) is not int or port not in (0,1)):
        raise ValueError('Некорректный разъём кабеля.')
    cable=result['cables'][cable_index]
    old=cable[side+'_port']
    for index,other in enumerate(result['cables']):
        if index==cable_index: continue
        for endpoint in ('a','b'):
            if other[endpoint]==cable[side] and other[endpoint+'_port']==port:
                other[endpoint+'_port']=old
    cable[side+'_port']=port
    return validate_topology(result,require_targets=False)


def resize_topology(value,count):
    original=validate_topology(value,require_targets=False)
    if type(count) is not int or count not in (2,3):
        raise ValueError('Поддерживается два или три Spark.')
    if count==len(original['nodes']): return original
    result=default_topology(count)
    result['nodes'][:2]=original['nodes'][:2]
    pair=next(c for c in original['cables'] if {c['a'],c['b']}=={'head','worker2'})
    result['cables'][0]=pair
    if count==3:
        for index,node in ((1,'head'),(2,'worker2')):
            side='a' if pair['a']==node else 'b'
            result['cables'][index]['a_port']=1-pair[side+'_port']
    return validate_topology(result,require_targets=False)


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
