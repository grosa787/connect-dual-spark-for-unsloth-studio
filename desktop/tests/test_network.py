import unittest
from spark_link.network_helper import checked_plan, network_document

class NetworkTests(unittest.TestCase):
    def plan(self):
        return {'version': 1, 'node': 'head', 'interfaces': {'enp1s0f0np0': ['10.100.32.1/24'], 'enp1s0f1np1': [], 'enP2p1s0f0np0': ['10.100.33.1/24'], 'enP2p1s0f1np1': []}}
    def test_management_interface_cannot_be_overwritten(self):
        plan = self.plan()
        plan['interfaces']['enP7s7'] = ['192.0.2.10/24']
        with self.assertRaises(ValueError): checked_plan(plan)
    def test_only_cluster_subnets_are_accepted(self):
        plan = self.plan()
        plan['interfaces']['enp1s0f0np0'] = ['0.0.0.0/0']
        with self.assertRaises(ValueError): checked_plan(plan)
    def test_document_removes_old_addresses_but_preserves_other_networks(self):
        old = {'network': {'version': 2, 'ethernets': {'enP7s7': {'dhcp4': True}, 'enp1s0f1np1': {'addresses': ['10.100.32.1/24']}}}}
        doc = network_document(old, self.plan())
        self.assertEqual(doc['network']['ethernets']['enP7s7'], {'dhcp4': True})
        self.assertEqual(doc['network']['ethernets']['enp1s0f1np1']['addresses'], [])
        self.assertEqual(old['network']['ethernets']['enp1s0f1np1']['addresses'], ['10.100.32.1/24'])
