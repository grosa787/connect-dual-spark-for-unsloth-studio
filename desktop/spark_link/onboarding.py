"""Explicitly authorized first login, pinned host key, public-key enrollment, encrypted credential persistence."""
import base64
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
from .credentials import SecretPipe,Vault
from .inventory import PROBE,probe
from .topology import safe_target

ENROLL=r'''
import base64,json,os,pathlib,subprocess,sys
gpu=subprocess.check_output(['nvidia-smi','--query-gpu=name','--format=csv,noheader'],text=True)
if 'GB10' not in gpu: raise SystemExit('This device is not a DGX Spark')
key=base64.b64decode(sys.argv[1]).decode().strip()
if not key.startswith('ssh-ed25519 '): raise SystemExit('Invalid enrollment public key')
directory=pathlib.Path.home()/'.ssh'; directory.mkdir(mode=0o700,exist_ok=True)
path=directory/'authorized_keys'
old=path.read_text() if path.exists() else ''
if key not in old.splitlines():
    with path.open('a') as stream: stream.write(('\n' if old and not old.endswith('\n') else '')+key+'\n')
path.chmod(0o600)
'''

def ensure_identity():
    directory=Path.home()/'.ssh'; directory.mkdir(mode=0o700,exist_ok=True)
    path=directory/'id_ed25519_spark_link'
    if not path.exists():
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-C','spark-link','-f',str(path)],check=True,stdin=subprocess.DEVNULL)
    path.chmod(0o600)
    return path

def pair_device(candidate,username,password,vault=None,identity=None):
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*[$]?',username) or not password or len(password)>4096 or '\n' in password or '\r' in password:
        raise ValueError('Invalid login or password')
    target=safe_target(username+'@'+candidate['address'])
    host_key=candidate.get('host_key','').strip()
    fields=host_key.split()
    if len(fields)!=3 or fields[1]!='ssh-ed25519': raise ValueError('Missing verified device host key')
    identity=identity or ensure_identity()
    public=identity.with_suffix('.pub').read_text().strip()
    helper=Path(__file__).with_name('askpass.py')
    helper.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix='spark-link-pair-') as directory,SecretPipe(password) as secret:
        known=Path(directory)/'known_hosts'; known.write_text(host_key+'\n'); known.chmod(0o600)
        env=os.environ.copy()
        env.update({'SSH_ASKPASS':str(helper),'SSH_ASKPASS_REQUIRE':'force','SPARK_LINK_ASKPASS_SOCKET':secret.path,
                    'PYTHONPATH':str(Path(__file__).parent.parent)})
        args=['ssh','-T','-o','ConnectTimeout=8','-o','NumberOfPasswordPrompts=1','-o','HostKeyAlgorithms=ssh-ed25519',
              '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(known),'-o','GlobalKnownHostsFile=/dev/null',
              '-o','BatchMode=no',target]
        # Probe before enrolling a key: authentication alone is not proof of Spark hardware.
        result=subprocess.run(args+['python3 -c '+shlex.quote(PROBE)],env=env,stdin=subprocess.DEVNULL,capture_output=True,text=True,start_new_session=True,timeout=50)
        if result.returncode: raise RuntimeError('SSH login failed. Check the account, password and host key.')
        info=json.loads(result.stdout)
        if 'GB10' not in info.get('gpu','') or not re.fullmatch(r'[a-f0-9]{16,64}',info.get('machine_id','')):
            raise RuntimeError('The connected device is not a recognized DGX Spark')
        credential=(vault or Vault())
        # Failure to persist securely is explicit. There is no plaintext fallback.
        credential.set_record(info['machine_id'],{'password':password,'username':username,'management_ip':info.get('management_ip',''),'hostname':info['hostname'],'identity':str(identity)})
        command='python3 -c '+shlex.quote(ENROLL)+' '+shlex.quote(base64.b64encode(public.encode()).decode())
        enrolled=subprocess.run(args+[command],env=env,stdin=subprocess.DEVNULL,capture_output=True,text=True,start_new_session=True,timeout=35)
        if enrolled.returncode: raise RuntimeError('Public-key enrollment failed')
    return pinned_node(info,username,identity,candidate)

def pinned_node(info,username,identity,candidate):
    fields=candidate['host_key'].split()
    alias='spark-link-'+info['machine_id']
    known=Path.home()/'.ssh/known_hosts'
    line=alias+' '+fields[1]+' '+fields[2]
    previous=known.read_text() if known.exists() else ''
    if line not in previous.splitlines():
        with known.open('a') as stream: stream.write(('\n' if previous and not previous.endswith('\n') else '')+line+'\n')
        known.chmod(0o600)
    address=info.get('management_ip') or info['hostname']+'.local'
    node={'id':'pending','name':'Новый Spark','local':False,'ssh':username+'@'+address,'identity':str(identity),
          'machine_id':info['machine_id'],'credential_id':info['machine_id'],'host_key_alias':alias,'host_key_id':candidate['key_id']}
    verified=probe(node)
    if not verified.get('online'): raise RuntimeError('The authorized Spark could not be reached on its management address')
    return verified

def trusted_node(candidate):
    info=candidate['device']
    if not info.get('online') or 'GB10' not in info.get('gpu','') or not re.fullmatch(r'[a-f0-9]{16,64}',info.get('machine_id','')):
        raise RuntimeError('The trusted device has not passed Spark verification')
    identity=ensure_identity()
    public=identity.with_suffix('.pub').read_text().strip()
    from .inventory import node_ssh
    command='python3 -c '+shlex.quote(ENROLL)+' '+shlex.quote(base64.b64encode(public.encode()).decode())
    subprocess.run(node_ssh(info)+[command],check=True,capture_output=True,text=True,timeout=35)
    return pinned_node(info,info['user'],identity,candidate)
