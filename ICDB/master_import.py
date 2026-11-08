"""Read normalized pinouts_master databases. Never modify the source."""
from collections import defaultdict, Counter
from pathlib import Path
import sqlite3
import re
import hashlib
from kicad_import import ImportResult, merge_result
from pinout import Project, Pin, PACKAGES, validate_count


# Package spellings that are the same physical package style as a supported one.
# Only real synonyms - unsupported families (SOT-23, TO-92...) are not approximated.
FAMILY_ALIASES = {
    'DIP': 'DIP', 'PDIP': 'DIP', 'CDIP': 'DIP', 'DIL': 'DIP', 'CERDIP': 'DIP',
    'SOIC': 'SOIC', 'SO': 'SOIC', 'SOP': 'SOIC',
    'TSSOP': 'TSSOP',
    'MSOP': 'MSOP', 'SSOP': 'SSOP', 'PLCC': 'PLCC',
    'QFP': 'QFP', 'LQFP': 'QFP', 'TQFP': 'QFP', 'PQFP': 'QFP', 'MQFP': 'QFP',
    'QFN': 'QFN', 'VQFN': 'QFN', 'WQFN': 'QFN', 'UQFN': 'QFN', 'TQFN': 'QFN', 'VFQFPN': 'QFN', 'HVQFN': 'QFN',
    'DFN': 'DFN', 'SON': 'DFN', 'VSON': 'DFN', 'WSON': 'DFN', 'TDFN': 'DFN', 'UDFN': 'DFN', 'VDFN': 'DFN', 'HVSON': 'DFN',
    'DPAK': 'TO-252', 'D2PAK': 'TO-263', 'DDPAK': 'TO-263',
}
TO_PACKAGES = {'TO-220', 'TO-252', 'TO-263', 'TO-247', 'TO-263AB'}


def package_name(raw, count):
    """Map a database package name to an ICPin package, or raise ValueError.

    Accepts plain names (SOIC, TO-220) and KiCad footprint names such as
    SOIC-8_3.9x4.9mm_P1.27mm, DIP-14_W7.62mm, LQFP-64_10x10mm_P0.5mm or
    TO-220-3_Vertical. The pin count must still be valid for the package
    (QFN/DFN footprints with a numbered exposed pad are rejected)."""
    text = str(raw).upper().strip()
    # Preserve TSOP type and PowerSO20 family before the legacy prefix parser.
    m = re.match(r'^(SSOP|PLCC|TSOP[-_ ]?(?:II|I|2|1))[-_ ]?(\d+)?(?=[_ ]|$)', text)
    if m:
        family=re.sub(r'[-_ ]','',m[1])
        family={'TSOPI':'TSOP-I','TSOP1':'TSOP-I','TSOPII':'TSOP-II','TSOP2':'TSOP-II'}.get(family,family)
        if m[2] and int(m[2])!=count:raise ValueError(f'package count {m[2]} differs from {count} numbered pins')
        validate_count(family,count)
        return family
    if re.match(r'^POWER[-_ ]?SO[-_ ]?20(?:[-_ ]20)?(?=[_ ]|$)',text):
        validate_count('PowerSO20',count)
        return 'PowerSO20'
    value = re.sub(r'[\s_-]', '', str(raw).upper())
    aliases = {'SOP':'SOIC', 'DPAK':'TO-252', 'D2PAK':'TO-263'}
    if value in aliases:
        value = aliases[value].replace('-', '')
    for package in sorted(PACKAGES, key=len, reverse=True):
        key = package.replace('-', '')
        if value == key or value == key + str(count):
            validate_count(package, count)
            return package
    text = str(raw).upper().strip()
    m = re.match(r'(SOT)-?(89|223)(?![0-9])', text) or re.match(r'TO-?(220|252|263|247)(AB)?(?![0-9])', text)
    if m:
        package = (f'SOT-{m.group(2)}' if m.group(1) == 'SOT' else f'TO-{m.group(1)}{m.group(2) or ""}')
        if package in PACKAGES:
            validate_count(package, count)
            return package
    m = re.match(r'([A-Z0-9]+?)(?:[-_]?\d+)?(?:[-_ ]|$)', text)
    head = re.match(r'[A-Z]+[0-9]?[A-Z]*', text)
    family = None
    for candidate in ([m.group(1)] if m else []) + ([head.group(0)] if head else []):
        family = FAMILY_ALIASES.get(re.sub(r'\d+$', '', candidate))
        if family: break
    if family:
        validate_count(family, count)
        return family
    raise ValueError(f'unsupported package/count: {raw}/{count}')


