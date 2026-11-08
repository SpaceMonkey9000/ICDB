"""Component already has an accepted pinout in the same package.

BLOCK a suggestion when the component already has an Accepted pinout definition
in the same package whose supply / ground / NC layout (rule_api.class_signature)
differs - accepting it would give the part two contradicting diagrams.
CAUTION when the accepted pinout has the same canonical pin names but is a
different definition: a duplicate that should probably be merged.

Reads pl_matches / pl_definitions once per scan (prepare). Batch review of ICPin
catalogs (no pl_* tables) is not affected.
"""
from pathlib import Path
import json
import sys
from _shipped_helpers import row_project
import rule_api
from pinouts import package_name
from pinout import project_label

RULE_ID = 'already-accepted-v1'
LABEL = 'Already accepted'
RANK = 3


def prepare(ctx):
    accepted = {}
    has = {r[0] for r in ctx.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if {'pl_matches', 'pl_definitions'} <= has:
        rows = ctx.db.execute('''SELECT m.component_id,m.definition_id,d.project_json FROM pl_matches m
            JOIN pl_definitions d ON d.id=m.definition_id WHERE m.status='Accepted'
            ORDER BY m.component_id,m.definition_id''').fetchall()
        for cid, ident, project_json in rows:
            try:
                data = json.loads(project_json)
                label = package_name(project_label(data))
            except (TypeError, ValueError, KeyError):
                continue
            accepted.setdefault(cid, []).append(
                (ident, label, rule_api.class_signature(data), rule_api.canonical_signature(data)))
    ctx.cache['already-accepted'] = accepted


def review(row, ctx):
    entries = ctx.cache.get('already-accepted', {}).get(row['component_id'])
    if not entries or 'definition_id' not in row:
        return None
    project = row_project(row, ctx)
    if not project:
        return None
    classes, canon = rule_api.class_signature(project), rule_api.canonical_signature(project)
    duplicate = None
    for ident, label, cls, can in entries:
        if ident == row['definition_id'] or label != row['package']:
            continue
        if cls != classes:
            return ('caution', f'{row["target"]} already has accepted pinout #{ident} in {label} with a different '
                               'supply/NC layout; reject that link first if this one is correct.')
        if can == canon and duplicate is None:
            duplicate = ident
    if duplicate is not None:
        return ('caution', f'Duplicate definition of accepted pinout #{duplicate}; consider merging')
    return None
