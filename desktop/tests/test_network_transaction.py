import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from spark_link import network_helper as helper


@unittest.skipUnless(importlib.util.find_spec('yaml'), 'system PyYAML is provided by netplan on Ubuntu')
class TransactionTests(unittest.TestCase):
    def test_failed_apply_restores_original_netplan(self):
        from spark_link.topology import compile_topology, default_topology
        topology=default_topology(); topology['nodes'][1]['ssh']='worker2'
        plan=compile_topology(topology)['head']
        with tempfile.TemporaryDirectory() as temp:
            destination=Path(temp)/'99-cluster.yaml'
            backups=Path(temp)/'backups'
            original='network:\n  version: 2\n  ethernets:\n    enP7s7:\n      dhcp4: true\n'
            destination.write_text(original)
            calls=[]
            def run(argv, **kwargs):
                calls.append(argv)
                if argv==['pgrep','-x','llama-server']: return subprocess.CompletedProcess(argv,1)
                if argv==['netplan','apply'] and calls.count(argv)==1:
                    raise subprocess.CalledProcessError(1,argv)
                return subprocess.CompletedProcess(argv,0)
            read=Path.read_text
            def read_text(path,*args,**kwargs):
                return '1' if str(path).startswith('/sys/class/net/') else read(path,*args,**kwargs)
            with patch.object(helper,'DESTINATION',destination), patch.object(helper,'BACKUPS',backups), patch.object(helper.subprocess,'run',side_effect=run), patch.object(helper.subprocess,'check_output',return_value='driver: mlx5_core'), patch.object(Path,'read_text',read_text):
                with self.assertRaises(subprocess.CalledProcessError): helper.apply(plan)
            self.assertEqual(destination.read_text(),original)
            self.assertEqual(calls.count(['netplan','apply']),2)
            self.assertEqual(len(list(backups.glob('*.json'))),1)

    def test_active_model_refuses_before_any_file_write(self):
        from spark_link.topology import compile_topology,default_topology
        topology=default_topology(); topology['nodes'][1]['ssh']='worker2'
        with tempfile.TemporaryDirectory() as temp:
            destination=Path(temp)/'netplan.yaml'
            with patch.object(helper,'DESTINATION',destination), patch.object(helper.subprocess,'run',return_value=subprocess.CompletedProcess([],0)):
                with self.assertRaisesRegex(RuntimeError,'выгрузите'): helper.apply(compile_topology(topology)['head'])
            self.assertFalse(destination.exists())
