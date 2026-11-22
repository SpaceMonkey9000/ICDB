"""Check that the files ICDB and ICOCR share are byte-identical in both applications.

Usage:  python tools/check_shared_files.py [OTHER_APPLICATION_FOLDER]

Without an argument the other application is looked for next to this one (a
folder named ICDB or ICOCR), or in the ICSUITE_ICDB / ICSUITE_ICOCR environment
variables. Exit status 0 when every shared file matches, 1 when any differs or is
missing, 2 when the other application cannot be found.

This file is shared as well: keep it identical in both applications.
"""
import hashlib
import os
import sys
from pathlib import Path

SHARED_FILES = (
    'shared_data.py',
    'data_lock.py',
    'reference_images.py',
    'tools/check_shared_files.py',
    'tests/test_shared_data.py',
    'tests/test_data_contract.py',
)


def application_name(folder):
    folder = Path(folder)
    if (folder/'icdb_qt.py').is_file():
        return 'ICDB'
    if (folder/'qt_full.py').is_file():
        return 'ICOCR'
    return None


def find_other(this, environ=None):
    """The other application's folder, or None."""
    env = os.environ if environ is None else environ
    name = application_name(this)
    other = {'ICDB': 'ICOCR', 'ICOCR': 'ICDB'}.get(name)
    if other is None:
        return None
    candidates = [env.get('ICSUITE_' + other), Path(this).resolve().parent/other]
    for candidate in candidates:
        if candidate and application_name(candidate) == other:
            return Path(candidate).resolve()
    return None


def differences(first, second):
    """Shared files that differ or are missing, as readable lines."""
    problems = []
    for name in SHARED_FILES:
        a, b = Path(first)/name, Path(second)/name
        if not a.is_file() or not b.is_file():
            missing = [str(p) for p in (a, b) if not p.is_file()]
            problems.append(f'{name}: missing in {", ".join(missing)}')
        elif hashlib.sha256(a.read_bytes()).digest() != hashlib.sha256(b.read_bytes()).digest():
            problems.append(f'{name}: differs between {first} and {second}')
    return problems


def main(argv):
    this = Path(__file__).resolve().parent.parent
    other = Path(argv[1]).resolve() if len(argv) > 1 else find_other(this)
    if other is None or application_name(other) is None:
        print('The other application (ICDB or ICOCR) was not found. Pass its folder as an argument.')
        return 2
    problems = differences(this, other)
    for line in problems:
        print(line)
    if not problems:
        print(f'{len(SHARED_FILES)} shared files are identical in {this.name} and {other.name}.')
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
