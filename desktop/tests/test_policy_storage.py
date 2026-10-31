from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from spark_link import model_policy as policy
from spark_link.state import write_json,read_json

class PolicyStorageTests(unittest.TestCase):
    def test_only_selected_model_rule_changes_and_removal_restores_it(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            placement=base/'model-placement.json'
            original={'version':1,'entries':{'owner/model-GGUF:Q8_0':{'mode':'first','custom':'keep'},'other/model:Q4_0':{'mode':'first'}}}
            write_json(placement,original)
            record={'repo':'owner/model-GGUF','variant':'Q8_0','files':['Model-Q8_0.gguf'],'weights_gib':12,'kv_gib':1,'context':4096,'dtype':'f16','percents':{'head':40,'worker2':60}}
            with patch.object(policy,'BASE',base),patch.object(policy,'POLICIES',base/'plans.json'),patch.object(policy,'install_gateway'):
                policy.save_policy(record,2)
                changed=read_json(placement)
                self.assertEqual(changed['entries']['owner/model-GGUF:Q8_0']['mode'],'both')
                self.assertEqual(changed['entries']['other/model:Q4_0'],original['entries']['other/model:Q4_0'])
                policy.remove_policy('owner/model-GGUF:Q8_0')
            self.assertEqual(read_json(placement),original)
