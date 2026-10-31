"""Cable-scoped discovery. No address sweep of the general management LAN."""
from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
from .inventory import probe,identity_file,ssh_argv,node_ssh
from .identity import same_device
from .topology import INTERFACES,default_topology,validate_topology

def physical_port(interface):
    return int(re.search(r'f([01])np[01]$',interface).group(1)) if interface in INTERFACES else None

def infer_topology(nodes):
    if len(nodes) not in (2,3): return None
    macs={data.get('mac','').lower():(node['id'],physical_port(iface)) for node in nodes for iface,data in node.get('interfaces',{}).items() if iface in INTERFACES and data.get('mac')}
    edges={}
    for node in nodes:
        for neighbor in node.get('neighbors',[]):
            if node.get('interfaces',{}).get(neighbor.get('dev'),{}).get('carrier') is False: continue
            port=physical_port(neighbor.get('dev'))
            other=macs.get(neighbor.get('lladdr','').lower())
            if port is None or not other or other[0]==node['id']: continue
            ordered=sorted([(node['id'],port),other],key=lambda x:['head','worker2','worker3'].index(x[0]))
            key=(ordered[0][0],ordered[1][0])
            edge={'a':ordered[0][0],'a_port':ordered[0][1],'b':ordered[1][0],'b_port':ordered[1][1]}
            if key in edges and edges[key]!=edge: return None
            edges[key]=edge
    if len(edges)!=(1 if len(nodes)==2 else 3): return None
    topology={'version':1,'nodes':[{k:v for k,v in node.items() if k in ('id','name','ssh','local','identity','machine_id','device_id','credential_id','host_key_alias','host_key_id','hostname','user','home','management_ip')} for node in nodes],'cables':list(edges.values())}
    try: return validate_topology(topology)
    except ValueError: return None

