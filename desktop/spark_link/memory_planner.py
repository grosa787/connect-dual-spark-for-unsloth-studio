"""HF model metadata and conservative layer-weight / KV-cache allocation planning."""
import hashlib
import json
import math
import re
import time
from urllib.parse import urlparse,unquote,quote
from urllib.request import Request,urlopen
from .gguf_metadata import read_remote_header
from .state import STATE,read_json,write_json

GIB=1024**3

def parse_hf_reference(reference):
    reference=reference.strip()
    if '://' in reference:
        parsed=urlparse(reference)
        if parsed.scheme!='https' or parsed.hostname not in ('huggingface.co','www.huggingface.co') or parsed.username or parsed.password or parsed.port:
            raise ValueError('Use an HTTPS huggingface.co model URL or owner/model ID')
        parts=[unquote(p) for p in parsed.path.strip('/').split('/')]
    else: parts=reference.split('/')
    if len(parts)<2 or not all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',p) and p not in ('.','..') for p in parts[:2]):
        raise ValueError('Use a Hugging Face owner/model ID')
    if '://' not in reference and len(parts)!=2: raise ValueError('Use a Hugging Face owner/model ID')
    return {'repo':'/'.join(parts[:2]),'path':'/'.join(parts[4:]) if len(parts)>4 and parts[2] in ('tree','blob','resolve') else ''}


def model_variants(siblings):
    groups={}
    for item in siblings:
        name=item.get('rfilename','')
        if not name.lower().endswith('.gguf') or re.search(r'(?:^|[/_.-])(mmproj|projector|draft|mtp)(?:[/_.-]|$)',name,re.I): continue
        match=re.search(r'(?:UD-)?(?:IQ[0-9][A-Za-z0-9_]*|Q[0-9][A-Za-z0-9_]*|BF16|F16|F32)',name,re.I)
        label=match.group().upper() if match else name.rsplit('/',1)[-1].split('-00001-of-')[0]
        prefix=re.sub(r'-\d{5}-of-\d{5}(?=\.gguf$)','',name)
        key=prefix
        group=groups.setdefault(key,{'label':label,'files':[],'size_bytes':0,'kind':'gguf','complete':True})
        group['files'].append(name)
        group['size_bytes']+=int(item.get('size') or item.get('lfs',{}).get('size') or 0)
    for group in groups.values():
        expected=re.search(r'-\d{5}-of-(\d{5})\.gguf$',group['files'][0])
        group['complete']=bool(group['size_bytes']) and (not expected or len(group['files'])==int(expected.group(1)))
        group['files'].sort()
    if not groups:
        files=[s for s in siblings if re.search(r'(?:^|/)(model(?:-\d+-of-\d+)?\.safetensors|pytorch_model(?:-\d+-of-\d+)?\.bin)$',s.get('rfilename',''))]
        if files: return [{'label':'HF weights','kind':'huggingface','files':[s['rfilename'] for s in files], 'size_bytes':sum(int(s.get('size') or s.get('lfs',{}).get('size') or 0) for s in files),'complete':True}]
    return sorted(groups.values(),key=lambda g:(g['size_bytes'],g['label']))


def normalized_metadata(config):
    arch=config.get('model_type','unknown')
    if arch=='qwen2_moe': arch='qwen2moe'
    result={'general.architecture':arch}
    fields={'block_count':'num_hidden_layers','embedding_length':'hidden_size','attention.head_count':'num_attention_heads','attention.head_count_kv':'num_key_value_heads','attention.key_length':'head_dim','attention.value_length':'head_dim','context_length':'max_position_embeddings'}
    for target,source in fields.items():
        if config.get(source) is not None: result[arch+'.'+target]=config[source]
    if config.get('sliding_window'): result[arch+'.attention.sliding_window']=config['sliding_window']
    return result


