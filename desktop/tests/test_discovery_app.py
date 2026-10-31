import unittest
from spark_link.discovery import infer_topology, filter_known_candidates

class DiscoveryAppTests(unittest.TestCase):
    def test_delayed_scan_cannot_offer_an_already_discovered_worker(self):
        nodes=[{'online':True,'machine_id':'worker','interfaces':{'enp1s0f0np0':{'mac':'AA:BB'}}}]
        candidates=[{'id':'old-scan','mac':'aa:bb'},{'id':'new','mac':'cc:dd'}]
        self.assertEqual(filter_known_candidates(candidates,nodes),[candidates[1]])
        # A genuinely replaced/offline device can still be offered for authorization.
        self.assertEqual(filter_known_candidates(candidates,[{**nodes[0],'online':False}]),candidates)

    def test_logical_rails_do_not_create_duplicate_cables(self):
        head={'id':'head','local':True,'name':'head','ssh':'','interfaces':{'enp1s0f0np0':{'mac':'aa:00'},'enP2p1s0f0np0':{'mac':'aa:01'}},'neighbors':[{'dev':'enp1s0f0np0','lladdr':'bb:00'},{'dev':'enP2p1s0f0np0','lladdr':'bb:01'}]}
        worker={'id':'worker2','local':False,'name':'worker','ssh':'worker','interfaces':{'enp1s0f1np1':{'mac':'bb:00'},'enP2p1s0f1np1':{'mac':'bb:01'}},'neighbors':[]}
        result=infer_topology([head,worker])
        self.assertIsNotNone(result)
        self.assertEqual(result['cables'],[{'a':'head','a_port':0,'b':'worker2','b_port':1}])
    def test_missing_triangle_link_is_not_reported_ready(self):
        self.assertIsNone(infer_topology([{'id':'head'},{'id':'worker2'},{'id':'worker3'}]))
