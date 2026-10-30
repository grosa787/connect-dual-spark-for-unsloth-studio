import json
import os
from pathlib import Path
import tempfile

STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'spark-link'
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'spark-link'


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        name = stream.name
    os.chmod(name, 0o600)
    os.replace(name, path)
