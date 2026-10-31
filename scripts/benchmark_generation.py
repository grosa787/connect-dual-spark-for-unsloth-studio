"""Run on the primary Spark. Bounded loopback-only throughput study; no launcher changes.

Uses the caller-provided worker SSH identity for read-only RAM/swap monitoring.
It aborts below 1.5 GiB available on either node or on >0.5 GiB swap growth.
Outputs a log and JSON under ~/.cache/spark-runtime-update/mistral.
"""
import argparse,json,os,signal,subprocess,time,threading
from pathlib import Path
from urllib.request import Request,urlopen

parser=argparse.ArgumentParser()
parser.add_argument('--context',type=int,default=4096)
parser.add_argument('--split',default='46,54')
parser.add_argument('--label',default='baseline')
parser.add_argument('--no-warmup',action='store_true')
parser.add_argument('--mode',default='dio')
parser.add_argument('--binary')
parser.add_argument('--model',required=True)
parser.add_argument('--worker-ssh',required=True)
parser.add_argument('--rpc',default='10.100.32.2:50053')
parser.add_argument('--draft')
parser.add_argument('--hold',action='store_true')
parser.add_argument('--spec',choices=('none','ngram-map-k','draft-dspark'),default='none')
args=parser.parse_args()
home=Path.home(); root=home/'.cache/spark-runtime-update/mistral'; root.mkdir(parents=True,exist_ok=True)
if subprocess.run(['pgrep','-x','llama-server'],stdout=subprocess.DEVNULL).returncode==0: raise SystemExit('An existing model is active; refusing to interfere')
model=Path(args.model).expanduser()
if not model.is_file(): parser.error('Model shard does not exist')
if args.spec=='draft-dspark' and (not args.draft or not Path(args.draft).expanduser().is_file()): parser.error('--draft must name a compatible downloaded draft')
binary=Path(args.binary) if args.binary else home/'.local/share/connect-dual-spark/fastload/current/source/build/bin/llama-server'
command=[str(binary),'-m',str(model),'--host','127.0.0.1','--port','59446','--rpc',args.rpc,'--device','CUDA0,RPC0','--split-mode','layer','--tensor-split',args.split,'--n-gpu-layers','all','--load-mode',args.mode,'--fit','off','-c',str(args.context),'--parallel','1','--flash-attn','on','--cache-type-k','f16','--cache-type-v','f16','-b','128','-ub','64','--cache-ram','0','--ctx-checkpoints','0','--no-context-shift','--jinja','--metrics','--verbosity','4']
if args.spec=='draft-dspark': command+=['--spec-type','draft-dspark','--spec-draft-n-max','3','--spec-draft-model',str(Path(args.draft).expanduser()),'--spec-draft-device','CUDA0,RPC0','--spec-draft-ngl','all']
elif args.spec!='none': command+=['--spec-type',args.spec,'--spec-draft-n-max','16','--spec-ngram-map-k-size-n','4','--spec-ngram-map-k-size-m','16']
if args.no_warmup: command.append('--no-warmup')
environment=os.environ.copy(); environment['GGML_RPC_NO_HASH_CACHE']='1'
log=root/(args.label+'.log'); output=root/(args.label+'.json')
def memory(text):
    data={line.split(':',1)[0]:int(line.split()[1]) for line in text.splitlines() if ':' in line and line.split()[1].isdigit()}
    return {'available_gib':data['MemAvailable']/1048576,'swap_used_gib':(data['SwapTotal']-data['SwapFree'])/1048576}
