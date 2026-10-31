from pathlib import Path
import socket
import tempfile
import unittest
from spark_link.state import write_json,read_json
from spark_link.credentials import SecretPipe

class RecoveryTests(unittest.TestCase):
    def test_corrupt_primary_recovers_last_complete_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.json'
            write_json(path,{'version':1})
            write_json(path,{'version':2})
            path.write_bytes(b'{broken')
            self.assertEqual(read_json(path),{'version':1})
    def test_password_pipe_contains_no_secret_file_and_is_removed(self):
        password='dummy-test-credential'
        with SecretPipe(password) as pipe:
            path=Path(pipe.path)
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertEqual([p.name for p in path.parent.iterdir()],['askpass.sock'])
            with socket.socket(socket.AF_UNIX) as connection:
                connection.connect(pipe.path)
                self.assertEqual(connection.recv(1024),password.encode()+b'\n')
        self.assertFalse(path.exists())
