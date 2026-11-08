"""Shared helpers for the shipped rules (files starting with '_' are not rules)."""
import importlib.util
import re
import sys
from pathlib import Path


def load_sibling(filename, alias):
    """Import another file from this folder (rules are loaded by path, not as a package)."""
    if alias in sys.modules:
        return sys.modules[alias]
    spec = importlib.util.spec_from_file_location(alias, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


def compact(name):
    return re.sub(r'[^0-9A-Z]', '', (name or '').upper())


UNKNOWN_MANUFACTURERS = {'', 'unknown', 'unspecified', 'unspecified (kicad)'}


def known_manufacturer(name):
    """Normalised manufacturer or '' when unknown / unspecified."""
    text = (name or '').strip().casefold()
    return '' if text in UNKNOWN_MANUFACTURERS else text


def row_project(row, ctx):
    """Pin data of the definition behind a candidate row.

    Native rows carry it as row['project']; batch-review (ICPin catalog) rows are
    looked up through ctx.mappings[(catalog_id, pinout_id)]."""
    import json
    project = row.get('project')
    if project:
        return project
    cache = ctx.cache.setdefault('_row_project', {})
    ident = (row.get('catalog_id'), row.get('pinout_id'))
    if ident not in cache:
        mapping = ctx.mappings.get(ident) or {}
        try:
            cache[ident] = json.loads(mapping.get('project_json') or '{}')
        except (TypeError, ValueError):
            cache[ident] = {}
    return cache[ident]


def package_family(project, package=''):
    """('SOIC', 8) style family/count from the definition (falls back to the row's
    package label, e.g. 'SOIC-8', 'TO-220-3')."""
    fam = re.sub(r'\s+', '', str((project or {}).get('package') or '')).upper()
    count = (project or {}).get('count')
    if not fam and package:
        m = re.fullmatch(r'(.+?)-(\d+)', package.upper())
        fam, count = (m.group(1), int(m.group(2))) if m else (package.upper(), None)
    return fam, count if isinstance(count, int) else None


def row_manufacturers(row):
    """(source manufacturer, component manufacturer), both normalised ('' = unknown)."""
    return (known_manufacturer(row.get('source_manufacturer')),
            known_manufacturer(row.get('target_manufacturer', row.get('manufacturer'))))
