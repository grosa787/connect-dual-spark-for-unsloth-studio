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
from .topology import INTERFACES,default_topology,validate_topology

def physical_port(interface):
    return int(re.search(r'f([01])np[01]$',interface).group(1)) if interface in INTERFACES else None

def infer_topology(nodes):
    if len(nodes) not in (2,3): return None
    macs={data.get('mac','').lower():(node['id'],physical_port(iface)) for node in nodes for iface,data in node.get('interfaces',{}).items() if iface in INTERFACES and data.get('mac')}
    edges={}
    for node in nodes:
        for neighbor in node.get('neighbors',[]):
            port=physical_port(neighbor.get('dev'))
            other=macs.get(neighbor.get('lladdr','').lower())
            if port is None or not other or other[0]==node['id']: continue
            ordered=sorted([(node['id'],port),other],key=lambda x:['head','worker2','worker3'].index(x[0]))
            key=(ordered[0][0],ordered[1][0])
            edge={'a':ordered[0][0],'a_port':ordered[0][1],'b':ordered[1][0],'b_port':ordered[1][1]}
            if key in edges and edges[key]!=edge: return None
            edges[key]=edge
    if len(edges)!=(1 if len(nodes)==2 else 3): return None
    topology={'version':1,'nodes':[{k:v for k,v in node.items() if k in ('id','name','ssh','local','identity','machine_id','credential_id','host_key_alias','host_key_id','hostname','user','home','management_ip')} for node in nodes],'cables':list(edges.values())}
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

def scan_new_devices(topology,known_nodes):
    head=next((n for n in known_nodes if n.get('local') and n.get('online')),None)
    if not head: return []
    warm_neighbors(head)
    refreshed=probe(topology['nodes'][0])
    if not refreshed.get('online'): return []
    known_macs={info.get('mac','').lower() for node in known_nodes if node.get('online') for info in node.get('interfaces',{}).values() if info.get('mac')}
    known_ids={node.get('machine_id') for node in known_nodes if node.get('machine_id')}
    addresses={}
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
            addresses[target]={'address':target,'interface':iface,'mac':neighbor['lladdr']}
        except ValueError: continue
    def inspect(candidate):
        key=fingerprint(candidate['address'])
        if not key: return None
        previous=next((n for n in known_nodes if n.get('host_key_id')==key['key_id']),None)
        # Already trusted SSH identities can be recognized without asking for credentials.
        target=(os.environ.get('USER','spark')+'@' if '%' in candidate['address'] else '')+candidate['address']
        if previous:
            username=previous.get('user') or previous['ssh'].split('@',1)[0]
            target=username+'@'+candidate['address']
        data=probe({**(previous or {}),'id':'pending','name':'Новый Spark','ssh':target,'local':False})
        if data.get('online') and data.get('machine_id') in known_ids:
            known=next(n for n in known_nodes if n.get('machine_id')==data['machine_id'])
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
