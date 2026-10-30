from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from spark_link import jobs
from spark_link.state import write_json
from spark_link.topology import default_topology

class UpdateRecoveryTests(unittest.TestCase):
    def test_official_updater_failure_restarts_studio_and_watcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            config=root/'config'; config.mkdir()
            topology=default_topology(); topology['nodes'][1]['ssh']='worker2'
            write_json(config/'topology.json',topology)
            studio=root/'unsloth'; studio.touch()
            guard=root/'llama-server-wrapper.json'; guard.write_text('{"custom":true}')
            calls=[]
            def run(argv,**kwargs):
                calls.append([str(x) for x in argv])
                if argv[0]==studio: raise subprocess.CalledProcessError(1,argv)
            idle=[{'online':True,'model_active':False}]
            with patch.object(jobs,'CONFIG',config), patch.object(jobs,'STATE',root/'state'), patch.object(jobs,'GUARD',guard), patch.object(jobs,'STUDIO',studio), patch.object(jobs,'scan',return_value=idle), patch.object(jobs,'run',side_effect=run), patch.object(jobs.subprocess,'run',return_value=subprocess.CompletedProcess([],0)):
                with self.assertRaises(subprocess.CalledProcessError): jobs.update_studio()
            self.assertIn(['systemctl','--user','start','connect-dual-spark-studio.service'],calls)
            self.assertIn(['systemctl','--user','start','connect-dual-spark-refresh.path'],calls)
            self.assertEqual(guard.read_text(),'{"custom":true}')
