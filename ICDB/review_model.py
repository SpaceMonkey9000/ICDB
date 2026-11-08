"""Pure helpers for the batch review workspace."""
import json
import re
from difflib import SequenceMatcher
from icpin_bundle import key

ACTIONABLE = {'Exact', 'Review', 'Rejected'}
QUEUES = ['Pending', 'Exact', 'Verified mappings', 'Caution', 'Rule suggestions', 'Suffix variants', 'Family suggestions',
          'Shared number only', 'Unmatched', 'Conflicts', 'Deferred', 'Linked', 'Rejected', 'All']


def group_key(row):
    return json.dumps([row['catalog_id'], row['pinout_id'], row['package']], separators=(',', ':'))


def filtered_groups(rows, filters, deferred):
    result = {}
    mode = filters.get('queue', 'Pending')
    term = filters.get('find', '').strip().casefold()
    evidence = {}
    if deferred:
        from pinout_matcher import digest
        for row in rows:
            gid = group_key(row)
            if gid in deferred: evidence.setdefault(gid, []).append((row['decision_key'],row['evidence'],row['status']))
        evidence = {gid:digest(sorted(items)) for gid,items in evidence.items()}
    for row in rows:
        gid = group_key(row)
        is_deferred = gid in deferred and deferred[gid] == evidence.get(gid)
        status = row['status']; kind = row['match_kind']
        if mode == 'Deferred':
            if not is_deferred: continue
        elif mode != 'All' and is_deferred: continue
        if mode == 'Pending' and status not in {'Exact', 'Review'}: continue
        if mode in {'Exact', 'Linked', 'Rejected', 'Unmatched'} and status != mode: continue
        if mode == 'Conflicts' and status != 'Blocked': continue
        if mode == 'Verified mappings' and (not row.get('verified') or status not in {'Exact','Review'}): continue
        if mode == 'Suffix variants' and (kind != 'Suffix variant' or status != 'Review'): continue
        if mode == 'Caution' and (not row.get('caution') or status not in {'Exact', 'Review'}): continue
        if mode == 'Rule suggestions' and (not row.get('plugin') or status != 'Review'): continue
        if mode == 'Family suggestions' and (kind not in {'Prefix variant','4000 family','Manual'} or status != 'Review'): continue
        if mode == 'Shared number only' and (kind != mode or status != 'Review'): continue
        if not filters.get('broad', False) and kind == 'Shared number only' and mode not in {'Shared number only','All','Rejected','Linked','Conflicts','Caution'}: continue
        if term and term not in ' '.join(str(row.get(k,'')) for k in ('source','target','reason','source_manufacturer','target_manufacturer')).casefold(): continue
        if any(filters.get(field,'All') not in ('All','',str(row.get(column,''))) for field,column in
               [('batch','catalog_id'),('package','package'),('pins','pin_count')]): continue
        mfr = filters.get('manufacturer','All')
        if mfr not in ('All','',row['target_manufacturer'],row['source_manufacturer']): continue
        rule = filters.get('rule','All')
        if rule not in ('All','',kind): continue
        reference = filters.get('reference','All')
        if reference == 'Missing reference' and row.get('has_reference'): continue
        if reference == 'Has reference' and not row.get('has_reference'): continue
        result.setdefault(gid,[]).append(row)
    return result


def group_evidence(rows, gid):
    # Deferrals reopen when the source, target or checked integrity changes.
    from pinout_matcher import digest
    return digest(sorted((r['decision_key'],r['evidence'],r['status']) for r in rows if group_key(r)==gid))


def resolve_parts(db, text):
    """Exact identities only. Duplicate manufacturer identities remain ambiguous."""
    tokens = list(dict.fromkeys(key(t) for t in re.split(r'[,;\s]+', text) if t.strip()))
    index = {}
    for row in db.execute('SELECT id,part_number,manufacturer FROM components'):
        index.setdefault(key(row['part_number'] or ''),[]).append(dict(row))
    return [(token,index.get(token,[])) for token in tokens]


def changed_spans(source, target):
    return [(a,b,c,d) for tag,a,b,c,d in SequenceMatcher(None,source,target,autojunk=False).get_opcodes() if tag!='equal']


def load_session(db):
    row = db.execute('SELECT state FROM pinout_review_session WHERE id=1').fetchone()
    try:
        state = json.loads(row[0]) if row else {}
        return state if isinstance(state,dict) else {}
    except (TypeError,ValueError): return {}


def save_session(db, state):
    with db:
        db.execute('INSERT OR REPLACE INTO pinout_review_session VALUES(1,?)',(json.dumps(state),))
