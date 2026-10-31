"""Machine-calibrated launch layouts, bound to exact model metadata and runtime.

Only execution placement/batching changes. Weights, context, KV precision and
reasoning instructions are retained. Other models use the ordinary memory guard.
"""
import hashlib
import math
import os
from pathlib import Path
import sys
from .state import CONFIG,read_json

def _argument(args,names,default=''):
    result=default
    for i,arg in enumerate(args):
        if arg in names and i+1<len(args): result=args[i+1]
        for name in names:
            if arg.startswith(name+'='): result=arg.split('=',1)[1]
    return result

def _digest(path,limit=None):
    with Path(path).open('rb') as stream:
        return hashlib.sha256(stream.read(limit)).hexdigest() if limit else hashlib.file_digest(stream,'sha256').hexdigest()

def apply_profile(command,nodes):
    model=_argument(command,('-m','--model'))
    if not model: return None
    path=Path(model)
    profiles=read_json(CONFIG/'launch-profiles.json',{}).get('profiles',[])
    profile=next((p for p in profiles if p.get('enabled') and p.get('model')==str(path.resolve())),None)
    if profile is None: return None
    context=int(_argument(command,('-c','--ctx-size'),os.environ.get('LLAMA_ARG_CTX_SIZE',str(profile['context']))))
    if context==0: context=int(profile['context'])
    if context<int(profile.get('min_context',profile['context'])): return None
    if context>int(profile['context']): raise RuntimeError('Requested context exceeds the validated launch profile')
    dtype=_argument(command,('--cache-type-k','-ctk'),os.environ.get('LLAMA_ARG_CACHE_TYPE_K','f16'))
    dtype_v=_argument(command,('--cache-type-v','-ctv'),os.environ.get('LLAMA_ARG_CACHE_TYPE_V','f16'))
    if dtype!=profile['dtype'] or dtype_v!=profile['dtype']: return None
    if path.stat().st_size!=profile['model_size'] or _digest(path,8*1024*1024)!=profile['header_sha256']:
        raise RuntimeError('Model changed; recalibrate its long-context launch profile')
    for shard in profile.get('shards',[]):
        if Path(shard['filename']).name!=shard['filename'] or (path.parent/shard['filename']).stat().st_size!=shard['size']:
            raise RuntimeError('Model shards changed; recalibrate the long-context profile')
    forbidden={'--override-kv','--lora','--lora-scaled','--control-vector','--cpu-moe','-cmoe','--n-cpu-moe','-ncmoe'}
    if any(arg.split('=',1)[0] in forbidden for arg in command):
        raise RuntimeError('Additional adapters or CPU/metadata overrides are not calibrated for this memory profile')
    if _digest(command[0])!=profile['binary_sha256']:
        raise RuntimeError('Model runtime changed; recalibrate its long-context launch profile')
    if [n['id'] for n in nodes]!=profile['node_ids'] or len(nodes)!=3:
        raise RuntimeError('This long-context profile requires all three configured devices')
    endpoints=_argument(command,('--rpc',)).split(',')
    if endpoints!=profile['endpoints']:
        raise RuntimeError('RPC devices changed; recalibrate the long-context profile')
    signatures=profile.get('rpc_manifests',{})
    if signatures:
        from .multi import manager_base
        for config in read_json(CONFIG/'cluster-runtime.json',{}).get('peers',[]):
            expected=signatures.get(config.get('node_id'))
            manifest=read_json(manager_base(config)/'fastload/current/manifest.json',{})
            if not expected or any(manifest.get(key)!=value for key,value in expected.items()):
                raise RuntimeError('RPC runtime changed; recalibrate the long-context profile')
    for extra in profile.get('extra_files',[]):
        value=_argument(command,tuple(extra.get('options') or [extra['option']]))
        if value and Path(value).stat().st_size>extra['max_bytes']:
            raise RuntimeError('Draft or projector exceeds the validated memory budget')
    required=profile['required_gib'];reserve=float(profile['reserve_gib']);split=profile['split']
    if (len(required)!=3 or len(split)!=3 or not 1<=reserve<=32
            or any(not math.isfinite(float(n)) or not 0<float(n)<=512 for n in required)
            or any(not math.isfinite(float(n)) or not 0<float(n)<=100 for n in split)
            or abs(sum(split)-100)>0.05): raise ValueError('Invalid calibrated memory layout')
    for node,cost in zip(nodes,required):
        if node['available_gib']<float(cost)+reserve:
            raise RuntimeError('Insufficient free memory on '+node['id']+' for the validated long-context profile')
    for field,maximum in (('batch',2048),('ubatch',512),('parallel',4)):
        if type(profile[field]) is not int or not 1<=profile[field]<=maximum: raise ValueError('Invalid profile batching')
    if profile['ubatch']>profile['batch']: raise ValueError('Microbatch exceeds batch size')
    override=profile['tensor_override']
    if (len(override)>4096 or '\n' in override or not override.endswith('=RPC0['+endpoints[0]+']')):
        raise ValueError('Invalid shared-KV placement')
    options={'-c','--ctx-size','--fit-ctx','-fitc','-b','--batch-size','-ub','--ubatch-size',
             '-np','--parallel','--flash-attn','-fa','--fit','--tensor-split','-ts',
             '--override-tensor','-ot','--spec-draft-device','--device-draft','-devd','--spec-draft-n-max',
             '--cache-ram','--ctx-checkpoints'}
    clean=[command[0]];i=1
    while i<len(command):
        name=command[i].split('=',1)[0]
        if name in options: i+=1 if '=' in command[i] else 2
        else: clean.append(command[i]);i+=1
    clean+=['-c',str(context),'--fit-ctx',str(context),'--fit','off','--flash-attn','on',
            '-b',str(profile['batch']),'-ub',str(profile['ubatch']),'--parallel',str(profile['parallel']),
            '--tensor-split',','.join(format(n,'.8g') for n in split),'--override-tensor',override,
            '--spec-draft-device','CUDA0,RPC0,RPC1','--spec-draft-n-max','3',
            '--cache-ram','0','--ctx-checkpoints','0']
    if profile.get('no_rpc_graph_cache'): os.environ['GGML_RPC_NO_GRAPH_CACHE']='1'
    print('Spark Link: validated launch profile '+profile['name']+'; context='+str(context)
          +'; F16 KV; batch='+str(profile['batch'])+'/'+str(profile['ubatch'])
          +'; slots='+str(profile['parallel']),file=sys.stderr,flush=True)
    return clean
