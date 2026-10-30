import copy
import unittest
from spark_link.topology import default_topology, compile_topology, validate_topology, safe_target


class TopologyTests(unittest.TestCase):
    def test_two_sparks_can_use_different_physical_ports(self):
        value = default_topology()
        value['nodes'][1]['ssh'] = 'spark2@spark-793d.local'
        value['cables'][0]['b_port'] = 1
        plans = compile_topology(value)
        self.assertEqual(plans['head']['interfaces']['enp1s0f0np0'], ['10.100.32.1/24'])
        self.assertEqual(plans['worker2']['interfaces']['enp1s0f1np1'], ['10.100.32.2/24'])
        self.assertEqual(plans['worker2']['interfaces']['enp1s0f0np0'], [])

    def test_triangle_assigns_unique_networks_and_ports(self):
        value = default_topology(3)
        value['nodes'][1]['ssh'] = 'worker2'
        value['nodes'][2]['ssh'] = 'worker3'
        plans = compile_topology(value)
        self.assertEqual(plans['head']['interfaces']['enp1s0f1np1'], ['10.100.34.1/24'])
        self.assertEqual(plans['worker3']['interfaces']['enp1s0f1np1'], ['10.100.36.2/24'])

    def test_same_port_cannot_hold_two_cables(self):
        value = default_topology(3)
        value['cables'][1]['a_port'] = 0
        with self.assertRaisesRegex(ValueError, 'порт'):
            validate_topology(value, require_targets=False)

    def test_shell_arguments_and_duplicate_hosts_rejected(self):
        for target in ['-oProxyCommand=evil', 'user@host;id', 'host name', '../host']:
            with self.assertRaises(ValueError):
                safe_target(target)
        value = default_topology(3)
        value['nodes'][1]['ssh'] = value['nodes'][2]['ssh'] = 'samehost'
        with self.assertRaises(ValueError):
            validate_topology(value)

    def test_plan_does_not_modify_user_draft(self):
        value = default_topology()
        value['nodes'][1]['ssh'] = 'worker2'
        before = copy.deepcopy(value)
        compile_topology(value)
        self.assertEqual(value, before)


if __name__ == '__main__':
    unittest.main()
