"""Release documents agree with version.py and their relative links resolve."""
import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
DOCS = [APP / 'README.md', APP / 'CHANGELOG.md', *sorted((APP / 'docs').glob('*.md'))]


def app_version():
    return re.search(r"APP_VERSION = '([^']+)'", (APP / 'version.py').read_text('utf-8')).group(1)


def test_readme_title_and_latest_changelog_entry_match_version():
    version = app_version()
    assert (APP / 'README.md').read_text('utf-8').splitlines()[0].endswith(' ' + version)
    latest = re.search(r'^## \[([^\]]+)\]', (APP / 'CHANGELOG.md').read_text('utf-8'), re.M).group(1)
    assert latest == version


def test_relative_links_point_to_existing_files():
    missing = []
    for doc in DOCS:
        for target in re.findall(r'\]\(([^)#\s]+)(?:#[^)]*)?\)', doc.read_text('utf-8')):
            if '://' not in target and not (doc.parent / target).exists():
                missing.append(f'{doc.relative_to(APP)} -> {target}')
    assert not missing, missing
