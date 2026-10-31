import unittest
import hashlib
from pathlib import Path
import tempfile
from unittest.mock import patch
from spark_link.memory_planner import parse_hf_reference, model_variants, estimate_kv, allocate
from spark_link import memory_planner
from spark_link.state import write_json

class ModelMetadataTests(unittest.TestCase):
    def test_offline_analysis_uses_last_saved_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            repo='owner/model-GGUF'
            cache=Path(directory)/'model-metadata'/(hashlib.sha256(repo.encode()).hexdigest()+'.json')
            write_json(cache,{'repo':repo,'variants':[{'label':'Q8_0'}],'max_context':32768})
            with patch.object(memory_planner,'STATE',Path(directory)), patch.object(memory_planner,'read_json_url',side_effect=OSError('offline')):
                result=memory_planner.analyze_model(repo)
            self.assertTrue(result['cached'])
            self.assertEqual(result['max_context'],32768)

    def test_hf_urls_and_ids_are_canonicalized_without_arbitrary_hosts(self):
        self.assertEqual(parse_hf_reference('https://huggingface.co/unsloth/Qwen3-0.6B-GGUF/tree/main/Q8_0')['repo'],'unsloth/Qwen3-0.6B-GGUF')
        self.assertEqual(parse_hf_reference('unsloth/Qwen3-0.6B-GGUF')['repo'],'unsloth/Qwen3-0.6B-GGUF')
        for value in ['https://example.com/user/model','https://huggingface.co@127.0.0.1/a/b','../model','http://huggingface.co/a/b']:
            with self.assertRaises(ValueError): parse_hf_reference(value)
    def test_shards_are_summed_without_projector(self):
        variants=model_variants([{'rfilename':'Q8_0/Model-Q8_0-00001-of-00002.gguf','size':3}, {'rfilename':'Q8_0/Model-Q8_0-00002-of-00002.gguf','size':4}, {'rfilename':'mmproj-F16.gguf','size':99}])
        self.assertEqual(len(variants),1)
        self.assertEqual(variants[0]['size_bytes'],7)
        self.assertTrue(variants[0]['complete'])
    def test_full_attention_kv_formula_and_unknown_compressed_architecture(self):
        meta={'general.architecture':'llama','llama.block_count':32,'llama.embedding_length':4096,'llama.attention.head_count':32,'llama.attention.head_count_kv':8}
        self.assertAlmostEqual(estimate_kv(meta,4096,'f16')['gib'],0.5)
        self.assertIsNone(estimate_kv({'general.architecture':'deepseek4'},1048576,'f16')['gib'])

class AllocationTests(unittest.TestCase):
    def test_auto_preserves_more_primary_headroom(self):
        result=allocate(150,27,[115,116],None)
        self.assertLess(result['allocations'][0]['percent'],result['allocations'][1]['percent'])
        self.assertGreater(result['allocations'][0]['remaining_gib'],result['allocations'][1]['remaining_gib'])
        self.assertTrue(result['fits'])
        self.assertAlmostEqual(sum(a['percent'] for a in result['allocations']),100)
    def test_manual_invalid_total_and_capacity_are_not_accepted(self):
        with self.assertRaises(ValueError): allocate(150,27,[115,116],[40,40])
        self.assertFalse(allocate(150,27,[115,116],[10,90])['fits'])
    def test_unknown_kv_requires_an_explicit_manual_budget(self):
        with self.assertRaises(ValueError): allocate(150,None,[115,116],None)
