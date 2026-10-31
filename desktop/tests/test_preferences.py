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
        # Rear I/O sits below the case centre; Rz(90) maps (x,y) to (-y,x).
        # A 49.75 mm lift keeps the 150 mm-wide shell on the same ground plane.
        for port in (0,1):
            x,y,z=port_anchor(port,False)
            self.assertEqual((x,y,z),(28+24*port,-11,92))
            self.assertEqual(port_anchor(port,True),(-y,49.75+x,z))

    def test_unknown_preferences_cannot_change_topology_or_create_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            preferences=ViewPreferences(Path(directory)/'preferences.json')
            with self.assertRaises(ValueError): preferences.set_orientation('remote-command',True)
            with self.assertRaises(ValueError): preferences.set_language('unknown')
