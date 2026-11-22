import unittest
from xml.etree import ElementTree

from pinout import Pin, Project, diagram


class DfnRenderingTests(unittest.TestCase):
    def test_opposing_terminals_use_the_same_rows(self):
        for pad in (None, {'number': 'EP', 'name': 'GND'}):
            with self.subTest(exposed_pad=pad is not None):
                project = Project(package='DFN', count=4, exposed_pad=pad,
                                  pins=[Pin(number, 'Signal') for number in range(1, 5)])
                root = ElementTree.fromstring(diagram(project).svg())
                centers = []
                for terminal in root.findall('{*}polygon'):
                    ys = [float(point.split(',')[1]) for point in terminal.attrib['points'].split()]
                    centers.append((min(ys) + max(ys)) / 2)
                self.assertEqual(len(centers), 4)
                self.assertEqual(centers[:2], centers[2:][::-1])
                self.assertAlmostEqual(centers[1] - centers[0], 32)
