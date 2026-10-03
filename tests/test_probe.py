import json
import unittest
from unittest.mock import patch

from dual_spark.probe import ClusterProbe


class ProbeTests(unittest.TestCase):
    def test_stale_neighbor_does_not_hide_the_actual_peer(self):
        def run(argv, **_kwargs):
            command = " ".join(argv)
            if argv[:4] == ["ip", "-j", "-4", "addr"]:
                return '[{"ifname":"cx7a","flags":["LOWER_UP"],"addr_info":[{"family":"inet","local":"10.42.0.1","prefixlen":30}]}]'
            if argv[:2] == ["ethtool", "-i"] or "ethtool -i cx7b" in command:
                return "driver: mlx5_core\n"
            if argv[0] == "ethtool" or "ethtool cx7b" in command:
                return "Speed: 200000Mb/s\n"
            if argv[:3] == ["ip", "-j", "neigh"]:
                return '[{"dst":"10.42.0.3","state":["STALE"]}]'
            if argv[:4] == ["ip", "-j", "route", "get"]:
                return '[{"dev":"cx7a","prefsrc":"10.42.0.1"}]'
            if argv[0] == "ssh" and "10.42.0.3" in argv:
                raise OSError("stale neighbor")
            if "id -un" in command:
                return "worker\n"
            if "printf %s" in command:
                return "/home/worker"
            if "hostname" in command:
                return "spark-worker\n"
            if "ip -j route get" in command:
                return '[{"dev":"cx7b","prefsrc":"10.42.0.2"}]'
            raise AssertionError(argv)

        with patch("dual_spark.probe._scan_link", return_value=["10.42.0.2"]) as scan:
            peer = ClusterProbe(run).detect()
        self.assertEqual(peer.worker_ip, "10.42.0.2")
        scan.assert_called_once()

    def test_auto_detects_worker_only_through_connectx_and_ssh(self):
        calls = []

        def run(argv, **_kwargs):
            calls.append(argv)
            joined = " ".join(argv)
            if argv[:4] == ["ip", "-j", "-4", "addr"]:
                return json.dumps(
                    [
                        {"ifname": "enP7s7", "flags": ["UP", "LOWER_UP"], "addr_info": [{"family": "inet", "local": "192.168.150.90", "prefixlen": 24}]},
                        {"ifname": "cx7custom0", "flags": ["UP", "LOWER_UP"], "addr_info": [{"family": "inet", "local": "10.100.32.1", "prefixlen": 24}]},
                    ]
                )
            if argv[:2] == ["ethtool", "-i"]:
                return "driver: r8169\n" if argv[2] == "enP7s7" else "driver: mlx5_core\n"
            if argv[:1] == ["ethtool"]:
                return "Speed: 200000Mb/s\nLink detected: yes\n"
            if argv[:4] == ["ip", "-j", "neigh", "show"]:
                return '[{"dst":"10.100.32.2","state":["STALE"]}]'
            if argv[:4] == ["ip", "-j", "route", "get"]:
                return '[{"dst":"10.100.32.2","dev":"cx7custom0","prefsrc":"10.100.32.1"}]'
            if argv[0] == "ssh":
                self.assertIn("-b", argv)
                self.assertIn("BindInterface=cx7custom0", joined)
                self.assertIn("10.100.32.1", argv)
                self.assertIn("10.100.32.2", argv)
                if "ip -j route get" in joined:
                    return '[{"dst":"10.100.32.1","dev":"cx7custom1","prefsrc":"10.100.32.2"}]'
                if "ethtool -i cx7custom1" in joined:
                    return "driver: mlx5_core\n"
                if "ethtool cx7custom1" in joined:
                    return "Speed: 200000Mb/s\nLink detected: yes\n"
                if "id -un" in joined:
                    return "spark2\n"
                if "printf %s" in joined:
                    return "/home/spark2"
                if "hostname" in joined:
                    return "spark-793d\n"
            raise AssertionError(argv)

        peer = ClusterProbe(run).detect()
        self.assertEqual(peer.host_ip, "10.100.32.1")
        self.assertEqual(peer.worker_ip, "10.100.32.2")
        self.assertEqual(peer.worker_user, "spark2")
        self.assertEqual(peer.worker_home, "/home/spark2")
        self.assertFalse(any("192.168.150.49" in " ".join(c) for c in calls))


if __name__ == "__main__":
    unittest.main()
