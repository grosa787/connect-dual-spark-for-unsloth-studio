import json
import os
from pathlib import Path
import tempfile

STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'spark-link'
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'spark-link'


def read_json(path, default=None):
    for candidate in (Path(path),Path(str(path)+'.bak')):
        try: return json.loads(candidate.read_text())
        except (OSError,ValueError): pass
    return default


def _atomic_write(path,content):
    with tempfile.NamedTemporaryFile(mode='wb',dir=path.parent,delete=False) as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
        name=stream.name
    os.chmod(name,0o600)
    os.replace(name,path)

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        previous=path.read_bytes()
        json.loads(previous)
        _atomic_write(Path(str(path)+'.bak'),previous)
    except (OSError,ValueError): pass
    _atomic_write(path,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())
    descriptor=os.open(path.parent,os.O_RDONLY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)
