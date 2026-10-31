from pathlib import Path
import tempfile
import unittest
from spark_link.preferences import ViewPreferences, port_anchor


class PreferenceTests(unittest.TestCase):
    def test_each_device_orientation_and_language_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'preferences.json'
            preferences=ViewPreferences(path)
            preferences.set_orientation('head',True)
            preferences.set_orientation('worker2',False)
            preferences.set_language('de')
            restored=ViewPreferences(path)
            self.assertEqual(restored.language,'de')
            self.assertTrue(restored.vertical('head'))
            self.assertFalse(restored.vertical('worker2'))
            self.assertFalse(restored.vertical('worker3'))

    def test_vertical_ports_follow_the_rotated_chassis(self):
        self.assertEqual(port_anchor(0,False),(28,0,92))
        self.assertEqual(port_anchor(1,False),(52,0,92))
        self.assertEqual(port_anchor(0,True),(0,72,92))
        self.assertEqual(port_anchor(1,True),(0,96,92))

    def test_unknown_preferences_cannot_change_topology_or_create_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            preferences=ViewPreferences(Path(directory)/'preferences.json')
            with self.assertRaises(ValueError): preferences.set_orientation('remote-command',True)
            with self.assertRaises(ValueError): preferences.set_language('unknown')