def warm_neighbors(node):
    commands=[]
    for iface,data in node.get('interfaces',{}).items():
        if iface.startswith('enp1s0f') and data.get('carrier'):
            commands.append(f'ping -6 -c 2 -W 1 -I {iface} ff02::1 >/dev/null 2>&1 || true')
    if not commands: return
    command='; '.join(commands)
    try:
        subprocess.run(['bash','-c',command] if node.get('local') else node_ssh(node)+[command],timeout=6,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except (OSError,subprocess.SubprocessError): pass

def fingerprint(address):
    try:
        output=subprocess.check_output(['ssh-keyscan','-t','ed25519','-T','2',address],text=True,stderr=subprocess.DEVNULL,timeout=4)
        line=next(line for line in output.splitlines() if ' ssh-ed25519 ' in line)
        public=line.split()[2]
        digest=base64.b64encode(hashlib.sha256(base64.b64decode(public)).digest()).decode().rstrip('=')
        return {'host_key':line,'fingerprint':'SHA256:'+digest,'key_id':digest}
    except Exception: return None

def filter_known_candidates(candidates,nodes):
    """Reconcile a delayed discovery result with the latest verified inventory."""
    online=[n for n in nodes if n.get('online')]
    macs={v['mac'].lower() for n in online for v in n.get('interfaces',{}).values() if v.get('mac')}
    keys={n['host_key_id'] for n in online if n.get('host_key_id')}
    return [c for c in candidates if c.get('existing_id') or not (
        c.get('mac','').lower() in macs or any(same_device(c.get('device',{}),node) for node in online) or c.get('id') in keys)]

def advertised_names(text):
    names=set()
    for line in text.splitlines():
        fields=line.split(';')
        if len(fields)<6 or fields[0] not in ('+','='): continue
        label=re.sub(r'\\([0-9]{3})',lambda m:chr(int(m[1])),fields[3])
        match=re.fullmatch(r'(spark-[a-zA-Z0-9-]{4,}) SSH',label)
        if match: names.add(match[1].lower()+'.local')
    return names


def bootstrap_candidates(nodes):
    """Passive SSH-service advertisements and LLDP, including other workers.

    A freshly installed Spark may have no IP address on ConnectX at all. Its
    advertised management name is still resolvable over the ordinary LAN.
    These are proposals only: onboarding verifies host key, GB10 and hardware ID.
    """
    names=set()
    try:
        result=subprocess.run(['avahi-browse','-pt','_ssh._tcp'],text=True,capture_output=True,timeout=6)
        names.update(advertised_names(result.stdout))
    except (OSError,subprocess.SubprocessError): pass
    def lldp_names(node):
        if not node.get('online'): return set()
        command=['lldpcli','-f','json','show','neighbors']
        try:
            argv=command if node.get('local') else node_ssh(node)+['lldpcli -f json show neighbors']
            result=subprocess.run(argv,text=True,capture_output=True,timeout=8)
            rows=json.loads(result.stdout).get('lldp',{}).get('interface',[])
            if isinstance(rows,dict): rows=[rows]
            return {name.lower()+'.local' for row in rows for iface,data in row.items() if iface in INTERFACES
                    for name in data.get('chassis',{}) if re.fullmatch(r'spark-[a-zA-Z0-9-]{4,}',name)
                    and name!=node.get('hostname')}
        except (OSError,ValueError,TypeError,AttributeError,subprocess.SubprocessError): return set()
    with ThreadPoolExecutor(max_workers=3) as pool:
        for found in pool.map(lldp_names,nodes): names.update(found)
    local_names={n.get('hostname','').lower()+'.local' for n in nodes if n.get('online')}
    result=[]
    head=next((n for n in nodes if n.get('local')), {})
    try: management=ipaddress.ip_network(str(head['management_ip'])+'/'+str(head.get('management_prefixlen',24)),strict=False)
    except (KeyError,ValueError): management=None
    for name in sorted(names-local_names)[:12]:
        try:
            addresses=socket.getaddrinfo(name,22,socket.AF_INET,socket.SOCK_STREAM)
            candidates={ip[4][0] for ip in addresses if ipaddress.ip_address(ip[4][0]).is_private and not ipaddress.ip_address(ip[4][0]).is_loopback and not ipaddress.ip_address(ip[4][0]).is_link_local}
            for address in sorted(candidates,key=lambda ip:(not (management and ipaddress.ip_address(ip) in management),ip))[:3]:
                result.append({'address':address,'hostname':name,'source':'mdns-lldp'})
        except (OSError,StopIteration): pass
    return result


def scan_new_devices(topology,known_nodes):
    head=next((n for n in known_nodes if n.get('local') and n.get('online')),None)
    if not head: return []
    addresses={c['address']:c for c in bootstrap_candidates(known_nodes)}
    warm_neighbors(head)
    refreshed=probe(topology['nodes'][0])
    known_macs={info.get('mac','').lower() for node in known_nodes if node.get('online') for info in node.get('interfaces',{}).values() if info.get('mac')}
    for neighbor in refreshed.get('neighbors',[]):
        iface=neighbor.get('dev','')
        if iface not in INTERFACES or not neighbor.get('lladdr') or neighbor['lladdr'].lower() in known_macs: continue
        try:
            address=ipaddress.ip_address(neighbor.get('dst',''))
            if address.version==6:
                if not address.is_link_local: continue
                target=str(address)+'%'+iface
            else:
                if not address.is_private: continue
                target=str(address)
            addresses.setdefault(target,{'address':target,'interface':iface,'mac':neighbor['lladdr'],'source':'connectx'})
        except ValueError: continue
    def inspect(candidate):
        key=fingerprint(candidate['address'])
        if not key: return None
        previous=next((n for n in known_nodes if n.get('host_key_id')==key['key_id']),None)
        target=(os.environ.get('USER','spark')+'@' if '%' in candidate['address'] else '')+candidate['address']
        if previous:
            username=previous.get('user') or previous['ssh'].split('@',1)[0]
            target=username+'@'+candidate['address']
        data=probe({**(previous or {}),'id':'pending','name':'Новый Spark','ssh':target,'local':False})
        known=next((n for n in known_nodes if data.get('online') and same_device(n,data)),None)
        if known:
            if known.get('online'): return None
            data.update({'id':known['id'],'name':known['name'],'ssh':data['user']+'@'+(data.get('management_ip') or data['hostname']+'.local')})
            return {**candidate,**key,'id':key['key_id'],'existing_id':known['id'],'device':data,'authorized':True}
        if data.get('online'): data['identity']=identity_file(target)
        return {**candidate,**key,'authorized':bool(data.get('online')),'device':data if data.get('online') else {},'id':key['key_id']}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(inspect,list(addresses.values())[:12]))
    unique={}
    for result in results:
        if result: unique.setdefault(result['id'],result)
    return list(unique.values())