def load_database(path):
    result = ImportResult()
    connection = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    stats = Counter()
    try:
        required = {'definitions','devices','device_definitions','packages','pins','pin_maps','source_records'}
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required <= tables:
            raise ValueError('Expected pinouts_master.db normalized schema; legacy components databases are not supported.')
        links = defaultdict(list)
        for row in connection.execute('SELECT dd.definition_id,d.name,d.manufacturer FROM device_definitions dd JOIN devices d ON d.id=dd.device_id ORDER BY d.id'):
            links[row['definition_id']].append(row)
        maps = defaultdict(list)
        for row in connection.execute('SELECT map_id,number,label FROM pins'):
            maps[row['map_id']].append((row['number'],row['label']))
        # Grouped databases name each logic family record by function (74xx14, 4060);
        # use that as the pinout title instead of whichever linked device sorts first.
        record_cols = {r[1] for r in connection.execute('PRAGMA table_info(source_records)')}
        group_title = ("CASE WHEN sr.group_type='logic' THEN sr.original_name END"
                       if {'group_type', 'original_name'} <= record_cols else 'NULL')
        query = f'''SELECT df.id,df.map_id,df.package_raw,df.status,pk.canonical_name,pm.pin_count,
                   sr.datasheet,sr.description,sr.information,sr.source_key,{group_title} AS group_title
                   FROM definitions df LEFT JOIN packages pk ON pk.id=df.package_id
                   LEFT JOIN pin_maps pm ON pm.id=df.map_id
                   LEFT JOIN source_records sr ON sr.id=df.record_id ORDER BY df.id'''
        for row in connection.execute(query):
            try:
                count = row['pin_count']
                package = package_name(row['canonical_name'] or row['package_raw'] or '', count)
                devices = links[row['id']]
                if not devices: raise ValueError('no linked devices')
                pins = []
                for number, label in maps[row['map_id']]:
                    if not re.fullmatch(r'[1-9][0-9]*', number):
                        raise ValueError(f'nonsequential or named pin number: {number}')
                    pins.append(Pin(int(number), label, 'Ground' if label.upper()=='GND' else 'NC' if label.upper() in ('NC','N.C.') else 'Signal'))
                pins.sort(key=lambda p:p.number)
                title = (row['group_title'] or '').strip() or devices[0]['name']
                project = Project(title, package, count,
                                  source=row['datasheet'] or f'Pinouts master definition {row["id"]}; unverified',pins=pins)
                project.validate()
                # Stable identity: title + package + pin content, not the database row id,
                # so rebuilding/regrouping pinouts_master.db keeps ICDB links. Identical
                # mappings from several records collapse into one pinout.
                digest = hashlib.sha256(repr([(p.number, p.name) for p in pins]).encode('utf-8')).hexdigest()[:12]
                identifier = f'PinoutsMaster:{title}|{package}-{count}|{digest}'
                if identifier in result.pinouts:
                    stats['merged'] += 1
                else:
                    result.pinouts[identifier] = {'project':project,'accepted':False}
                for device in devices:
                    result.devices.append(dict(device=device['name'],manufacturer=device['manufacturer'] or 'Unspecified',
                        package=f'{package}-{count}',pinout_id=identifier,source_url=row['datasheet'] or 'pinouts-master:database',
                        source_page=f'definition={row["id"]}',
                        notes=(row['description'] or '')+f'; package code {row["canonical_name"] or row["package_raw"]}; Unverified source mapping.'))
                stats['imported'] += 1
            except (ValueError,TypeError) as exc:
                stats['skipped'] += 1
                result.report.append(f'SKIPPED definition={row["id"]}: {exc}')
        result.report.insert(0,f'Pinouts master: {stats["imported"]} supported definitions -> {len(result.pinouts)} pinouts ({stats["merged"]} identical mappings combined); {stats["skipped"]} skipped; {len(result.devices)} device links. All mappings are drafts.')
        return result
    except sqlite3.Error as exc:
        raise ValueError(f'Cannot read pinouts_master.db: {exc}') from exc
    finally:
        connection.close()
