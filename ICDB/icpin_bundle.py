"""Reviewed ICPin imports with stable assets and additive device associations."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
import uuid
import zipfile
from pinouts import package_name
from reference_images import reference_suffix
from pinout import PACKAGES, count_limits, validate_count, exposed_pad, project_label

SCHEMA='''CREATE TABLE IF NOT EXISTS icpin_pinouts(
 catalog_id TEXT NOT NULL, pinout_id TEXT NOT NULL,
 asset_id INTEGER NOT NULL UNIQUE REFERENCES pinout_assets(id),
 package TEXT NOT NULL, pin_count INTEGER NOT NULL, project_json TEXT NOT NULL,
 imported_sha256 TEXT NOT NULL, PRIMARY KEY(catalog_id,pinout_id));
CREATE TABLE IF NOT EXISTS icpin_bundles(
 catalog_id TEXT PRIMARY KEY, bundle_path TEXT NOT NULL, sha256 TEXT NOT NULL);
'''
UNKNOWN={'','unknown','unspecified','unspecified (kicad)'}
# Shared renderer/import contract; unnumbered thermal tabs are not extra pins.
PACKAGE_COUNTS = {package: count_limits(package) for package in PACKAGES}

def valid_package_count(package, count):
    try: validate_count(package,count)
    except ValueError: return False
    return True


def key(value):return value.strip().upper()
def encoded(value):return json.dumps(value,sort_keys=True,ensure_ascii=False)

class Bundle:
    def __init__(self,path):
        self.path=Path(path)
        if self.path.stat().st_size>128_000_000:raise ValueError('Bundle exceeds 128 MB.')
        self.raw=self.path.read_bytes();self.sha=hashlib.sha256(self.raw).hexdigest()
        import io
        try:
            with zipfile.ZipFile(io.BytesIO(self.raw)) as archive:
                infos=archive.infolist();names=[i.filename for i in infos]
                if len(names)!=len(set(names)):raise ValueError('Duplicate files in bundle.')
                if len(names)>20000 or sum(i.file_size for i in infos)>256_000_000:
                    raise ValueError('Bundle is too large when expanded.')
                for name in names:
                    if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or '\\' in name:
                        raise ValueError('Unsafe bundle filename.')
                manifest=json.loads(archive.read('bundle.json'))
                catalog=json.loads(archive.read('catalog.json'))
                if manifest.get('format')!='icpin-bundle' or manifest.get('version')!=1:
                    raise ValueError('Unsupported ICPin bundle version.')
                self.catalog_id=str(uuid.UUID(manifest['catalog_id']))
                if catalog.get('catalog_id')!=self.catalog_id or catalog.get('catalog_version')!=1:
                    raise ValueError('Editable catalog identity does not match bundle.')
                self.pinouts={};self.devices=manifest['devices']
                if not isinstance(self.devices,list):raise ValueError('Invalid device table.')
                with tempfile.TemporaryDirectory() as temp:
                    for entry in manifest['pinouts']:
                        ident=entry['pinout_id'];p=entry['project']
                        if not isinstance(ident,str) or not ident.strip() or ident in self.pinouts:
                            raise ValueError('Missing or duplicate pinout ID.')
                        exposed_pad(p)
                        count=p['count'];pins=p['pins']
                        if not valid_package_count(p['package'], count):
                            raise ValueError('Invalid package/count for '+ident)
                        if len(pins)!=count or {pin['number'] for pin in pins}!=set(range(1,count+1)):
                            raise ValueError('Incomplete/duplicate pin numbers for '+ident)
                        if any(type(pin['number']) is not int or not isinstance(pin['name'],str) or not pin['name'].strip()
                               or not all(isinstance(pin.get(k,''),str) for k in ('role','description')) for pin in pins):
                            raise ValueError('Invalid pin data for '+ident)
                        if not isinstance(p.get('device'),str) or not isinstance(p.get('source',''),str):
                            raise ValueError('Invalid device/source text for '+ident)
                        if catalog['pinouts'][ident]['project']!=p:raise ValueError('Editable pin data differs from manifest.')
                        info=archive.getinfo(entry['svg_file'])
                        if info.file_size>8_000_000:raise ValueError('SVG exceeds 8 MB.')
                        svg=archive.read(info)
                        if hashlib.sha256(svg).hexdigest()!=entry['sha256']:raise ValueError('SVG checksum mismatch: '+ident)
                        sample=Path(temp)/'preview.svg';sample.write_bytes(svg);reference_suffix(sample)
                        self.pinouts[ident]=dict(entry,svg=svg,package=package_name(project_label(p)))
                if not self.pinouts:raise ValueError('Bundle has no pinouts.')
                if set(catalog['pinouts'])!=set(self.pinouts) or catalog['devices']!=self.devices:
                    raise ValueError('Catalog and manifest contain different records.')
                for row in self.devices:
                    if not all(isinstance(row.get(k),str) for k in ('device','manufacturer','package','pinout_id','source_url','source_page','notes')):
                        raise ValueError('Invalid device record.')
        except (zipfile.BadZipFile,KeyError,TypeError,AttributeError,UnicodeError) as exc:
            raise ValueError('Invalid ICPin bundle: '+str(exc)) from exc


def preview(store,bundle):
    """Read-only plan; no guessed aliases or suffix removal."""
    assets=[];states={}
    for ident,entry in bundle.pinouts.items():
        previous=store.db.execute('SELECT p.*,a.sha256,a.path FROM icpin_pinouts p JOIN pinout_assets a ON a.id=p.asset_id WHERE catalog_id=? AND pinout_id=?',(bundle.catalog_id,ident)).fetchone()
        collision=store.db.execute('SELECT id FROM pinout_assets WHERE sha256=?',(entry['sha256'],)).fetchone()
        reason='';action='New'
        if previous:
            if previous['package']!=entry['package'] or previous['pin_count']!=entry['project']['count']:
                action='Conflict';reason='Package/count changed; use a new pinout ID.'
            elif previous['sha256']!=previous['imported_sha256'] or (store.path(previous).exists() and hashlib.sha256(store.path(previous).read_bytes()).hexdigest()!=previous['imported_sha256']):
                action='Conflict';reason='Managed image was changed outside bundle import.'
            elif previous['sha256']==entry['sha256'] and previous['project_json']==encoded(entry['project']):action='Unchanged'
            else:action='Update'
        if collision and (not previous or collision['id']!=previous['asset_id']):
            action='Conflict';reason='Identical image already belongs to another asset; existing image kept.'
        row=dict(pinout_id=ident,package=entry['package'],action=action,reason=reason,
                 asset_id=previous['asset_id'] if previous else None)
        assets.append(row);states[ident]=row
    components={}
    for r in store.db.execute('SELECT id,part_number,manufacturer FROM components WHERE part_number IS NOT NULL'):
        components.setdefault(key(r['part_number']),[]).append(dict(r))
    links=[];seen=set();targets=set()
    for index,device in enumerate(bundle.devices):
        ident=device['pinout_id'];candidates=components.get(key(device['device']),[])
        status='Ready';reason='Exact part match';cid=None
        identity=(key(device['device']),key(device['manufacturer']),package_name(device['package']))
        if identity in seen:status='Duplicate';reason='Repeated device/manufacturer/package record.'
        elif ident not in states:status='Unresolved';reason='No pinout mapping supplied.'
        elif states[ident]['action']=='Conflict':status='Conflict';reason=states[ident]['reason']
        elif package_name(device['package'])!=states[ident]['package']:
            status='Conflict';reason='Device package differs from pinout.'
        elif not candidates:status='Unmatched';reason='Part number absent from ICDB.'
        else:
            mfr=device['manufacturer'].strip().casefold()
            if mfr not in UNKNOWN:
                exact=[c for c in candidates if c['manufacturer'].strip().casefold()==mfr]
                if exact:candidates=exact
                elif len(candidates)==1 and not candidates[0]['manufacturer'].strip():
                    reason='Exact part; ICDB manufacturer is blank.'
                else:status='Manufacturer mismatch';reason='No exact manufacturer match.'
            if status=='Ready':
                if len(candidates)!=1:status='Ambiguous';reason='Multiple ICDB records; specify manufacturer.'
                else:
                    cid=candidates[0]['id']
                    aid=states[ident]['asset_id']
                    if aid and store.db.execute('SELECT 1 FROM pinout_links WHERE component_id=? AND asset_id=? AND package=?',(cid,aid,states[ident]['package'])).fetchone():
                        status='Linked';reason='Existing association retained.'
        target=(cid,ident,package_name(device['package']))
        if status=='Ready' and target in targets:
            status='Duplicate';reason='Another row resolves to the same device association.'
        if status in {'Ready','Linked'}:targets.add(target)
        seen.add(identity)
        links.append(dict(index=index,device=device['device'],manufacturer=device['manufacturer'],package=device['package'],
                          pinout_id=ident,component_id=cid,status=status,reason=reason))
    return dict(assets=assets,links=links)


def apply_bundle(store,bundle,approved):
    """Apply the displayed ready items atomically; links/defaults are never removed."""
    db=store.db
    if db.in_transaction:raise ValueError('Finish the current database operation first.')
    created=[];superseded=[]
    try:
        db.execute('BEGIN IMMEDIATE')
        current=preview(store,bundle)
        if current!=approved:raise ValueError('The catalogue changed after preview. Reopen the bundle preview.')
        ids={};changed=0;linked=0
        def write_new(path,data):
            if not path.resolve().is_relative_to(store.root/'pinouts'):
                raise ValueError('Managed import path is outside pinouts.')
            path.parent.mkdir(parents=True,exist_ok=True)
            if path.exists():
                if path.read_bytes()!=data:raise ValueError('Managed import file was modified: '+str(path))
                return
            temporary=path.with_name(path.name+'.tmp')
            try:temporary.write_bytes(data);temporary.replace(path);created.append(path)
            finally:temporary.unlink(missing_ok=True)
        for item in current['assets']:
            if item['action']=='Conflict':continue
            ident=item['pinout_id'];entry=bundle.pinouts[ident]
            identity=hashlib.sha256(ident.encode()).hexdigest()
            relative=f"pinouts/icpin/{bundle.catalog_id}/{identity}/{entry['sha256']}.svg"
            write_new(store.root/relative,entry['svg'])
            aid=item['asset_id']
            if aid is None:
                aid=db.execute('INSERT INTO pinout_assets(sha256,path,original_name,caption,source) VALUES(?,?,?,?,?)',
                    (entry['sha256'],relative,ident+'.svg',entry['project']['device'],entry['project'].get('source',''))).lastrowid
            else:
                old=db.execute('SELECT path FROM pinout_assets WHERE id=?',(aid,)).fetchone()
                if old and old[0]!=relative:superseded.append(old[0])
                db.execute('UPDATE pinout_assets SET sha256=?,path=? WHERE id=?',(entry['sha256'],relative,aid))
            db.execute('''INSERT INTO icpin_pinouts VALUES(?,?,?,?,?,?,?) ON CONFLICT(catalog_id,pinout_id)
                DO UPDATE SET project_json=excluded.project_json,imported_sha256=excluded.imported_sha256''',
                (bundle.catalog_id,ident,aid,entry['package'],entry['project']['count'],encoded(entry['project']),entry['sha256']))
            ids[ident]=aid
            if item['action']!='Unchanged':changed+=1
        for item in current['links']:
            if item['status']!='Ready':continue
            aid=ids[item['pinout_id']];cid=item['component_id'];entry=bundle.pinouts[item['pinout_id']]
            first=not db.execute('SELECT 1 FROM pinout_links WHERE component_id=?',(cid,)).fetchone()
            db.execute('INSERT INTO pinout_links(component_id,asset_id,package,pin_count,is_default) VALUES(?,?,?,?,?)',
                       (cid,aid,entry['package'],entry['project']['count'],int(first)))
            linked+=1
        relative=f'pinouts/icpin/{bundle.catalog_id}/sources/{bundle.sha}.icpin.zip'
        write_new(store.root/relative,bundle.raw)
        db.execute('INSERT INTO icpin_bundles VALUES(?,?,?) ON CONFLICT(catalog_id) DO UPDATE SET bundle_path=excluded.bundle_path,sha256=excluded.sha256',
                   (bundle.catalog_id,relative,bundle.sha))
        from pinout_matcher import remember_sources
        remember_sources(store,bundle)
        db.commit()
    except Exception:
        db.rollback()
        for path in reversed(created):path.unlink(missing_ok=True)
        raise
    # Remove superseded generated revisions only after commit, and only when nothing references them.
    for relative in superseded:
        try:
            path=store.path({'path':relative})
            if path.is_relative_to(store.root/'pinouts'/'icpin') and not db.execute('SELECT 1 FROM pinout_assets WHERE path=?',(relative,)).fetchone():
                path.unlink(missing_ok=True)
        except (OSError,ValueError):pass
    return changed,linked
