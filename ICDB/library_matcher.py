"""Indexed candidate search over pin data; never generates an image."""
from collections import defaultdict
import json
import rule_api
from pinout_matcher import part_tokens, variant_match, family_number, SECOND_SOURCE_PREFIXES, EXACT_MFR_CAUTION
from pinouts import package_name
from icpin_bundle import UNKNOWN, key
from pin_library import digest, encoded, package_label, render_issue, signature


def scan(library):
    db = library.db
    components = {r['id']: dict(r) for r in db.execute('SELECT id,part_number,manufacturer FROM components')}
    exact, numeric, families = defaultdict(list), defaultdict(list), defaultdict(list)
    for c in components.values():
        exact[key(c['part_number'])].append(c)
        token = part_tokens(c['part_number'])
        if token: numeric[token[0]].append(c)
        family = family_number(c['part_number'])
        if family: families[family].append(c)
    defs = {r['id']:json.loads(r['project_json']) for r in db.execute('SELECT * FROM pl_definitions')}
    sources, mappings = [], {}
    source_def = {}
    for row in db.execute('SELECT * FROM pl_sources ORDER BY namespace,external_id'):
        data = defs[row['definition_id']]
        for record in json.loads(row['devices_json']):
            record = dict(record)
            record.setdefault('manufacturer',''); record.setdefault('notes','')
            record.setdefault('source_url',''); record.setdefault('source_page','')
            record.setdefault('package',package_label(data))
            # Namespace is part of the identity: every ICPin project file uses id 'project'
            # and master databases reuse row ids, so external_id alone collides.
            sid = digest([row['namespace'],row['external_id'],record])
            # One common namespace/definition identity permits rules to consolidate aliases.
            s = rule_api.Source(dict(catalog_id='library',source_id=sid,pinout_id=str(row['definition_id']),
                              project_json=encoded(data),record_json=encoded(record)),package_name)
            sources.append(s); source_def[sid] = row['definition_id']
            mappings[('library',s.pinout_id)] = dict(project_json=encoded(data),package=package_label(data))
    # Manual definitions also participate in exact and family matching.
    sourced = set(source_def.values())
    for ident, data in defs.items():
        if ident in sourced: continue
        rec = dict(device=data['device'],manufacturer='',package=package_label(data),notes='',source_url=data.get('source',''),source_page='')
        sid = 'manual-definition:'+str(ident)
        sources.append(rule_api.Source(dict(catalog_id='library',source_id=sid,pinout_id=str(ident),
                       project_json=encoded(data),record_json=encoded(rec)),package_name)); source_def[sid] = ident
    ctx = rule_api.Context(db,components,exact,sources,mappings)
    rules, rule_errors = rule_api.load_rules(library.root)
    rule_errors = list(rule_errors)          # broken rule files are skipped, not fatal
    conflicts = defaultdict(set)
    issues = {ident:render_issue(data) for ident,data in defs.items()}
    for s in sources:
        conflicts[(s.name,key(s.manufacturer),s.package)].add(signature(s.project))
    while True:
        # A rule that raises is dropped and the whole pass is recomputed without it,
        # so the result never depends on where (or for which row) it failed.
        ctx.cache = {}
        try:
            proposals = _propose(rules,ctx,sources,source_def,components,exact,numeric,families,issues,conflicts)
            break
        except _RuleFailure as failure:
            rule_errors.append(failure.message)
            rules = [r for r in rules if r is not failure.rule]
    # Conflicting exact pinouts must not be accepted merely because each name is exact.
    exact_defs = defaultdict(set)
    for item in proposals.values():
        if item['rule']=='exact-v1' and not item['blocked']:
            exact_defs[(item['component_id'],package_label(defs[item['definition_id']]))].add(item['definition_id'])
    with db:
        for k,item in proposals.items():
            if len(exact_defs[(k[0],package_label(defs[k[1]]))])>1:
                item['blocked'] = 'Multiple exact sources disagree on pin data for this part/package.'
            old = db.execute('SELECT * FROM pl_matches WHERE component_id=? AND definition_id=?',k).fetchone()
            if old and old['rule']=='manual-v1': continue
            if old and old['status']=='Accepted':
                # A person already accepted this link. Advisory blocks (the shared-number default and
                # review-rule verdicts, e.g. rules added in a later release) become cautions so the
                # link keeps publishing; structural blocks (conflicting sources, rendering) still apply.
                if item['rule']==SHARED_RULE and item['blocked']==SHARED_BLOCK: item['blocked'] = ''
                elif item['blocked'] and item['blocked']==item.get('review_block'):
                    item['reason'] += (' ' if 'CAUTION:' in item['reason'] else ' | CAUTION: ')+item['blocked']
                    item['blocked'] = ''
            status = 'Blocked' if item['blocked'] else 'Suggested'
            if old and old['status'] in ('Accepted','Rejected'):
                # Accepted edits are deliberate; reimport conflicts never overwrite them.
                status = old['status'] if old['status']=='Accepted' or old['evidence']==item['evidence'] or old['rule']=='legacy-reject' else status
            db.execute('''INSERT INTO pl_matches(component_id,definition_id,status,rule,reason,blocked,evidence)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(component_id,definition_id) DO UPDATE SET
                status=excluded.status,rule=excluded.rule,reason=excluded.reason,blocked=excluded.blocked,evidence=excluded.evidence''',
                (k[0],k[1],status,item['rule'],item['reason'],item['blocked'],item['evidence']))
        for old in db.execute("SELECT * FROM pl_matches WHERE rule NOT IN ('manual-v1','legacy')").fetchall():
            if (old['component_id'],old['definition_id']) not in proposals:
                db.execute("UPDATE pl_matches SET blocked='No longer supported by the current sources/rules',status=CASE WHEN status='Suggested' THEN 'Blocked' ELSE status END WHERE id=?",(old['id'],))
    scan.rule_errors = rule_errors
    return dict(candidates=len(proposals),blocked=sum(bool(p['blocked']) for p in proposals.values()),
                rule_errors=rule_errors)


