"""Hardware identity distinguishes Sparks made from the same OS image."""
def device_identity(node):
    return node.get('device_id') or node.get('machine_id') or ''

def same_device(left,right):
    if bool(left.get('device_id'))!=bool(right.get('device_id')): return False
    identity=device_identity(left)
    return bool(identity) and identity==device_identity(right)

def enrollment_slot(nodes,current,new):
    online={n['id']:n.get('online',False) for n in current}
    names={new.get('hostname','')+'.local',new.get('management_ip','')}
    for index,node in enumerate(nodes[1:],1):
        if node.get('machine_id') or node.get('device_id') or online.get(node['id']): continue
        target=node.get('ssh','').split('@')[-1]
        if not target or target in names: return index
    return len(nodes)
