from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from spark_link import model_policy


class HelperUpdateTests(unittest.TestCase):
    def test_app_refreshes_manager_helpers_without_replacing_custom_launch_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'core'; source.mkdir(); target=root/'installed'; target.mkdir()
            for name in ('fastload.py','fastload_manager.py','update_proxy.py'): (source/name).write_text('new '+name)
            (source/'patches').mkdir(); (source/'patches/rpc-async-staging.patch').write_text('new patch')
            (target/'fastload.py').write_text('old helper')
            private={'llama-server-wrapper.py':'custom launcher','llama-server-wrapper.json':'custom config','model-placement.json':'custom rules'}
            for name,content in private.items(): (target/name).write_text(content)
            with patch.object(model_policy,'BASE',target):
                model_policy.sync_manager_helpers(source)
                model_policy.sync_manager_helpers(source)
            self.assertEqual((target/'fastload.py').read_text(),'new fastload.py')
            self.assertEqual((target/'fastload.py.bak').read_text(),'old helper')
            self.assertEqual((target/'patches/rpc-async-staging.patch').read_text(),'new patch')
            self.assertEqual((target/'fastload.py').stat().st_mode&0o777,0o600)
            self.assertEqual((target/'fastload_manager.py').stat().st_mode&0o777,0o700)
            for name,content in private.items(): self.assertEqual((target/name).read_text(),content)