SHARED_RULE = 'prefix-shared-number-v1'
SHARED_BLOCK = 'Shared number only; link manually if correct'


_RuleFailure = rule_api.RuleFailure
_call = rule_api.call             # guarded + result-shape checked; a failure skips the rule for this scan


def _variant(source, target):
    """variant_match mapped to native ranks/rules: exact 0, family rules 2,
    suffix 2, prefix 3, shared number only 4 (Blocked unless both prefixes are
    known second-source prefixes)."""
    match = variant_match(source, target)
    if not match: return None
    _, label, reason = match
    if label == 'Suffix variant': return 2, 'prefix-suffix-v1', reason, ''
    if label == 'Prefix variant': return 3, 'prefix-suffix-v1', reason, ''
    a, b = part_tokens(source)[1], part_tokens(target)[1]
    if a in SECOND_SOURCE_PREFIXES and b in SECOND_SOURCE_PREFIXES:
        return 4, SHARED_RULE, reason + ' | CAUTION: Second-source prefixes ' + f'{a}/{b}; confirm the datasheet pinout', ''
    return 4, SHARED_RULE, reason, SHARED_BLOCK


def _propose(rules, ctx, sources, source_def, components, exact, numeric, families, issues, conflicts):
    for rule in rules:
        if rule.prepare: _call(rule, 'prepare', ctx)
    proposals = {}
    for s in sources:
        ident = source_def[s.source_id]; candidates = {}
        for c in exact.get(s.name,[]): candidates[c['id']] = (0,'exact-v1','Exact part name; confirm package applicability','')
        if s.name.isdecimal() and len(s.name)==4 and s.name.startswith('4'):
            for c in families.get(s.name,[]): candidates.setdefault(c['id'],(2,'4000-prefix-v1','Same 4000-series number; confirm pinout',''))
        for rule in rules:
            if rule.candidates:
                for cid, reason in _call(rule, 'candidates', s, ctx) or []:
                    if cid in components: candidates.setdefault(cid,(rule.RANK,rule.RULE_ID,str(reason),''))
        token = part_tokens(s.name)
        if token:
            for c in numeric.get(token[0],[]):
                match = _variant(s.name,c['part_number'])
                if match: candidates.setdefault(c['id'],match)
        for cid,(rank,rule,reason,blocked) in candidates.items():
            c = components[cid]; caution = []
            if issues[ident]: blocked = 'Rendering unavailable: '+issues[ident]
            if s.package != package_label(s.project): blocked = 'Source package differs from pin definition.'
            if len(conflicts[(s.name,key(s.manufacturer),s.package)])>1:
                blocked = 'Conflicting source pin tables for this part/package.'
            if s.manufacturer.casefold() not in UNKNOWN and c['manufacturer'].strip() and key(s.manufacturer)!=key(c['manufacturer']):
                if rule == 'exact-v1':        # second sources share exact names (LM358 TI / ST)
                    caution.append(EXACT_MFR_CAUTION)
                else:
                    blocked = 'Manufacturer conflict.'
            row = dict(rule=rule,target=c['part_number'],source=s.device,component_id=cid,package=s.package,
                       definition_id=ident,catalog_id=s.catalog_id,pinout_id=s.pinout_id,project=s.project,
                       manufacturer=c['manufacturer'],target_manufacturer=c['manufacturer'],
                       source_manufacturer=s.manufacturer)
            review_block = ''
            for hook in rules:
                # The shared-number default block is soft: review rules still run, so a link
                # accepted before 0.7.5 keeps every other rule's verdict.
                if hook.review and (not blocked or blocked==SHARED_BLOCK):
                    verdict = _call(hook, 'review', row, ctx)
                    if verdict:
                        kind,text = verdict
                        if kind=='block': blocked = review_block = text
                        elif kind=='caution': caution.append(text)
            reason = f'{s.device} → {c["part_number"]}: {reason}'
            if caution: reason += (' ' if 'CAUTION:' in reason else ' | CAUTION: ')+' '.join(caution)
            item = dict(component_id=cid,definition_id=ident,rule=rule,reason=reason,blocked=blocked,
                        evidence=digest([c,s.project,s.record]),rank=rank,review_block=review_block)
            k = (cid,ident)
            prev = proposals.get(k)
            # Prefer usable exact evidence; blocked alternatives remain in source history.
            if prev is None or (bool(blocked),rank)<(bool(prev['blocked']),prev['rank']): proposals[k]=item
    return proposals
