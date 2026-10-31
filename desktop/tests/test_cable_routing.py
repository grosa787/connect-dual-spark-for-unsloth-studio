import unittest
from spark_link.cable_path import cable_points

class CableRoutingTests(unittest.TestCase):
    def test_triangle_cables_clear_every_flat_chassis(self):
        positions=((-155,50),(155,50),(0,-200))
        # Each vertex uses both physical ports. Test both port assignments.
        for offsets in ((28,52),(52,28)):
            links=[((-155+offsets[0],-11,142),(155+offsets[0],-11,142)),
                   ((-155+offsets[1],-11,142),(offsets[0],-11,-108)),
                   ((155+offsets[1],-11,142),(offsets[1],-11,-108))]
            for start,end in links:
                points=cable_points(start,end)
                self.assertEqual(points[0],start)
                self.assertEqual(points[-1],end)
                for x,y,z in points:
                    for cx,cz in positions:
                        self.assertFalse(abs(x-cx)<78 and abs(z-cz)<78 and -26<y<26,
                                         f'Cable passes through a case: {(x,y,z)}')

    def test_upright_endpoints_and_reversed_links_are_preserved(self):
        for start,end in (((-144,77.75,142),(11,101.75,-108)),
                          ((166,101.75,142),(11,77.75,-108))):
            points=cable_points(start,end)
            self.assertEqual(points[0],start); self.assertEqual(points[-1],end)
            self.assertEqual(cable_points(end,start),list(reversed(points)))
            self.assertTrue(all(-160<y<160 for x,y,z in points))
