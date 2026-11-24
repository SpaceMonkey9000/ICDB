"""SOT-23 variants and numbering are safe to render and import."""
from xml.etree import ElementTree
import pytest

from pinout import PACKAGES, Pin, Project, count_limits, diagram, validate_count
from pinouts import package_name
from icpin_bundle import valid_package_count


def test_sot23_supported_counts():
    assert 'SOT-23' in PACKAGES
    assert count_limits('SOT-23') == (3, 6, 1)
    for n in (3, 4, 5, 6):
        validate_count('SOT-23', n)
        assert valid_package_count('SOT-23', n)
        assert package_name(f'SOT-23-{n}') == f'SOT-23-{n}'
    for n in (2, 7):
        with pytest.raises(ValueError):
            validate_count('SOT-23', n)


@pytest.mark.parametrize('count', (3, 4, 5, 6))
def test_sot23_pin_number_positions(count):
    p = Project(device='SOT test', package='SOT-23', count=count,
                pins=[Pin(i, f'P{i}') for i in range(1, count+1)])
    scene = diagram(p)
    root = ElementTree.fromstring(scene.svg())
    assert root.attrib['viewBox'] == '0 0 450 350'
    labels = {node.text: (float(node.attrib['x']), float(node.attrib['y']))
              for node in root.findall('{*}text') if node.text in {f'P{i}' for i in range(1, count + 1)}}
    assert len(labels) == count
    lower = (count+1)//2
    for n in range(1, lower + 1):
        assert labels[f'P{n}'][1] > 239
    for n in range(lower + 1, count + 1):
        assert labels[f'P{n}'][1] < 145
    # Both lower and upper numbers follow counter-clockwise sequencing.
    assert [labels[f'P{i}'][0] for i in range(1,lower+1)] == sorted(labels[f'P{i}'][0] for i in range(1,lower+1))
    assert [labels[f'P{i}'][0] for i in range(lower+1,count+1)] == sorted((labels[f'P{i}'][0] for i in range(lower+1,count+1)),reverse=True)
