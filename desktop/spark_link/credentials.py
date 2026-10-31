"""Secrets live in the encrypted Secret Service collection or transient local IPC, never JSON."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import socket
import struct
import tempfile
import threading

class VaultUnavailable(RuntimeError): pass

def credential_id(node):
    return node.get('machine_id') or hashlib.sha256((node.get('ssh') or 'local').encode()).hexdigest()

class Vault:
    def __init__(self,connection_factory=None):
        self.connection_factory=connection_factory
    @contextmanager
    def collection(self,unlock=True,create=False):
        try:
            import secretstorage
            connection=self.connection_factory() if self.connection_factory else secretstorage.dbus_init()
            try:
                collection=secretstorage.get_default_collection(connection) if create else secretstorage.get_collection_by_alias(connection,'default')
                # A session collection is volatile and is not encrypted durable storage.
                if '/session' in collection.collection_path: raise VaultUnavailable('Persistent keyring is required')
                if collection.is_locked():
                    if unlock: collection.unlock()
                if collection.is_locked(): raise VaultUnavailable('Keyring is locked')
                yield collection
            finally:
                connection.close()
        except VaultUnavailable: raise
        except Exception as exc:
            raise VaultUnavailable('Encrypted GNOME keyring is unavailable or locked') from exc
    def get(self,identity,unlock=True):
        with self.collection(unlock=unlock) as collection:
            items=list(collection.search_items({'application':'spark-link','device':identity}))
            if not items: return None
            text=items[0].get_secret().decode('utf-8')
            try:
                import json
                record=json.loads(text)
                return record.get('password') if isinstance(record,dict) else text
            except ValueError: return text
    def set(self,identity,password):
        with self.collection(create=True) as collection:
            collection.create_item('Spark Link — '+identity[:12],{'application':'spark-link','device':identity},password.encode('utf-8'),replace=True)
    def set_record(self,identity,record):
        import json
        self.set(identity,json.dumps(record,ensure_ascii=False))
    def delete(self,identity):
        with self.collection() as collection:
            for item in collection.search_items({'application':'spark-link','device':identity}): item.delete()

class SecretPipe:
    """Short-lived same-user Unix socket consumed only by OpenSSH askpass."""
    def __init__(self,password):
        self.secret=bytearray(password.encode('utf-8'))
        self.directory=tempfile.TemporaryDirectory(prefix='spark-link-auth-')
        self.path=str(Path(self.directory.name)/'askpass.sock')
        self.stop=threading.Event()
    def __enter__(self):
        self.socket=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.socket.bind(self.path); os.chmod(self.path,0o600)
        self.socket.listen(2); self.socket.settimeout(0.2)
        def serve():
            while not self.stop.is_set():
                try: connection,_=self.socket.accept()
                except socket.timeout: continue
                except OSError: break
                with connection:
                    if hasattr(socket,'SO_PEERCRED'):
                        _,uid,_=struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                        if uid!=os.getuid(): continue
                    connection.sendall(self.secret+b'\n')
        self.thread=threading.Thread(target=serve,daemon=True); self.thread.start()
        return self
    def __exit__(self,*args):
        self.stop.set(); self.socket.close(); self.thread.join(timeout=1)
        for i in range(len(self.secret)): self.secret[i]=0
        self.directory.cleanup()

def askpass_main():
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.connect(os.environ['SPARK_LINK_ASKPASS_SOCKET'])
        value=bytearray()
        while len(value)<65536:
            part=connection.recv(4096)
            if not part: break
            value.extend(part)
    os.write(1,value)
    for i in range(len(value)): value[i]=0
