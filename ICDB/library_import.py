"""Direct data import: no SVGs, bundle creation or writes to source files."""
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
import json
import sqlite3
import zipfile
from pin_library import validate_data, digest, package_label
from bulk import Catalog, read_text_file, csv_catalog_id, project_dict
from kicad_import import load_libraries
from master_import import package_name


def from_catalog(catalog, name, namespace=None):
    devices = defaultdict(list)
    for d in catalog.devices: devices[d['pinout_id']].append(d)
    items = []
    for ident, entry in catalog.pinouts.items():
        data = project_dict(entry['project'])
        records = devices[ident] or [dict(device=data['device'],manufacturer='',package=package_label(data))]
        items.append(dict(id=ident,project=data,devices=records))
    return dict(name=name,namespace=namespace or 'catalog:'+catalog.catalog_id,items=items,report=catalog.report)


def load_files(paths, devices_path=None):
    paths = [Path(p) for p in paths]
    if not paths: raise ValueError('Choose a source file.')
    if all(p.suffix.lower()=='.kicad_sym' for p in paths):
        result = load_libraries(paths, preserve_unsupported=True)
        # KiCad external IDs already contain the library namespace.
        result.catalog_id = ''; batch = from_catalog(result,', '.join(p.name for p in paths),'kicad')
        return batch
    if len(paths)!=1: raise ValueError('Only KiCad libraries can be selected together.')
    p = paths[0]
    if p.suffix.lower() in ('.db','.sqlite','.sqlite3'): return load_master(p)
    if p.suffix.lower()=='.csv':
        pin_text, pin_note = read_text_file(p)
        device_text, device_note = read_text_file(devices_path) if devices_path else (None, None)
        catalog = Catalog();catalog.import_csv(pin_text,device_text)
        batch = from_catalog(catalog,p.name,csv_namespace(p,pin_text,device_text))
        batch['report'] = [n for n in (pin_note,device_note) if n]+list(batch['report'])
        return batch
    if p.suffix.lower()=='.zip':
        # Catalog is the data authority; no SVG expansion required.
        with zipfile.ZipFile(p) as z:
            info = z.getinfo('catalog.json')
            if info.file_size>128_000_000: raise ValueError('Catalog exceeds 128 MB.')
            data = json.loads(z.read(info))
        return load_catalog_data(data,p.name)
    data = json.loads(p.read_text(encoding='utf-8-sig'))
    if data.get('schema_version')==1:
        data.pop('schema_version');validate_data(data)
        return dict(name=p.name,namespace='project:'+p.name,items=[dict(id='project',project=data,devices=[dict(device=data['device'],manufacturer='',package=package_label(data))])],report=[])
    return load_catalog_data(data,p.name)


def csv_namespace(path, pin_text, device_text=None):
    """Exports from 0.7.5 carry a catalog_id column, so two catalogs exported as
    pinouts.csv to different folders no longer share one source identity (and a renamed
    export keeps its own). CSVs without the column keep the legacy file-name namespace
    so earlier imports still match on re-import."""
    identity = csv_catalog_id(pin_text, device_text)
    return 'csv:catalog:'+identity if identity else 'csv:'+path.name


def load_catalog_data(data,name):
    if data.get('catalog_version')!=1: raise ValueError('Expected an ICPin catalog or project.')
    devices = defaultdict(list)
    for record in data.get('devices',[]): devices[record['pinout_id']].append(record)
    items = []
    for ident,entry in data['pinouts'].items():
        p = validate_data(entry['project'])
        items.append(dict(id=ident,project=p,devices=devices[ident] or [dict(device=p['device'],manufacturer='',package=package_label(p))]))
    return dict(name=name,namespace='catalog:'+str(data.get('catalog_id') or digest(name)),items=items,report=[])


def load_master(path):
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    batch = dict(name=path.name,namespace='master:'+path.name,items=[],report=[])
    try:
        links, pins = defaultdict(list),defaultdict(list)
        for row in db.execute('SELECT dd.definition_id,d.name,d.manufacturer FROM device_definitions dd JOIN devices d ON d.id=dd.device_id ORDER BY dd.definition_id,d.id'):
            links[row['definition_id']].append(dict(row))
        for row in db.execute('SELECT map_id,number,label FROM pins'):
            n = str(row['number']);n = int(n) if n.isdecimal() else n
            pins[row['map_id']].append(dict(number=n,name=row['label'],role='Signal',description=''))
        query = '''SELECT df.id,df.map_id,df.package_raw,pk.canonical_name,pm.pin_count,
            sr.datasheet,sr.description,sr.source_key FROM definitions df
            LEFT JOIN packages pk ON pk.id=df.package_id LEFT JOIN pin_maps pm ON pm.id=df.map_id
            LEFT JOIN source_records sr ON sr.id=df.record_id ORDER BY df.id'''
        for row in db.execute(query):
            raw = row['canonical_name'] or row['package_raw'] or 'Unresolved'
            try:
                package = package_name(raw,row['pin_count'])
            except (ValueError,TypeError): package = raw
            try:
                records = links[row['id']]
                title = records[0]['name'] if records else 'Definition '+str(row['id'])
                data = dict(device=title,package=package,count=row['pin_count'],source=row['datasheet'] or '',verified=False,pins=pins[row['map_id']])
                validate_data(data)
                devices = [dict(device=r['name'],manufacturer=r['manufacturer'] or '',package=f"{package}-{data['count']}",
                                source_url=row['datasheet'] or '',source_page='',notes=row['description'] or '') for r in records]
                # Original row identity permits changed definitions to become review conflicts.
                batch['items'].append(dict(id=str(row['id']),project=data,devices=devices))
            except (ValueError,TypeError) as exc: batch['report'].append(f"Skipped definition {row['id']}: {exc}")
        return batch
    except sqlite3.Error as exc:
        raise ValueError('Expected normalized master/grouped pinout database: '+str(exc)) from exc
    finally: db.close()
