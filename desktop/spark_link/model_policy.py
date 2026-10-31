"""Model-specific memory policies, enforced at the final guarded exec boundary."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
from .memory_planner import allocate,estimate_kv
from .gguf_metadata import parse_header
from .runtime_stats import observed_cache
from .state import CONFIG,STATE,read_json,write_json

POLICIES=CONFIG/'model-policies.json'
BASE=Path.home()/'.local/share/connect-dual-spark'
MARKER='SPARK_LINK_MEMORY_GATEWAY'

def argument(args,names):
    value=''
    for index,arg in enumerate(args):
        if arg in names and index+1<len(args): value=args[index+1]
        for name in names:
            if arg.startswith(name+'='): value=arg.split('=',1)[1]
    return value

def matched_policy(policies,args):
    model=argument(args,('-m','--model'))
    path=Path(model)
    hf=argument(args,('-hf','--hf-repo','--hf-repo','-hfr'))
    for policy in policies:
        if policy.get('local_path') and model and str(path.resolve())==policy['local_path']: return policy
        repo=policy.get('repo','')
        if hf and hf.split(':',1)[0]==repo and (':' not in hf or hf.split(':',1)[1].upper()==policy.get('variant','').upper()): return policy
        if model and 'models--'+repo.replace('/','--') in path.parts:
            for filename in policy.get('files',[]):
                parts=Path(filename).parts
                if len(parts)<=len(path.parts) and tuple(path.parts[-len(parts):])==parts: return policy
    return None

def planned_command(command,policy,nodes):
    percentages=policy.get('percents',{})
    ids=[n['id'] for n in nodes]
    changed=set(ids)!=set(percentages)
    shares=None if changed and policy.get('auto_topology',True) else [float(percentages.get(node,0)) for node in ids]
    if shares is not None and changed:
        total=sum(shares)
        if not total: raise RuntimeError('No selected model devices are available')
        shares=[100*s/total for s in shares]
    result=allocate(float(policy['weights_gib']),float(policy['kv_gib']),[n['available_gib'] for n in nodes],shares,
                    head_reserve=float(policy.get('head_reserve',24)),worker_reserve=float(policy.get('worker_reserve',8)))
    if not result['fits']: raise RuntimeError('Insufficient memory headroom for this model and context. Recalculate the model plan.')
    options={'--rpc','--device','-dev','--tensor-split','-ts','--split-mode','-sm','--main-gpu','-mg',
             '-c','--ctx-size','--fit-ctx','-fitc','--cache-type-k','--cache-type-v','-ctk','-ctv',
             '--spec-draft-device','--device-draft','-devd','--mmproj-device','-mmdev'}
    clean=[command[0]]; index=1
    while index<len(command):
        name=command[index].split('=',1)[0]
        if name in options: index+=1 if '=' in command[index] else 2
        else: clean.append(command[index]); index+=1
    selected=[(node,allocation) for node,allocation in zip(nodes,result['allocations']) if allocation['percent']>0.001]
    endpoints=[n['rpc'] for n,a in selected if n['id']!='head']
    devices=[]; remote=0
    for node,_ in selected:
        if node['id']=='head': devices.append('CUDA0')
        else: devices.append('RPC'+str(remote)); remote+=1
    if not devices: raise RuntimeError('No model device selected')
    if endpoints: clean+=['--rpc',','.join(endpoints)]
    clean+=['--device',','.join(devices),'--split-mode','layer' if len(devices)>1 else 'none']
    if len(devices)>1:
        clean+=['--tensor-split',','.join(format(a['percent'],'.8g') for n,a in selected)]
    context=int(policy['context'])
    if not 1<=context<=2147483647 or policy['dtype'] not in ('f16','q8_0','q4_0'): raise ValueError('Invalid memory policy context or cache type')
    clean+=['-c',str(context),'--fit-ctx',str(context),'--cache-type-k',policy['dtype'],'--cache-type-v',policy['dtype'],
            '--spec-draft-device',','.join(devices)]
    if '--no-mmproj-offload' not in clean: clean+=['--mmproj-device',devices[0]]
    return clean

def available_nodes(command):
    def memory(text): return int(next(l for l in text.splitlines() if l.startswith('MemAvailable:')).split()[1])/1048576
    nodes=[{'id':'head','available_gib':memory(Path('/proc/meminfo').read_text())}]
    endpoints=argument(command,('--rpc',)).split(',')
    configurations=read_json(CONFIG/'cluster-runtime.json',{}).get('peers') or [read_json(BASE/'llama-server-wrapper.json',{})]
    from dual_spark.system import remote_ssh
    for index,config in enumerate(configurations):
        if config.get('rpc') not in endpoints: continue
        result=subprocess.check_output(remote_ssh(type('Peer',(),{'host_ip':config['host_ip'],'host_iface':config['host_iface'],'worker_ip':config['rpc'].rsplit(':',1)[0]})(), 'cat /proc/meminfo'),text=True,timeout=15)
        nodes.append({'id':config.get('node_id','worker'+str(index+2)),'available_gib':memory(result),'rpc':config['rpc']})
    return nodes

def apply_saved(command,args):
    policy=matched_policy(read_json(POLICIES,{'models':[]}).get('models',[]),args)
    if not policy:
        # Refuse an oversized local fallback after a worker/cable outage.
        model=argument(args,('-m','--model'))
        if model and not argument(command,('--rpc',)) and Path(model).is_file():
            path=Path(model)
            files=list(path.parent.glob(path.name.split('-00001-of-')[0]+'*.gguf')) if '-00001-of-' in path.name else [path]
            size=sum(p.stat().st_size for p in files)
            available=int(next(l for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')).split()[1])*1024
            if size>available*0.85: raise RuntimeError('This model does not fit safely on the available local Spark. Reconnect the worker.')
        if model and Path(model).is_file():
            path=Path(model)
            try:
                with path.open('rb') as stream: metadata=parse_header(stream.read(8*1024*1024))
                arch=metadata.get('general.architecture','unknown')
                context=int(argument(command,('-c','--ctx-size')) or os.environ.get('LLAMA_ARG_CTX_SIZE') or metadata.get(arch+'.context_length') or 0)
                dtype=argument(command,('--cache-type-k','-ctk')) or os.environ.get('LLAMA_ARG_CACHE_TYPE_K','f16')
                dtype_v=argument(command,('--cache-type-v','-ctv')) or os.environ.get('LLAMA_ARG_CACHE_TYPE_V','f16')
                cache=estimate_kv(metadata,context,dtype,dtype_v)['gib']
                if cache is None and dtype==dtype_v:
                    repo_part=next((p for p in path.parts if p.startswith('models--')),None)
                    repo=repo_part[len('models--'):].replace('--','/',1) if repo_part else ''
                    cache=observed_cache(repo,[path.name],context,dtype,source_path=str(path))
            except (ValueError,OSError,TypeError): cache=None
            if cache is not None:
                files=list(path.parent.glob(path.name.split('-00001-of-')[0]+'*.gguf')) if '-00001-of-' in path.name else [path]
                weights=sum(p.stat().st_size for p in files)/1024**3
                nodes=available_nodes(command)
                selected=(argument(command,('--device','-dev')) or 'CUDA0').split(',')
                shares=[float(v) for v in argument(command,('--tensor-split','-ts')).split(',') if v] or [1]*max(1,len(selected))
                order=[]; remote=0
                for node in nodes:
                    device='CUDA0' if node['id']=='head' else 'RPC'+str(remote)
                    if node['id']!='head': remote+=1
                    order.append(device)
                actual=[shares[selected.index(device)] if device in selected and selected.index(device)<len(shares) else 0 for device in order]
                if sum(actual):
                    check=allocate(weights,cache,[n['available_gib'] for n in nodes],[100*s/sum(actual) for s in actual])
                    if not check['fits']: raise RuntimeError('Model weights and KV cache leave insufficient memory reserve. Create a Spark Link memory plan.')
        return command
    policy=dict(policy)
    model=argument(args,('-m','--model'))
    if model and Path(model).is_file():
        path=Path(model)
        files=list(path.parent.glob(path.name.split('-00001-of-')[0]+'*.gguf')) if '-00001-of-' in path.name else [path]
        policy['weights_gib']=sum(p.stat().st_size for p in files)/1024**3
    result=planned_command(command,policy,available_nodes(command))
    print('Spark Link: memory policy applied; context='+str(policy['context'])+'; devices='+argument(result,('--device',)),file=sys.stderr,flush=True)
    return result

def install_gateway(kind=None):
    launcher=BASE/'llama-server-wrapper.py'
    if not launcher.is_file(): raise RuntimeError('Install and configure RPC before saving a launch policy')
    metadata_path=CONFIG/'model-gateway.json'
    metadata=read_json(metadata_path,{})
    content=launcher.read_text()
    if MARKER not in content:
        STATE.mkdir(parents=True,exist_ok=True)
        backup=BASE/('llama-server-wrapper.before-memory-'+str(time.time_ns())+'.py')
        shutil.copy2(launcher,backup)
        metadata={'kind':kind or ('multi' if 'from spark_link.multi import main' in content else 'legacy'),'delegate':str(backup),'sha256':hashlib.sha256(backup.read_bytes()).hexdigest()}
    elif kind:
        metadata['kind']=kind
    if metadata.get('kind') not in ('legacy','multi'): raise ValueError('Unknown model gateway delegate')
    write_json(metadata_path,metadata)
    # Inference uses a tiny standard-library runtime outside the GUI installation.
    # Closing/removing the graphical runtime must not stop an installed RPC guard.
    import dual_spark
    package=Path(__file__).parent
    core=Path(dual_spark.__file__).parent
    names=('__init__.py','model_policy.py','memory_planner.py','gguf_metadata.py','runtime_stats.py','state.py','multi.py','topology.py')
    digest=hashlib.sha256(b''.join((package/name).read_bytes() for name in names)+b''.join(p.read_bytes() for p in sorted(core.glob('*.py')))).hexdigest()[:16]
    root=BASE/'model-runtime'
    destination=root/'releases'/digest
    if not destination.is_dir():
        temporary=destination.with_name(digest+'.new-'+str(os.getpid()))
        (temporary/'spark_link').mkdir(parents=True,mode=0o700)
        for name in names: shutil.copy2(package/name,temporary/'spark_link'/name)
        shutil.copytree(core,temporary/'dual_spark',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        os.replace(temporary,destination)
    for license_name in ('LICENSE','CLI-LICENSE'):
        license=package.parent/license_name
        if license.is_file(): shutil.copy2(license,destination/license_name)
    pointer=root/('.current-'+str(os.getpid()))
    pointer.symlink_to(destination,target_is_directory=True)
    os.replace(pointer,root/'current')
    source='#!/usr/bin/python3\n# '+MARKER+'\nimport sys\nsys.path.insert(0,'+repr(str(root/'current'))+')\nfrom spark_link.model_policy import gateway_main\ngateway_main()\n'
    temporary=launcher.with_suffix('.new')
    temporary.write_text(source); temporary.chmod(0o700); os.replace(temporary,launcher)

def save_policy(policy,node_count):
    data=read_json(POLICIES,{'version':1,'models':[]})
    identity=policy.get('repo')+':'+policy.get('variant','') if policy.get('repo') else policy.get('local_path')
    if not identity: raise ValueError('A repository ID or exact local model path is required')
    policy={**policy,'id':identity}
    old_record=next((p for p in data['models'] if p.get('id')==identity),None)
    install_gateway()
    # Reconcile the older single-device selector so it cannot bypass a newly saved multi-device plan.
    placement=BASE/'model-placement.json'
    if placement.exists():
        target=placement.resolve()
        previous=read_json(target,{'version':1,'entries':{}})
        mode='first' if policy['percents'].get('head')==100 else 'second' if node_count==2 and policy['percents'].get('worker2')==100 else 'both'
        key=identity
        entry=None
        if policy.get('repo') and policy.get('files'):
            entry={'model':policy['repo'],'quant':policy['variant'],'mode':mode,'filename':policy['files'][0],
                'binding':{'kind':'hf','repo_dir':'models--'+policy['repo'].replace('/','--')},'size_bytes':int(policy['weights_gib']*1024**3)}
        elif policy.get('local_path') and (BASE/'model_placement.py').is_file():
            spec=importlib.util.spec_from_file_location('spark_link_existing_placement',BASE/'model_placement.py')
            module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            selected=module.select_entry(module.load(target)['entries'],['-m',policy.get('source_path') or policy['local_path']])
            if selected:
                key=module.identity(selected['model'],selected['quant'])
                entry={**selected,'mode':mode}
        if entry is not None:
            policy['placement_key']=key
            policy['previous_rule']=old_record.get('previous_rule') if old_record and 'previous_rule' in old_record else previous['entries'].get(key)
            policy['installed_rule']=entry
            previous['entries'][key]=entry
            write_json(target,previous)
    data['models']=[p for p in data['models'] if p.get('id')!=identity]+[policy]
    write_json(POLICIES,data)
    return policy

def remove_policy(identity):
    data=read_json(POLICIES,{'version':1,'models':[]})
    record=next((p for p in data['models'] if p.get('id')==identity),None)
    if not record: return
    placement=BASE/'model-placement.json'
    if record.get('placement_key') and placement.is_file():
        target=placement.resolve(); previous=read_json(target)
        key=record['placement_key']
        # Respect a later edit made in another UI instead of clobbering it.
        if previous['entries'].get(key)==record.get('installed_rule'):
            if record.get('previous_rule') is None: previous['entries'].pop(key,None)
            else: previous['entries'][key]=record['previous_rule']
            write_json(target,previous)
    data['models']=[p for p in data['models'] if p.get('id')!=identity]
    write_json(POLICIES,data)

def gateway_main():
    metadata=read_json(CONFIG/'model-gateway.json',{})
    sys.path.insert(0,str(BASE))
    if metadata.get('kind')=='multi':
        from . import multi
        original=multi.model_command
        def command(binary,args,endpoints,mode='both'): return apply_saved(original(binary,args,endpoints,mode),args)
        multi.model_command=command
        multi.main()
        return
    delegate=Path(metadata.get('delegate',''))
    if not delegate.is_file() or hashlib.sha256(delegate.read_bytes()).hexdigest()!=metadata.get('sha256'):
        raise SystemExit('Saved model launcher changed. Reinstall the Spark Link memory gateway.')
    spec=importlib.util.spec_from_file_location('spark_link_saved_launcher',delegate)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    original=module.enforced_command
    def enforced(binary,args,*tail,**kwargs): return apply_saved(original(binary,args,*tail,**kwargs),args)
    module.enforced_command=enforced
    if hasattr(module,'local_command'):
        local=module.local_command
        module.local_command=lambda binary,args:apply_saved(local(binary,args),args)
    module.main(config_path=BASE/'llama-server-wrapper.json')
