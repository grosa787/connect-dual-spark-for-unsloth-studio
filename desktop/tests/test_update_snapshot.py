from pathlib import Path
import tempfile
import unittest
from spark_link.recovery import make_snapshot,restore_snapshot
from spark_link.state import read_json

class SnapshotTests(unittest.TestCase):
    def test_interrupted_update_restores_files_and_preserves_failed_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); runtime=root/'unsloth_studio'; runtime.mkdir(); (runtime/'version').write_text('old')
            pending=root/'pending.json'; base=root/'backups'
            record=make_snapshot([runtime],base,pending)
            (runtime/'version').write_text('incomplete-new')
            restore_snapshot(record,[runtime],base,pending)
            self.assertEqual((runtime/'version').read_text(),'old')
            self.assertIsNone(read_json(pending))
            self.assertEqual(next(root.glob('unsloth_studio.before-rollback-*')).joinpath('version').read_text(),'incomplete-new')
    def test_snapshot_cannot_restore_an_unrelated_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); runtime=root/'runtime'; runtime.mkdir()
            record=make_snapshot([runtime],root/'backups',root/'pending.json')
            record['roots'][0]['source']=str(root/'other')
            with self.assertRaises(RuntimeError): restore_snapshot(record,[runtime],root/'backups',root/'pending.json')
