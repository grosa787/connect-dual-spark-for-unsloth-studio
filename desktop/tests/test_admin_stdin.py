import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from spark_link import admin

class AdminInputTests(unittest.TestCase):
    def test_cached_sudo_cannot_forward_password_to_root_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            sudo=root/'sudo'
            sudo.write_text('''#!/bin/sh
for arg in "$@"; do
    if [ "$arg" = -v ]; then
        IFS= read -r credential
        [ "$credential" = dummy-credential ] || exit 1
        printf '%s' "$PPID" > "$SPARK_LINK_TEST_STAMP"
        exit 0
    fi
done
[ "$(cat "$SPARK_LINK_TEST_STAMP")" = "$PPID" ] || exit 9
if IFS= read -r unexpected; then printf 'credential reached target stdin'; exit 8; fi
printf 'safe'
''')
            sudo.chmod(0o700)
            class DummyVault:
                def get(self,identity): return 'dummy-credential'
            env={'PATH':str(root)+os.pathsep+os.defpath,'SPARK_LINK_TEST_STAMP':str(root/'stamp')}
            with patch.object(admin,'Vault',DummyVault),patch.dict(os.environ,env):
                result=admin.privileged({'local':True,'machine_id':'fixture'},['/bin/true'],capture=True)
            self.assertEqual(result.stdout,'safe')
