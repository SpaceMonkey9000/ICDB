"""The shared DATA folder used by both ICDB and ICOCR.

This file is shared: ICDB and ICOCR each ship their own copy, and the two copies
must stay byte-identical (tools/check_shared_files.py checks this). Keep
application-specific code out of it. Nothing is written on import.

DATA folder resolution, highest priority first:
1. the ICLENS_DATA environment variable;
2. %LOCALAPPDATA%\\ICSuite\\data_location.json (written by save_directory);
3. %LOCALAPPDATA%\\IC_Tools\\data_location.json (read only, older installations);
4. %LOCALAPPDATA%\\ICSuite\\DATA for an installed exe, else a DATA folder next to
   the application folder.
"""
import json
import os
import sys
from pathlib import Path


def config_base(environ=None):
    env = os.environ if environ is None else environ
    return Path(env.get('LOCALAPPDATA') or env.get('XDG_CONFIG_HOME') or Path.home()/'.config')


def location_file(environ=None):
    """Where the chosen DATA folder is saved. Both applications read and write this file."""
    return config_base(environ)/'ICSuite'/'data_location.json'


def legacy_location_file(environ=None):
    """Older location, read only."""
    return config_base(environ)/'IC_Tools'/'data_location.json'


def data_directory(app_root, environ=None):
    env = os.environ if environ is None else environ
    if env.get('ICLENS_DATA'):
        return Path(env['ICLENS_DATA']).expanduser().resolve()
    for settings in (location_file(env), legacy_location_file(env)):
        if not settings.exists():
            continue
        try:
            # Notepad and PowerShell 5 write a UTF-8 BOM.
            value = json.loads(settings.read_text('utf-8-sig'))
        except (ValueError, OSError) as exc:
            raise ValueError(f'DATA folder setting file is unreadable: {settings}\n{exc}\n'
                             'Fix or delete this file, then restart (or choose the DATA folder again).') from exc
        value = value.get('data_folder') if isinstance(value, dict) else None
        if not isinstance(value, str) or not value.strip() or not Path(value).expanduser().is_absolute():
            raise ValueError('Invalid absolute DATA folder setting: '+str(settings))
        return Path(value).expanduser().resolve()
    if getattr(sys, 'frozen', False):
        return (config_base(env)/'ICSuite'/'DATA').resolve()
    return (Path(app_root).resolve().parent/'DATA').resolve()


def database_file(data):
    data = Path(data)
    # Preserve legacy root layout when present; otherwise use DATA/db.
    legacy = data/'components.sqlite'
    return legacy if legacy.is_file() else data/'db'/'components.sqlite'


def save_directory(folder, environ=None):
    """Save the DATA folder for both applications. Creates the standard subfolders;
    existing files are not moved."""
    folder = Path(folder).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    for name in ('db', 'models', 'pinouts', 'rules'):
        (folder/name).mkdir(exist_ok=True)
    settings = location_file(environ)
    settings.parent.mkdir(parents=True, exist_ok=True)
    temp = settings.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as handle:
        handle.write(json.dumps({'data_folder': str(folder)}, indent=2))
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(settings)
    return folder