def samples():
    local=memory(Path('/proc/meminfo').read_text())
    remote=memory(subprocess.check_output(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=3',args.worker_ssh,'cat /proc/meminfo'],text=True,timeout=7))
    return [local,remote]
initial=samples(); record={'spec':args.spec,'command':command,'context':args.context,'kv_type':'f16','split':args.split,'mode':args.mode,'warmup':not args.no_warmup,'initial_memory':initial,'samples':[],'requests':[],'status':'starting'}
process=None; started=time.monotonic(); last=0
watch_stop=threading.Event(); watch_errors=[]; watcher=None
def guard():
    global last
    if time.monotonic()-last<3: return
    last=time.monotonic(); current=samples(); record['samples'].append({'seconds':round(last-started,1),'nodes':current})
    for index,stats in enumerate(current):
        if stats['available_gib']<1.5 or stats['swap_used_gib']>initial[index]['swap_used_gib']+.5:
            raise RuntimeError('Memory/swap safety threshold reached: '+str(current))
def request(payload,timeout=180):
    req=Request('http://127.0.0.1:59446/completion',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=timeout) as response: return json.load(response)
def monitor():
    while not watch_stop.wait(1):
        try: guard()
        except Exception as exc:
            watch_errors.append(str(exc))
            if process and process.poll() is None:
                os.killpg(process.pid,signal.SIGTERM)
                try: process.wait(timeout=20)
                except subprocess.TimeoutExpired: os.killpg(process.pid,signal.SIGKILL)
            return
try:
    with log.open('w') as stream:
        process=subprocess.Popen(command,env=environment,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    watcher=threading.Thread(target=monitor,daemon=True); watcher.start()
    record['pid']=process.pid
    print('START',args.label,'PID',process.pid,'context',args.context,flush=True)
    until=time.monotonic()+600
    while process.poll() is None and time.monotonic()<until:
        guard()
        try:
            with urlopen('http://127.0.0.1:59446/health',timeout=1) as response:
                if response.status==200: break
        except Exception: pass
        time.sleep(.3)
    else: raise RuntimeError('Model failed to become ready: '+log.read_text(errors='replace')[-3500:])
    record['ready_seconds']=round(time.monotonic()-started,3); record['loaded_memory']=samples()
    print('READY',record['ready_seconds'],record['loaded_memory'],flush=True)
    tasks=[
        ('code','Write a Python function that merges overlapping closed intervals. Include type hints, a docstring and three assert examples. Explain edge cases.'),
        ('reasoning','Есть две верёвки: каждая сгорает ровно за час, но неравномерно. Как отмерить 45 минут? Обоснуй решение и объясни, почему нельзя просто делить длину пополам.'),
        ('rewrite','Convert the following JavaScript to TypeScript. Preserve the identifiers and repeat each item in the returned array. Return only code.\nconst colors = ["amber", "green", "blue", "white", "black"];\nfunction makeRows() { return colors.map((color, index) => ({ color, index, enabled: true })); }'),
    ]
    for temperature in (0,0.7):
      for index,(name,prompt) in enumerate(tasks):
        data=json.dumps({'messages':[{'role':'user','content':prompt}],'add_generation_prompt':True}).encode()
        with urlopen(Request('http://127.0.0.1:59446/apply-template',data=data,headers={'Content-Type':'application/json'}),timeout=30) as response: formatted=json.load(response)['prompt']
        result=request({'prompt':formatted,'n_predict':128,'temperature':temperature,'seed':1234,'ignore_eos':True,'cache_prompt':False},timeout=240)
        row={'task':name,'temperature':temperature,'timings':result.get('timings'),'tokens_predicted':result.get('tokens_predicted'),'content':result.get('content'),'stop':result.get('stop')}
        record['requests'].append(row)
        output.write_text(json.dumps(record,indent=2))
        print('GENERATED',name,temperature,json.dumps(row['timings']),flush=True)
        guard()
    if watch_errors: raise RuntimeError(watch_errors[0])
    record['status']='passed'
    if args.hold:
        record['status']='held'; output.write_text(json.dumps(record,indent=2)); print('HOLD ready for additional requests',flush=True)
        stop_file=root/(args.label+'.stop'); stop_file.unlink(missing_ok=True)
        while process.poll() is None and not stop_file.exists(): guard(); time.sleep(.3)
        if watch_errors: raise RuntimeError(watch_errors[0])
        record['status']='passed'
except Exception as exc:
    record['status']='failed'; record['error']=watch_errors[0] if watch_errors else str(exc); print('FAIL',record['error'],flush=True)
finally:
    watch_stop.set()
    if process and process.poll() is None:
        os.killpg(process.pid,signal.SIGTERM)
        try: process.wait(timeout=20)
        except subprocess.TimeoutExpired: os.killpg(process.pid,signal.SIGKILL); process.wait()
    if watcher: watcher.join(timeout=8)
    record['duration_seconds']=round(time.monotonic()-started,2)
    output.write_text(json.dumps(record,indent=2))
    print('RESULT',output,record['status'],flush=True)
if record['status']=='failed': raise SystemExit(1)
