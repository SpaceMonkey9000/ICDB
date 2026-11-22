"""Atomic, per-database draft journal for ICDB's pinout editor.

This file is intentionally independent of Qt and SQLite. No database writes occur.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile

DRAFT_VERSION = 1


def draft_file(base_dir, database_path):
    key = hashlib.sha256(str(Path(database_path).resolve()).encode('utf-8')).hexdigest()[:24]
    return Path(base_dir) / f'pinout-{key}.json'


def write_draft(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = {'version': DRAFT_VERSION, **payload}
    if content.get('version') != DRAFT_VERSION:
        raise ValueError('Unsupported draft version')
    data = json.dumps(content, ensure_ascii=False, indent=2).encode('utf-8')
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', prefix='.draft-', suffix='.tmp',
                                         dir=path.parent, delete=False) as stream:
            name = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def read_draft(path):
    path = Path(path)
    if not path.exists():
        return None
    with path.open('r', encoding='utf-8') as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or data.get('version') != DRAFT_VERSION:
        raise ValueError('Unrecognized ICDB draft file format')
    if data.get('kind') == 'pinout_session':
        if not isinstance(data.get('drafts'), dict):
            raise ValueError('Pinout session missing drafts')
    else:
        for key in ('new', 'definition_id', 'raw', 'base_members', 'draft_members'):
            if key not in data:
                raise ValueError(f'Draft missing {key}')
    return data


def delete_draft(path):
    Path(path).unlink(missing_ok=True)


def draft_is_current(draft, current_revision, current_members):
    """Reject recovery if the database changed since the draft was created."""
    if draft.get('new'):
        return draft.get('definition_id') is None
    return (str(draft.get('base_revision')) == str(current_revision)
            and set(map(int, draft['base_members'])) == set(map(int, current_members)))
