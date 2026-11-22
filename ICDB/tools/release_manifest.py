"""Write RELEASE_MANIFEST.json and SHA256SUMS.txt for the files that ship.

Run from anywhere: python tools/release_manifest.py
Development-only paths (tests, tools, archive, hidden folders such as .git
and caches) are left out.
"""
import hashlib
import json
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
SKIP_DIRS = {'.git', 'tests', 'tools', 'archive', '__pycache__', '.pytest_cache'}
SKIP_FILES = {'RELEASE_MANIFEST.json', 'SHA256SUMS.txt', '.gitignore', 'requirements-dev.txt'}


def shipped_files():
    for path in sorted(APP.rglob('*')):
        rel = path.relative_to(APP)
        folders = rel.parts[:-1]
        if path.is_file() and not SKIP_DIRS.intersection(folders) \
                and not any(part.startswith('.') for part in folders) \
                and rel.name not in SKIP_FILES and path.suffix != '.pyc':
            yield rel.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    files = dict(shipped_files())
    (APP / 'RELEASE_MANIFEST.json').write_text(json.dumps(files, indent=2) + '\n', 'utf-8')
    (APP / 'SHA256SUMS.txt').write_text(''.join(f'{h}  {p}\n' for p, h in files.items()), 'utf-8')
    print(f'{len(files)} files')


if __name__ == '__main__':
    main()
