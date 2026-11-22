from contextlib import closing
import json

import pytest

from builder import connect
from import_batch import exclude_rows, plan_file, preview_files
from pin_library import Library
from pinouts import Pinouts


def test_invalid_later_file_rolls_back_preview(tmp_path):
    csv = tmp_path / 'new.csv'
    csv.write_text('A,First\n', encoding='utf-8')
    bad = tmp_path / 'bad.json'
    bad.write_text('{}', encoding='utf-8')
    with closing(connect(tmp_path / 'components.sqlite')) as db:
        library = Library(Pinouts(db, tmp_path))
        with pytest.raises(ValueError, match=r'bad\.json: Expected an ICDB data JSON file'):
            preview_files(library, [str(csv), str(bad)], lambda *_: None)
        assert not db.execute('SELECT 1 FROM components').fetchone()
        assert not db.execute('SELECT 1 FROM sources').fetchone()


def test_changed_later_csv_rolls_back_entire_save(tmp_path):
    first = tmp_path / 'first.csv'
    second = tmp_path / 'second.csv'
    first.write_text('A,First\n', encoding='utf-8')
    second.write_text('B,Second\n', encoding='utf-8')
    with closing(connect(tmp_path / 'components.sqlite')) as db:
        library = Library(Pinouts(db, tmp_path))
        files = preview_files(library, [str(first), str(second)], lambda *_: None)
        second.write_text('C,Third\n', encoding='utf-8')
        with pytest.raises(ValueError, match=r'second\.csv: CSV content changed'), db:
            db.execute('BEGIN IMMEDIATE')
            for entry in files:
                plan_file(library, entry, replay=True)
        assert not db.execute('SELECT 1 FROM components').fetchone()
        assert not db.execute('SELECT 1 FROM sources').fetchone()

def test_filtered_csv_can_later_import_omitted_records(tmp_path):
    csv = tmp_path / 'parts.csv'
    csv.write_text('A,First\nB,Second\nC,Third\n', encoding='utf-8')
    with closing(connect(tmp_path / 'components.sqlite')) as db:
        library = Library(Pinouts(db, tmp_path))
        progress = lambda *_: None
        entry, = preview_files(library, [str(csv)], progress)
        filtered, = preview_files(library, [exclude_rows(entry, {2})], progress)
        with db:
            db.execute('BEGIN IMMEDIATE')
            plan_file(library, filtered, replay=True)
        assert [row[0] for row in db.execute('SELECT part_number FROM components ORDER BY id')] == ['A', 'C']
        complete, = preview_files(library, [str(csv)], progress)
        assert [row[2] for row in complete['rows']] == ['Already in ICDB', 'New', 'Already in ICDB']

def test_removed_json_part_drops_alias_and_assignment_but_keeps_shared_pinout(tmp_path):
    path = tmp_path / 'parts.json'
    path.write_text(json.dumps({
        'format': 'icdb-data', 'version': 3,
        'parts': [{'part_number': 'A', 'marking_aliases': [{'marking': 'ABC'}]},
                  {'part_number': 'B'}],
        'pinouts': [{'id': 'shared', 'devices': [{'part_number': 'A'}, {'part_number': 'B'}],
                     'project': {'device': 'Shared', 'package': 'DFN', 'count': 4,
                                 'pins': [{'number': i, 'name': 'NC'} for i in range(1, 5)]}}],
    }), encoding='utf-8')
    with closing(connect(tmp_path / 'components.sqlite')) as db:
        library = Library(Pinouts(db, tmp_path))
        entry, = preview_files(library, [str(path)], lambda *_: None)
        filtered, = preview_files(library, [exclude_rows(entry, {('part', 0)})], lambda *_: None)
        assert [(row[0], row[2]) for row in filtered['rows']] == [
            ('B', 'New part'), ('Shared', 'New pinout'), ('B', 'New assignment')]
        with db:
            db.execute('BEGIN IMMEDIATE')
            plan_file(library, filtered, replay=True)
        assert db.execute('SELECT COUNT(*) FROM component_marking_aliases').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM pl_assignments').fetchone()[0] == 1
