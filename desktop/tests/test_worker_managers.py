from pathlib import Path
import unittest
from spark_link.multi import manager_base

class WorkerManagerTests(unittest.TestCase):
    def test_third_worker_keeps_its_own_binary_manifest(self):
        base=Path.home()/'.local/share/connect-dual-spark'
        self.assertEqual(manager_base({}),base)
        self.assertEqual(manager_base({'manager_base':str(base/'pairs/worker3')}),base/'pairs/worker3')
        with self.assertRaises(ValueError): manager_base({'manager_base':'/tmp/arbitrary-manager'})
