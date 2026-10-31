import copy
import unittest
from spark_link.topology import default_topology, validate_topology, select_port, resize_topology


class TriangleEditingTests(unittest.TestCase):
    def test_third_device_uses_free_ports_without_changing_the_working_pair(self):
        for head_port in (0,1):
            for worker_port in (0,1):
                value=default_topology()
                value['cables'][0].update(a_port=head_port,b_port=worker_port)
                value['nodes'][1]['ssh']='existing-worker'
                result=resize_topology(value,3)
                self.assertEqual(result['cables'][0],value['cables'][0])
                self.assertEqual(result['cables'][1]['a_port'],1-head_port)
                self.assertEqual(result['cables'][2]['a_port'],1-worker_port)
                self.assertEqual(result['nodes'][1],value['nodes'][1])
                validate_topology(result,require_targets=False)
                self.assertEqual(resize_topology(result,2),value)

    def test_every_device_connects_to_both_others_on_two_unique_ports(self):
        topology=default_topology(3)
        validate_topology(topology,require_targets=False)
        for node in topology['nodes']:
            peers=set(); ports=set()
            for cable in topology['cables']:
                for side,other in (('a','b'),('b','a')):
                    if cable[side]==node['id']:
                        peers.add(cable[other]); ports.add(cable[side+'_port'])
            self.assertEqual(peers,{n['id'] for n in topology['nodes']}-{node['id']})
            self.assertEqual(ports,{0,1})

    def test_selecting_occupied_port_swaps_only_that_devices_endpoints(self):
        original=default_topology(3)
        before=copy.deepcopy(original)
        changed=select_port(original,0,'a',1)
        self.assertEqual(changed['cables'][0]['a_port'],1)
        self.assertEqual(changed['cables'][1]['a_port'],0)
        self.assertEqual(changed['cables'][2],original['cables'][2])
        self.assertEqual(changed['cables'][0]['b_port'],original['cables'][0]['b_port'])
        self.assertEqual(original,before)
        validate_topology(changed,require_targets=False)

    def test_all_endpoint_swaps_preserve_the_complete_triangle(self):
        value=default_topology(3)
        for index in range(3):
            for side in ('a','b'):
                value=select_port(value,index,side,1-value['cables'][index][side+'_port'])
                validate_topology(value,require_targets=False)
        for index,side,port in ((-1,'a',0),(3,'a',0),(0,'x',0),(0,'a',True)):
            with self.assertRaises(ValueError): select_port(value,index,side,port)

    def test_chain_is_not_a_valid_three_device_cluster(self):
        value=default_topology(3); value['cables'].pop()
        with self.assertRaisesRegex(ValueError,'треугольник'):
            validate_topology(value,require_targets=False)