def estimate_kv(metadata,context,dtype='f16',dtype_v=None):
    arch=metadata.get('general.architecture','unknown')
    full={'llama','qwen2','qwen2moe','qwen3','qwen3moe','mistral','gemma','gemma2','gemma3','phi2','phi3','falcon','gptneox','gpt2','starcoder2','olmo','granite','cohere2'}
    if arch not in full: return {'gib':None,'quality':'unknown','reason':'compressed_or_unknown'}
    def get(key,default=None): return metadata.get(arch+'.'+key,default)
    try:
        layers=int(get('block_count')); heads=int(get('attention.head_count')); embedding=int(get('embedding_length'))
        kv_heads=int(get('attention.head_count_kv',heads))
        key=int(get('attention.key_length',embedding//heads)); val=int(get('attention.value_length',key))
        sizes={'f16':2,'f32':4,'q8_0':34/32,'q4_0':18/32}
        size_k,size_v=sizes[dtype],sizes[dtype_v or dtype]
        if min(layers,heads,embedding,kv_heads,key,val,int(context))<=0: raise ValueError()
        gib=int(context)*layers*kv_heads*(key*size_k+val*size_v)/GIB
        return {'gib':gib,'quality':'upper_bound' if get('attention.sliding_window') else 'estimate','reason':'full_attention'}
    except (TypeError,ValueError,KeyError,ZeroDivisionError):
        return {'gib':None,'quality':'unknown','reason':'missing_metadata'}


def allocate(weights_gib,kv_gib,available_gib,percents=None,head_reserve=24,worker_reserve=8,compute_margin=4):
    values=[weights_gib,head_reserve,worker_reserve,compute_margin,*available_gib]
    if kv_gib is None: raise ValueError('KV cache budget is unknown; enter it manually')
    values.append(kv_gib)
    if any(not math.isfinite(float(v)) or float(v)<0 for v in values) or weights_gib<=0 or len(available_gib) not in (1,2,3):
        raise ValueError('Memory values must be finite and non-negative')
    reserves=[head_reserve]+[worker_reserve]*(len(available_gib)-1)
    capacity=[max(0,a-r-compute_margin) for a,r in zip(available_gib,reserves)]
    if percents is None:
        if sum(capacity)<=0: raise ValueError('No usable memory after reserves')
        percents=[100*c/sum(capacity) for c in capacity]
    if len(percents)!=len(available_gib) or any(not math.isfinite(float(p)) or p<0 for p in percents) or abs(sum(percents)-100)>0.05:
        raise ValueError('Device percentages must add up to 100')
    allocations=[]
    for index,(available,reserve,percent) in enumerate(zip(available_gib,reserves,percents)):
        fraction=percent/100
        weights,kv=weights_gib*fraction,kv_gib*fraction
        remaining=available-weights-kv-(compute_margin if percent else 0)
        allocations.append({'index':index,'percent':percent,'weights_gib':weights,'kv_gib':kv,'reserve_gib':reserve,'remaining_gib':remaining,'fits':percent==0 or remaining>=reserve-0.001})
    return {'allocations':allocations,'fits':all(a['fits'] for a in allocations),'weights_gib':weights_gib,'kv_gib':kv_gib,'total_gib':weights_gib+kv_gib}


def read_json_url(url,limit=8*1024*1024):
    with urlopen(Request(url,headers={'User-Agent':'Spark-Link/1.1'}),timeout=15) as response:
        content=response.read(limit+1)
    if len(content)>limit: raise ValueError('Model metadata response is too large')
    return json.loads(content)


def analyze_model(reference):
    parsed=parse_hf_reference(reference)
    repo=parsed['repo']
    cache=STATE/'model-metadata'/(hashlib.sha256(repo.encode()).hexdigest()+'.json')
    try:
        info=read_json_url('https://huggingface.co/api/models/'+quote(repo,safe='/')+'?blobs=true')
        variants=model_variants(info.get('siblings',[]))
        if not variants: raise ValueError('No supported model weight files found in this repository')
        config={}
        try: config=read_json_url('https://huggingface.co/'+quote(repo,safe='/')+'/resolve/'+quote(info.get('sha','main'),safe='')+'/config.json',2*1024*1024)
        except Exception: pass
        metadata=normalized_metadata(config)
        chosen=next((v for v in variants if parsed['path'] and any(f.startswith(parsed['path']) for f in v['files'])),None) or next((v for v in variants if v['label'].startswith('UD-Q8')),variants[0])
        if chosen['kind']=='gguf':
            try:
                url='https://huggingface.co/'+quote(repo,safe='/')+'/resolve/'+quote(info.get('sha','main'),safe='')+'/'+quote(chosen['files'][0],safe='/')
                metadata.update(read_remote_header(url))
            except Exception: pass
        arch=metadata.get('general.architecture','unknown')
        max_context=metadata.get(arch+'.context_length') or info.get('gguf',{}).get('context_length')
        if not isinstance(max_context,int) or not 1<=max_context<=2147483647: max_context=None
        result={'repo':repo,'revision':info.get('sha',''),'variants':variants,'selected':variants.index(chosen),'metadata':metadata,'max_context':max_context,'fetched_at':time.time(),'cached':False}
        write_json(cache,result)
        return result
    except Exception:
        cached=read_json(cache)
        if cached:
            cached['cached']=True
            return cached
        raise
