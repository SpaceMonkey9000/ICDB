"""DATA folder resolution shared by ICDB and ICOCR (shared_data.py).

This file is shared: keep it identical in both applications.
"""
import json
import sys

import pytest

import shared_data


def env_for(tmp_path, **extra):
    return dict({'LOCALAPPDATA': str(tmp_path / 'local')}, **extra)


def write_location(path, folder, bom=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({'data_folder': str(folder)})
    path.write_text(('﻿' if bom else '') + text, 'utf-8')


def test_environment_variable_wins(tmp_path):
    env = env_for(tmp_path, ICLENS_DATA=str(tmp_path / 'forced'))
    write_location(shared_data.location_file(env), tmp_path / 'saved')
    assert shared_data.data_directory(tmp_path / 'app', env) == (tmp_path / 'forced').resolve()


def test_saved_folder_is_shared_by_both_applications(tmp_path):
    env = env_for(tmp_path)
    saved = shared_data.save_directory(tmp_path / 'DATA', env)
    assert shared_data.location_file(env) == tmp_path / 'local' / 'ICSuite' / 'data_location.json'
    # Either application reads the folder the other saved.
    assert shared_data.data_directory(tmp_path / 'ICDB', env) == saved
    assert shared_data.data_directory(tmp_path / 'ICOCR', env) == saved
    for name in ('db', 'models', 'pinouts', 'rules'):
        assert (saved / name).is_dir()


def test_new_location_takes_precedence_over_legacy(tmp_path):
    env = env_for(tmp_path)
    write_location(shared_data.legacy_location_file(env), tmp_path / 'old')
    assert shared_data.data_directory(tmp_path / 'app', env) == (tmp_path / 'old').resolve()
    shared_data.save_directory(tmp_path / 'new', env)
    assert shared_data.data_directory(tmp_path / 'app', env) == (tmp_path / 'new').resolve()
    assert shared_data.legacy_location_file(env).exists()     # legacy file is never written or removed


def test_saved_file_with_bom_is_accepted(tmp_path):
    env = env_for(tmp_path)
    write_location(shared_data.location_file(env), tmp_path / 'DATA', bom=True)
    assert shared_data.data_directory(tmp_path / 'app', env) == (tmp_path / 'DATA').resolve()


@pytest.mark.parametrize('content', ['not json', '{"data_folder": ""}', '{"data_folder": "relative/DATA"}', '[]'])
def test_invalid_saved_file_is_reported(tmp_path, content):
    env = env_for(tmp_path)
    path = shared_data.location_file(env)
    path.parent.mkdir(parents=True)
    path.write_text(content, 'utf-8')
    with pytest.raises(ValueError, match=str(path).replace('\\', '\\\\')):
        shared_data.data_directory(tmp_path / 'app', env)


def test_defaults_without_a_saved_folder(tmp_path, monkeypatch):
    env = env_for(tmp_path)
    assert shared_data.data_directory(tmp_path / 'apps' / 'ICOCR', env) == (tmp_path / 'apps' / 'DATA').resolve()
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert shared_data.data_directory(tmp_path / 'apps' / 'ICOCR', env) == \
        (tmp_path / 'local' / 'ICSuite' / 'DATA').resolve()


def test_database_file_prefers_legacy_root_layout(tmp_path):
    assert shared_data.database_file(tmp_path) == tmp_path / 'db' / 'components.sqlite'
    (tmp_path / 'components.sqlite').write_bytes(b'')
    assert shared_data.database_file(tmp_path) == tmp_path / 'components.sqlite'
