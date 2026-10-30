"""Dedicated SSH client metadata; never copies private keys."""
import os
from pathlib import Path
import re
import shutil
import time
from .inventory import identity_file

def ensure_cluster_ssh(nodes):
    directory=Path.home()/'.ssh'
    directory.mkdir(mode=0o700,exist_ok=True)
    lines=['# Managed by Spark Link. Private keys remain at their original location.']
    for index,node in enumerate(nodes[1:]):
        user=node['user']
        if not re.fullmatch(r'[a-z_][a-z0-9_-]*[$]?',user): raise ValueError('Некорректный пользователь SSH.')
        subnet=32+index*2
        lines += [f'Host 10.100.{subnet}.2 10.100.{subnet+1}.2',f'  User {user}']
        identity=node.get('identity') or identity_file(node['ssh'])
        if identity:
            if any(ord(c)<32 for c in identity): raise ValueError('Некорректный путь SSH-ключа.')
            escaped=identity.replace('\\','\\\\').replace('"','\\"')
            lines += ['  IdentityFile "'+escaped+'"','  IdentitiesOnly yes']
    path=directory/'spark-link.conf'
    path.write_text('\n'.join(lines)+'\n')
    path.chmod(0o600)
    config=directory/'config'
    text=config.read_text() if config.is_file() else ''
    include='Include '+str(path)
    if include not in text.splitlines():
        if config.is_file(): shutil.copy2(config,directory/('config.before-spark-link-'+str(time.time_ns())))
        temporary=directory/'.config.spark-link.new'
        temporary.write_text(include+'\n'+text)
        temporary.chmod(0o600)
        os.replace(temporary,config)
