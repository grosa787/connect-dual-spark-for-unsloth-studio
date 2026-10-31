import unittest
from spark_link.identity import same_device, device_identity
from spark_link.credentials import credential_id

class DeviceIdentityTests(unittest.TestCase):
 def test_cloned_machine_ids_do_not_merge_different_gpus(self):
  a={'machine_id':'cloned','device_id':'gpu-a'}; b={'machine_id':'cloned','device_id':'gpu-b'}
  self.assertFalse(same_device(a,b))
  self.assertNotEqual(credential_id(a),credential_id(b))
 def test_saved_credentials_remain_at_their_original_identity(self):
  node={'machine_id':'legacy','device_id':'gpu-a','credential_id':'legacy'}
  self.assertEqual(credential_id(node),'legacy')
  self.assertEqual(device_identity(node),'gpu-a')
 def test_legacy_and_unknown_records_are_not_mistaken_for_clones(self):
  self.assertTrue(same_device({'machine_id':'a'},{'machine_id':'a'}))
  self.assertFalse(same_device({'machine_id':'a'},{'machine_id':'a','device_id':'b'}))
 def test_offline_manual_placeholder_can_be_enrolled_with_correct_username(self):
  from spark_link.identity import enrollment_slot
  nodes=[{'id':'head','local':True,'machine_id':'known'}, {'id':'worker2','machine_id':'other'}, {'id':'worker3','ssh':'spark-d983.local'}]
  current=[{'id':'head','online':True},{'id':'worker2','online':True},{'id':'worker3','online':False}]
  self.assertEqual(enrollment_slot(nodes,current,{'hostname':'spark-d983','management_ip':'192.168.1.3'}),2)
