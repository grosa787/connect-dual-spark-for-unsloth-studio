import json
import unittest

from dual_spark.discovery import candidate_links, peer_candidates, route_uses_link


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.addresses = json.dumps(
            [
                {
                    "ifname": "enP7s7",
                    "flags": ["UP", "LOWER_UP"],
                    "addr_info": [
                        {"family": "inet", "local": "192.168.150.90", "prefixlen": 24}
                    ],
                },
                {
                    "ifname": "enp1s0f0np0",
                    "flags": ["UP", "LOWER_UP"],
                    "addr_info": [
                        {"family": "inet", "local": "10.100.32.1", "prefixlen": 24}
                    ],
                },
                {
                    "ifname": "enP2p1s0f0np0",
                    "flags": ["UP", "LOWER_UP"],
                    "addr_info": [
                        {"family": "inet", "local": "10.100.33.1", "prefixlen": 24}
                    ],
                },
                {
                    "ifname": "enp1s0f1np1",
                    "flags": ["UP"],
                    "addr_info": [],
                },
            ]
        )

    def test_only_up_connectx_interfaces_with_usable_speed(self):
        speeds = {
            "enP7s7": 1000,
            "enp1s0f0np0": 200000,
            "enP2p1s0f0np0": 200000,
            "enp1s0f1np1": 200000,
        }
        links = candidate_links(self.addresses, speeds)
        self.assertEqual(
            [(x.interface, x.address) for x in links],
            [
                ("enp1s0f0np0", "10.100.32.1"),
                ("enP2p1s0f0np0", "10.100.33.1"),
            ],
        )

    def test_connectx_interface_name_can_vary_between_sparks(self):
        addresses = json.dumps([{"ifname": "cx7custom0", "flags": ["LOWER_UP"], "addr_info": [{"family": "inet", "local": "10.42.0.1", "prefixlen": 30}]}])
        links = candidate_links(addresses, {"cx7custom0": 200000})
        self.assertEqual(links[0].address, "10.42.0.1")

    def test_neighbor_candidates_ignore_lan_and_failed_entries(self):
        link = candidate_links(self.addresses, {"enp1s0f0np0": 200000})[0]
        neighbors = json.dumps(
            [
                {"dst": "10.100.32.2", "state": ["STALE"]},
                {"dst": "10.100.32.3", "state": ["FAILED"]},
                {"dst": "192.168.150.49", "state": ["REACHABLE"]},
            ]
        )
        self.assertEqual(peer_candidates(link, neighbors), ["10.100.32.2"])

    def test_route_must_stay_on_selected_connectx_interface(self):
        link = candidate_links(self.addresses, {"enp1s0f0np0": 200000})[0]
        self.assertTrue(
            route_uses_link(
                link,
                json.dumps([{"dst": "10.100.32.2", "dev": "enp1s0f0np0", "prefsrc": "10.100.32.1"}]),
            )
        )
        self.assertFalse(
            route_uses_link(
                link,
                json.dumps([{"dst": "10.100.32.2", "dev": "enP7s7", "prefsrc": "192.168.150.90"}]),
            )
        )


if __name__ == "__main__":
    unittest.main()
