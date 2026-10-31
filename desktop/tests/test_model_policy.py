import unittest
from spark_link.model_policy import matched_policy, planned_command

class PolicyTests(unittest.TestCase):
    def policy(self):
        return {'repo':'owner/model-GGUF','files':['Q8_0/Model-Q8_0.gguf'],'weights_gib':150,'kv_gib':27,'context':1048576,'dtype':'f16','percents':{'head':43,'worker2':57},'head_reserve':24,'worker_reserve':8,'auto_topology':True}
    def test_policy_matches_exact_repo_and_variant_only(self):
        path='/home/u/.cache/huggingface/hub/models--owner--model-GGUF/snapshots/abc/Q8_0/Model-Q8_0.gguf'
        self.assertIsNotNone(matched_policy([self.policy()],['-m',path]))
        self.assertIsNone(matched_policy([self.policy()],['-m',path.replace('owner--','other--')]))
        self.assertIsNone(matched_policy([self.policy()],['-m',path.replace('Q8_0.gguf','Q4_0.gguf')]))
    def test_saved_percentages_replace_stale_split_and_preserve_context(self):
        nodes=[{'id':'head','available_gib':115},{'id':'worker2','available_gib':116,'rpc':'10.100.32.2:50053'}]
        command=planned_command(['/binary','-m','/model.gguf','--rpc','192.168.1.2:1','--tensor-split','1,1','-c','8192'],self.policy(),nodes)
        self.assertNotIn('192.168.1.2:1',command)
        self.assertEqual(command[command.index('--tensor-split')+1],'43,57')
        self.assertEqual(command[command.index('-c')+1],'1048576')
    def test_topology_change_recalculates_with_primary_reserve(self):
        nodes=[{'id':'head','available_gib':115},{'id':'worker2','available_gib':116,'rpc':'10.100.32.2:50053'},{'id':'worker3','available_gib':116,'rpc':'10.100.34.2:50053'}]
        command=planned_command(['/binary','-m','/model.gguf'],self.policy(),nodes)
        split=list(map(float,command[command.index('--tensor-split')+1].split(',')))
        self.assertLess(split[0],split[1])
        self.assertAlmostEqual(sum(split),100,places=4)
    def test_capacity_failure_stops_before_model_execution(self):
        with self.assertRaisesRegex(RuntimeError,'memory'):
            planned_command(['/binary'],self.policy(),[{'id':'head','available_gib':10},{'id':'worker2','available_gib':10,'rpc':'10.100.32.2:50053'}])
