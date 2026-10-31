import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from spark_link.launch_profiles import apply_profile

class LaunchProfileTests(unittest.TestCase):
 def fixture(self,root):
  root=Path(root);model=root/'model.gguf';model.write_bytes(b'GGUF-memory-fixture')
  binary=root/'llama-server';binary.write_bytes(b'verified-runtime')
  profile={'enabled':True,'name':'long-context-f16','model':str(model.resolve()),'model_size':model.stat().st_size,'header_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),
    'context':1048576,'dtype':'f16','binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
    'node_ids':['head','worker2','worker3'],'endpoints':['10.100.32.2:50053','10.100.34.2:50053'],'required_gib':[90,95,96],'reserve_gib':4,
    'split':[28,34,38],'batch':128,'ubatch':16,'parallel':1,'tensor_override':r'blk\.(47|51)\.attn_.*=RPC0[10.100.32.2:50053]','no_rpc_graph_cache':True}
  command=[str(binary),'-m',str(model),'-c','1048576','--rpc',','.join(profile['endpoints']),'--device','CUDA0,RPC0,RPC1','--tensor-split','28,36,36','--flash-attn','off','--parallel','4','-b','2048','-ub','512','--cache-type-k','f16','--cache-type-v','f16','--chat-template-kwargs','{"reasoning_effort":"high"}']
  return profile,command
 def nodes(self): return [{'id':n,'available_gib':110} for n in ('head','worker2','worker3')]
 def test_verified_profile_keeps_model_context_precision_and_reasoning(self):
  with tempfile.TemporaryDirectory() as d:
   profile,cmd=self.fixture(d)
   with patch('spark_link.launch_profiles.read_json',return_value={'profiles':[profile]}):
    out=apply_profile(cmd,self.nodes())
   self.assertEqual(out[out.index('-c')+1],'1048576');self.assertEqual(out[out.index('-ub')+1],'16')
   self.assertEqual(out[out.index('--parallel')+1],'1');self.assertEqual(out[out.index('--flash-attn')+1],'on')
   self.assertEqual(out[out.index('--cache-type-k')+1],'f16');self.assertIn('{"reasoning_effort":"high"}',out)
   self.assertEqual(out[out.index('--tensor-split')+1],'28,34,38')
 def test_other_models_are_untouched(self):
  with tempfile.TemporaryDirectory() as d:
   p,cmd=self.fixture(d);cmd[2]='/unrelated.gguf'
   with patch('spark_link.launch_profiles.read_json',return_value={'profiles':[p]}): self.assertIsNone(apply_profile(cmd,self.nodes()))
 def test_changed_binary_or_insufficient_ram_fails_before_exec(self):
  with tempfile.TemporaryDirectory() as d:
   p,cmd=self.fixture(d)
   with patch('spark_link.launch_profiles.read_json',return_value={'profiles':[p]}):
    nodes=self.nodes();nodes[2]['available_gib']=99
    with self.assertRaisesRegex(RuntimeError,'memory'): apply_profile(cmd,nodes)
    Path(cmd[0]).write_bytes(b'new-runtime')
    with self.assertRaisesRegex(RuntimeError,'runtime'): apply_profile(cmd,self.nodes())
 def test_missing_worker_is_not_silently_used_for_a_million_context(self):
  with tempfile.TemporaryDirectory() as d:
   p,cmd=self.fixture(d)
   with patch('spark_link.launch_profiles.read_json',return_value={'profiles':[p]}):
    with self.assertRaisesRegex(RuntimeError,'three|devices'): apply_profile(cmd,self.nodes()[:2])
 def test_cpu_offload_cannot_bypass_the_calibrated_budget(self):
  with tempfile.TemporaryDirectory() as d:
   p,cmd=self.fixture(d)
   with patch('spark_link.launch_profiles.read_json',return_value={'profiles':[p]}):
    with self.assertRaisesRegex(RuntimeError,'not calibrated'): apply_profile(cmd+['--cpu-moe'],self.nodes())
 def test_cache_precision_is_not_silently_changed(self):
  with tempfile.TemporaryDirectory() as d:
   p,cmd=self.fixture(d);cmd[cmd.index('--cache-type-k')+1]='q8_0'
   with patch('spark_link.launch_profiles.read_json',return_value={'profiles':[p]}): self.assertIsNone(apply_profile(cmd,self.nodes()))
 def test_calibrated_layout_replaces_the_linear_preflight_for_its_model_only(self):
  from spark_link import model_policy
  with tempfile.TemporaryDirectory() as d:
   p,cmd=self.fixture(d)
   def settings(path,default=None): return {'models':[]} if Path(path).name=='model-policies.json' else {'profiles':[p]}
   with patch('spark_link.model_policy.read_json',side_effect=settings),patch('spark_link.launch_profiles.read_json',return_value={'profiles':[p]}),patch('spark_link.model_policy.available_nodes',return_value=self.nodes()),patch('spark_link.model_policy.allocate',side_effect=AssertionError('Linear estimator must not reject a calibrated layout')):
    out=model_policy.apply_saved(cmd,cmd[1:])
   self.assertEqual(out[out.index('-ub')+1],'16')
