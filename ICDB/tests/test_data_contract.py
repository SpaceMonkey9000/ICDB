"""The DATA contract between ICDB (writer) and ICOCR (reader).

ICDB saves the DATA folder, imports components and publishes a pinout; ICOCR then
finds the same folder, the components and the published diagram. Each application
runs in its own Python process, as it does for users. Skipped when the other
application is not next to this one (or named by ICSUITE_ICDB / ICSUITE_ICOCR).

This file is shared: keep it identical in both applications.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

THIS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(THIS / 'tools'))
from check_shared_files import application_name, differences, find_other  # noqa: E402

OTHER = find_other(THIS)
APPS = {application_name(THIS): THIS, **({application_name(OTHER): OTHER} if OTHER else {})}
needs_both = pytest.mark.skipif(OTHER is None, reason='the other application (ICDB or ICOCR) is not next to this one')

PUBLISH = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
data = Path(sys.argv[2])
from builder import connect, add_device, import_file
from shared_data import data_directory, database_file, save_directory
from pinouts import Pinouts
from pin_library import Library

save_directory(data)                                   # as Settings -> Data does
database = database_file(data)
database.parent.mkdir(parents=True, exist_ok=True)
db = connect(database)
csv = data / 'parts.csv'
csv.write_text('part_number,description\nLM358,Dual operational amplifier\n', 'utf-8')
import_file(db, csv)                                   # as the Import tab does
lm358 = db.execute("SELECT id FROM components WHERE part_number='LM358'").fetchone()[0]
ne5532 = add_device(db, 'NE5532', 'Dual low-noise op-amp', 'Texas Instruments')
library = Library(Pinouts(db, data))
pinout = {'device': 'Dual op-amp', 'package': 'SOIC', 'count': 8,
          'pins': [{'number': i, 'name': name, 'role': role, 'description': ''} for i, (name, role) in
                   enumerate([('OUT1', 'Output'), ('IN1-', 'Input'), ('IN1+', 'Input'), ('V-', 'Ground'),
                              ('IN2+', 'Input'), ('IN2-', 'Input'), ('OUT2', 'Output'), ('V+', 'Power')], 1)]}
db.execute('BEGIN IMMEDIATE')
ident = library.save(pinout, None, locked=True)
row, _ = library.get(ident)
library.save_with_members(pinout, ident, row['revision'], set(), {lm358, ne5532}, locked=True)
db.commit()
result = library.publish(force=False)
print(json.dumps({'data': str(data_directory(sys.argv[1])), 'database': str(database),
                  'updated': result['updated'], 'skipped': result['skipped']}))
'''

READ = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from shared_data import data_directory, database_file
from component_catalog import Catalog
from logic_diagrams import DiagramLibrary
from reference_images import load_reference_image

data = data_directory(sys.argv[1])                     # no ICLENS_DATA: must find ICDB's saved folder
catalog = Catalog(database_file(data))
library = DiagramLibrary(data, background=False)
parts = {}
for part in ('LM358', 'NE5532'):
    records = catalog.find(part)
    choices = []
    for record in records:
        match = {'part': record['part'], 'manufacturer': record['manufacturer'], 'package': record.get('package', '')}
        for choice in library.choices({'selected_database_match': match}):
            image = load_reference_image(choice['path'], (400, 400))
            choices.append({'package': choice['package'], 'pin_count': choice['pin_count'],
                            'image': list(image.size), 'path': str(choice['path'])})
    parts[part] = {'records': [{k: r[k] for k in ('part', 'manufacturer', 'component_function')} for r in records],
                   'pinouts': choices}
library.close()
print(json.dumps({'data': str(data), 'parts': parts}))
'''


def run(app, script, data, home):
    env = dict(os.environ, LOCALAPPDATA=str(home), XDG_CONFIG_HOME=str(home),
               ICOCR_CONFIG_DIR=str(home / 'ICOCR-config'), QT_QPA_PLATFORM='offscreen',
               ICOCR_RULES_DIR=str(APPS['ICOCR'] / 'factory' / 'rules'), PYTHONDONTWRITEBYTECODE='1')
    env.pop('ICLENS_DATA', None)
    result = subprocess.run([sys.executable, '-I', '-c', script, str(app), str(data)], cwd=home,
                            env=env, capture_output=True, text=True, timeout=180)
    if result.returncode and 'ModuleNotFoundError' in result.stderr:
        pytest.skip(f'{app.name} dependencies are not installed: {result.stderr.strip().splitlines()[-1]}')
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@needs_both
def test_shared_files_are_identical():
    assert differences(THIS, OTHER) == []


@needs_both
def test_icocr_reads_what_icdb_publishes(tmp_path):
    home, data = tmp_path / 'home', tmp_path / 'DATA'
    # ICOCR chose another DATA folder earlier; ICDB's later choice must win for both.
    earlier = home / 'ICSuite' / 'data_location.json'
    earlier.parent.mkdir(parents=True)
    earlier.write_text(json.dumps({'data_folder': str(tmp_path / 'earlier-DATA')}), 'utf-8')
    published = run(APPS['ICDB'], PUBLISH, data, home)
    assert published['updated'] == 2 and not published['skipped']
    assert Path(published['data']) == data.resolve()

    read = run(APPS['ICOCR'], READ, data, home)
    assert Path(read['data']) == data.resolve()        # ICOCR follows the folder ICDB saved
    lm358, ne5532 = read['parts']['LM358'], read['parts']['NE5532']
    assert lm358['records'][0]['component_function'] == 'Dual operational amplifier'
    assert ne5532['records'][0]['manufacturer'] == 'Texas Instruments'
    for part in (lm358, ne5532):
        assert len(part['pinouts']) == 1
        pinout = part['pinouts'][0]
        assert pinout['package'].startswith('SOIC') and pinout['pin_count'] == 8
        assert Path(pinout['path']).is_relative_to(data.resolve() / 'pinouts')
        assert min(pinout['image']) > 50                  # the SVG renders
