"""Run under dbus-run-session with scratch XDG_DATA_HOME; only dummy secrets are used."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
from spark_link.credentials import Vault

assert os.environ.get('SPARK_LINK_ISOLATED_VAULT_TEST')=='1'
data=Path(os.environ['XDG_DATA_HOME'])
assert 'spark-link-vault-qa-' in str(data)
process=subprocess.run(['gnome-keyring-daemon','--unlock','--components=secrets'],input='dummy-keyring-master-passphrase\n',text=True,capture_output=True,timeout=15)
if process.returncode: raise RuntimeError('Could not initialize isolated test keyring')
time.sleep(.5)
vault=Vault()
identity='fixture-device'
secret='dummy-secret-not-user-data-9f2a'
vault.set_record(identity,{'password':secret,'identity':'/dummy/key','management_ip':'192.0.2.7'})
assert vault.get(identity)==secret
files=[p for p in data.rglob('*') if p.is_file()]
assert files and not any(secret.encode() in p.read_bytes() for p in files)
vault.delete(identity)
assert vault.get(identity) is None
print('PASS: isolated GNOME Secret Service stores and retrieves dummy credentials; secret absent from backing files; record deletion works.')
