"""Headless regression tests for pinout crash-recovery journals."""
import json
import tempfile
from pathlib import Path
from qt_draft_store import (draft_file, write_draft, read_draft, delete_draft,
                            draft_is_current)


def test_draft_roundtrip():
    with tempfile.TemporaryDirectory() as folder:
        a = draft_file(folder, Path(folder) / 'a.sqlite')
        b = draft_file(folder, Path(folder) / 'b.sqlite')
        assert a != b
        payload = dict(new=False, definition_id=5, base_revision=3,
                       base_members=[1, 2], draft_members=[2, 3],
                       raw={'title': 'Testing', 'pins': [['1','VCC','Power','']]})
        write_draft(a, payload)
        assert read_draft(a)['raw']['title'] == 'Testing'
        assert draft_is_current(read_draft(a), 3, {1,2})
        assert not draft_is_current(read_draft(a), 4, {1,2})
        assert not draft_is_current(read_draft(a), 3, {1,3})
        write_draft(a, {**payload,'raw':{'title':'Changed','pins':[]}})
        assert read_draft(a)['raw']['title'] == 'Changed'
        assert not list(Path(folder).glob('*.tmp'))
        delete_draft(a)
        assert read_draft(a) is None


def test_draft_new_and_invalid():
    with tempfile.TemporaryDirectory() as folder:
        a = draft_file(folder, Path(folder) / 'database.sqlite')
        write_draft(a, dict(new=True, definition_id=None,
                            base_revision=None, base_members=[], draft_members=[], raw={}))
        assert draft_is_current(read_draft(a), None, set())
        a.write_text('{ not json', encoding='utf-8')
        try:
            read_draft(a)
        except json.JSONDecodeError:
            pass
        else:
            raise AssertionError('Corrupted draft was silently accepted')


if __name__ == '__main__':
    test_draft_roundtrip()
    test_draft_new_and_invalid()
    print('Draft recovery tests passed')
