"""Real small-model policy smoke on the two authorized Sparks; never unloads existing models."""
import json
from pathlib import Path
import subprocess
import time
from urllib.request import Request,urlopen
from spark_link.model_policy import save_policy,remove_policy,POLICIES,BASE
from spark_link.state import read_json

if subprocess.run(['pgrep','-x','llama-server'],stdout=subprocess.DEVNULL).returncode==0:
    raise SystemExit('A model is active; runtime QA refuses to interrupt it.')
repo='unsloth/Qwen3-0.6B-GGUF'
filename='Qwen3-0.6B-UD-Q4_K_XL.gguf'
models=list((Path.home()/'.cache/huggingface/hub/models--unsloth--Qwen3-0.6B-GGUF/snapshots').glob('*/'+filename))
assert models,'Tiny cached GGUF is required for this bounded smoke test.'
path=models[0]
identity=repo+':UD-Q4_K_XL'
assert not any(p.get('id')==identity for p in read_json(POLICIES,{'models':[]})['models']),'User already has a policy for the QA model; do not overwrite it.'
record={'repo':repo,'variant':'UD-Q4_K_XL','files':[filename],'weights_gib':path.stat().st_size/1024**3,'kv_gib':0.06,'context':512,'dtype':'f16',
        'percents':{'head':45,'worker2':55},'head_reserve':24,'worker_reserve':8,'auto_topology':True}
saved=False; process=None
logpath=Path('/tmp/spark-link-model-policy-qa.log')
try:
    save_policy(record,2); saved=True
    with logpath.open('w') as log:
        process=subprocess.Popen([str(Path.home()/'.unsloth/llama.cpp/llama-server'),'-m',str(path),'--host','127.0.0.1','--port','59445','-c','8192','--parallel','1','--flash-attn','on','--verbosity','4'],stdout=log,stderr=subprocess.STDOUT)
        ready=False
        until=time.monotonic()+90
        while time.monotonic()<until and process.poll() is None:
            try:
                with urlopen('http://127.0.0.1:59445/health',timeout=1) as response:
                    if response.status==200: ready=True; break
            except Exception: pass
            time.sleep(.3)
        assert ready,logpath.read_text()[-3000:]
        args=Path(f'/proc/{process.pid}/cmdline').read_bytes().decode().split('\0')
        assert args[args.index('--tensor-split')+1]=='45,55',args
        assert args[args.index('-c')+1]=='512',args
        request=Request('http://127.0.0.1:59445/completion',data=json.dumps({'prompt':'The capital of France is','n_predict':8,'temperature':0}).encode(),headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=20) as response: result=json.load(response)
        assert result.get('content') and result['tokens_predicted']>0,result
        with urlopen('http://127.0.0.1:8888/api/health',timeout=3) as response: assert response.status==200
        print('PASS: independent standard-library guard; requested 45:55 split; saved 512-token context overrides stale args; two-device GGUF completion; Studio remains healthy.')
finally:
    if process and process.poll() is None:
        process.terminate()
        try: process.wait(timeout=15)
        except subprocess.TimeoutExpired: process.kill(); process.wait()
    if saved: remove_policy(identity)
