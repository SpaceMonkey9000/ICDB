"""Bulk import with explicit identity, conflict reporting and portable catalog storage."""
from dataclasses import asdict
from pathlib import Path
import copy
import csv
import io
import json
import os
import re
import uuid
from pinout import Project, Pin, ROLES, clean_project, diagram, exposed_pad, project_label

PIN_FIELDS = ('pinout_id','package','pin_count','pin_number','pin_name','pin_role','description')
PAD_FIELDS = ('exposed_pad_number','exposed_pad_name','exposed_pad_role','exposed_pad_description')
DEVICE_FIELDS = ('device','manufacturer','package','pinout_id','source_url','source_page','notes')


MISDECODED_BOM = '\u00ef\u00bb\u00bf'  # UTF-8 BOM bytes read as Windows-1252
SEP_LINE = re.compile(r'^"?sep=(.)"?[ \t]*$', re.I)


def read_text_file(path):
    """Return (text, note). UTF-8 first; UTF-16 (Excel "Unicode Text") by BOM; Excel's
    Windows-1252 CSVs are accepted with a note."""
    name = Path(path).name
    data = Path(path).read_bytes()
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        try:
            return data.decode('utf-16').lstrip('\ufeff'), None
        except UnicodeDecodeError:
            raise ValueError(f'{name} starts with a UTF-16 marker but is not valid UTF-16 text. Save it as "CSV UTF-8" and try again.') from None
    try:
        return data.decode('utf-8-sig'), None
    except UnicodeDecodeError:
        pass
    try:
        text = data.decode('cp1252')
    except UnicodeDecodeError:
        raise ValueError(f'{name} is neither UTF-8 nor Windows-1252 text. Save it as "CSV UTF-8" and try again.') from None
    # A UTF-8 file with one stray Windows-1252 byte still carries the UTF-8 BOM.
    text = text.removeprefix(MISDECODED_BOM)
    return text, f'NOTE {name}: not UTF-8; read as Windows-1252 (cp1252). Check special characters such as µ or Ω.'


def split_separator(text):
    """Return (text, delimiter, skipped_lines); honours Excel's optional 'sep=X' first line."""
    text = text.lstrip('\ufeff')
    first, newline, rest = text.partition('\n')
    match = SEP_LINE.match(first.rstrip('\r'))
    if match:
        return rest, match[1], 1
    first = text.splitlines()[0] if text.strip() else ''
    return text, '\t' if '\t' in first else ';' if ';' in first else ',', 0


def read_rows(text, required):
    text, delimiter, skipped = split_separator(text)
    if delimiter in '"\r\n':
        raise ValueError(f'Unusable separator in "sep=" line: {delimiter!r}.')
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    index = 1 + skipped
    try:
        if not reader.fieldnames:
            raise ValueError('CSV has no header.')
        reader.fieldnames = [x.strip().lower() for x in reader.fieldnames]
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError('Duplicate column headings.')
        missing = set(required)-set(reader.fieldnames)
        if missing:
            raise ValueError('Missing columns: '+', '.join(sorted(missing)))
        rows = []
        for index, row in enumerate(reader, 2 + skipped):
            # Excel often saves trailing rows that contain only separators.
            if not any((v or '').strip() for k,v in row.items() if k is not None) and not any(x.strip() for x in row.get(None) or []):
                continue
            if None in row:
                raise ValueError(f'Row {index}: extra columns; quote values containing commas.')
            rows.append((index,{k:(v or '').strip() for k,v in row.items()}))
    except csv.Error as exc:
        raise ValueError(f'CSV cannot be read near line {max(index, reader.line_num)}: {exc}. '
                         'Check for unbalanced quotes or binary content, or re-save as "CSV UTF-8".') from None
    return rows


def csv_catalog_id(*texts):
    """Catalog id written by Catalog.export_csv, or None (older exports and hand-made CSVs)."""
    found = set()
    for text in texts:
        if text is None:
            continue
        try:
            rows = read_rows(text, ())
        except ValueError:
            return None
        found.update(row.get('catalog_id', '') for _, row in rows)
    found.discard('')
    if len(found) != 1:
        return None
    try:
        return str(uuid.UUID(found.pop()))
    except ValueError:
        return None


def fingerprint(project):
    base = (project.package, project.count, tuple(sorted((p.number,p.name,p.role,p.description) for p in project.pins)))
    pad = exposed_pad(project)
    return base + (tuple(pad[k] for k in ('number','name','role','description')),) if pad else base


def device_key(row):
    return tuple(row[k].casefold() for k in ('device','manufacturer','package'))


def project_dict(p):
    data = asdict(p)
    if exposed_pad(p): data['exposed_pad'] = exposed_pad(p)
    else: data.pop('exposed_pad', None)
    return data


def project_from(data):
    data = dict(data)
    data['pins'] = [Pin(**p) for p in data['pins']]
    project = clean_project(Project(**data))
    project.validate()
    return project


class Catalog:
    def __init__(self):
        self.catalog_id = str(uuid.uuid4())
        self.retired_ids = set()
        self.pinouts = {}
        self.devices = []
        self.report = []
        self.dirty = False

    def import_csv(self, pin_text, device_text=None):
        # Parse both files first so malformed headers never cause a partial mutation.
        pin_rows = read_rows(pin_text, PIN_FIELDS[:6])
        device_rows = read_rows(device_text, DEVICE_FIELDS[:6]) if device_text is not None else []
        report = []
        groups = {}
        blocked = set()
        for line,row in pin_rows:
            identifier = row['pinout_id']
            if not identifier:
                report.append(f'REJECTED row {line}: missing pinout_id.')
                continue
            groups.setdefault(identifier,[]).append((line,row))
        for identifier, rows in groups.items():
            if identifier in self.retired_ids:
                blocked.add(identifier);report.append(f'REJECTED {identifier}: deleted identity; use a new pinout_id.');continue
            try:
                first = rows[0][1]
                count = int(first['pin_count'])
                package = first['package'].upper()
                pins = []
                for line,row in rows:
                    if row['package'].upper()!=package or int(row['pin_count'])!=count:
                        raise ValueError(f'inconsistent package/count at row {line}')
                    role = row['pin_role'] or 'Signal'
                    role = next((x for x in ROLES if x.casefold()==role.casefold()),role)
                    pins.append(Pin(int(row['pin_number']),row['pin_name'],role,row.get('description','')))
                pads = {tuple(row.get(k,'') for k in PAD_FIELDS) for _,row in rows}
                if len(pads)>1: raise ValueError('inconsistent exposed-pad columns; repeat pad metadata on every lead row')
                fields = next(iter(pads))
                pad = dict(zip(('number','name','role','description'),fields)) if any(fields) else None
                if pad and not pad['role']: pad['role']='Signal'
                project = Project(identifier,package,count,pins=pins,exposed_pad=pad)
                project.validate()
                if identifier in self.pinouts:
                    old = self.pinouts[identifier]['project']
                    if fingerprint(old)==fingerprint(project):
                        report.append(f'UNCHANGED {identifier}: matching mapping already present.')
                    else:
                        blocked.add(identifier)
                        report.append(f'CONFLICT {identifier}: existing mapping kept. Review CSV before replacing manually.')
                    continue
                self.pinouts[identifier] = {'project':project, 'accepted':False}
                self.dirty = True
                report.append(f'IMPORTED {identifier}: {package}-{count}, draft.')
            except (ValueError, TypeError) as exc:
                blocked.add(identifier)
                report.append(f'REJECTED {identifier}: {exc}')
        existing = {device_key(d):d for d in self.devices}
        for line,row in device_rows:
            row = {key:row.get(key,'') for key in DEVICE_FIELDS}
            if not row['device'] or not row['manufacturer'] or not row['package']:
                report.append(f'REJECTED device row {line}: device, manufacturer and package are required.')
                continue
            if row['pinout_id'] in blocked:
                report.append(f'REJECTED device row {line}: referenced mapping failed or conflicts; link not imported.')
                continue
            row['package'] = row['package'].upper()
            key = device_key(row)
            if key in existing:
                if existing[key] == row:
                    report.append(f'UNCHANGED device {row["device"]} / {row["package"]}.')
                else:
                    report.append(f'CONFLICT device {row["device"]} / {row["package"]}: existing link/source kept.')
                continue
            self.devices.append(row)
            if row['pinout_id'] in self.pinouts:
                self.pinouts[row['pinout_id']]['accepted'] = False
            existing[key] = row
            self.dirty = True
            report.append(f'LINKED {row["device"]} / {row["package"]}: {self.device_status(row)}.')
        seen = {}
        for identifier,entry in self.pinouts.items():
            fp = fingerprint(entry['project'])
            if fp in seen:
                report.append(f'REUSE CANDIDATE {identifier} and {seen[fp]}: identical data; identities retained.')
            else:
                seen[fp] = identifier
        if not report:
            report.append('No records found.')
        self.report = report
        self.dirty = True
        return report

    def device_status(self, row):
        identifier = row['pinout_id']
        if not identifier:
            return 'Missing'
        entry = self.pinouts.get(identifier)
        if not entry:
            return 'Needs attention: unknown pinout'
        p = entry['project']
        if row['package'] != project_label(p):
            return 'Needs attention: package mismatch'
        if not row['source_url'] or not row['source_page']:
            return 'Needs attention: source missing'
        return 'Accepted' if entry['accepted'] else 'Draft'

    def accept(self, identifier, value):
        entry = self.pinouts[identifier]
        entry['project'].validate()
        if value:
            links = [d for d in self.devices if d['pinout_id']==identifier]
            if not links:
                raise ValueError('Add a device link and source before accepting this mapping.')
            if any(self.device_status(d).startswith('Needs attention') for d in links):
                raise ValueError('Resolve package/source issues in the linked devices before accepting.')
        entry['accepted'] = bool(value)
        self.dirty = True

    def package_locked(self, identifier):
        """True when package/count changes would break identities already shared with ICDB."""
        return identifier.startswith('KiCad:') or any(d['pinout_id']==identifier for d in self.devices)

    def copy_as_new(self, identifier, project):
        """Store project under a new pinout ID; the original mapping and its links stay unchanged."""
        project.validate()
        # Drop the KiCad: prefix so the copy is never mistaken for a library identity.
        base = f'{identifier.removeprefix("KiCad:")}_{project.package}-{project.count}'
        new_id, index = base, 2
        while new_id in self.pinouts or new_id in self.retired_ids:
            new_id = f'{base}_{index}'; index += 1
        self.pinouts[new_id] = {'project':copy.deepcopy(project),'accepted':False}
        self.dirty = True
        return new_id

    def update(self, identifier, project):
        project.validate()
        self.pinouts[identifier] = {'project':copy.deepcopy(project),'accepted':False}
        self.dirty = True

    def save(self, path):
        data = {'catalog_version':1,'catalog_id':self.catalog_id,'retired_ids':sorted(self.retired_ids),'pinouts':{k:{'project':project_dict(v['project']),'accepted':v['accepted']} for k,v in self.pinouts.items()},'devices':self.devices,'report':self.report}
        path = Path(path)
        temporary = path.with_name(path.name+'.tmp')
        try:
            with temporary.open('w',encoding='utf-8') as handle:
                handle.write(json.dumps(data,indent=2,ensure_ascii=False))
                handle.flush();os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        self.dirty = False

    @classmethod
    def load(cls,path):
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if data.get('catalog_version')!=1:
            raise ValueError('Not an ICPin batch catalog.')
        result = cls()
        # Legacy catalogs gain a repeatable namespace until first saved.
        result.catalog_id = str(uuid.UUID(data['catalog_id'])) if 'catalog_id' in data else str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(data,sort_keys=True)))
        result.retired_ids = set(data.get('retired_ids',[]))
        result.pinouts = {k:{'project':project_from(v['project']),'accepted':bool(v['accepted'])} for k,v in data['pinouts'].items()}
        for row in data['devices']:
            if any(k not in row or not isinstance(row[k],str) for k in DEVICE_FIELDS):
                raise ValueError('Invalid device record.')
            # Drop unknown keys so CSV and bundle exports keep a fixed column set.
            result.devices.append({k:row[k] for k in DEVICE_FIELDS})
        if len({device_key(d) for d in result.devices})!=len(result.devices):
            raise ValueError('Duplicate device identities in catalog.')
        result.report = list(data.get('report',[]))
        return result

    def export_csv(self, folder):
        """Write pinouts_<id8>.csv and devices_<id8>.csv; a catalog_id column lets re-imports
        of renamed or moved exports keep one ICDB source identity. Returns both paths."""
        folder = Path(folder)
        suffix = self.catalog_id.split('-')[0]
        pins_path, devices_path = folder/f'pinouts_{suffix}.csv', folder/f'devices_{suffix}.csv'
        with pins_path.open('w',newline='',encoding='utf-8-sig') as f:
            writer=csv.writer(f); writer.writerow(PIN_FIELDS+('catalog_id',)+PAD_FIELDS)
            for identifier,entry in sorted(self.pinouts.items()):
                p=entry['project']
                for pin in sorted(p.pins,key=lambda p:p.number):
                    writer.writerow((identifier,p.package,p.count,pin.number,pin.name,pin.role,pin.description,self.catalog_id)+tuple((exposed_pad(p) or {}).get(k,'') for k in ('number','name','role','description')))
        with devices_path.open('w',newline='',encoding='utf-8-sig') as f:
            writer=csv.writer(f); writer.writerow(DEVICE_FIELDS+('catalog_id',))
            for row in self.devices:
                writer.writerow([row.get(k,'') for k in DEVICE_FIELDS]+[self.catalog_id])
        return pins_path, devices_path

    def export_svg(self,folder,accepted_only=True):
        folder=Path(folder)
        manifest=[]
        # Numeric prefix prevents filename collisions and Windows reserved names.
        for index,(identifier,entry) in enumerate(sorted(self.pinouts.items()),1):
            if accepted_only and not entry['accepted']:
                continue
            safe=re.sub(r'[^A-Za-z0-9_-]','_',identifier)[:80] or 'pinout'
            filename=f'{index:04d}_{safe}.svg'
            (folder/filename).write_text(diagram(entry['project']).svg(),encoding='utf-8')
            manifest.append({'pinout_id':identifier,'svg_file':filename,'status':'Accepted' if entry['accepted'] else 'Draft'})
        with (folder/'manifest.csv').open('w',newline='',encoding='utf-8-sig') as f:
            writer=csv.DictWriter(f,fieldnames=('pinout_id','svg_file','status'));writer.writeheader();writer.writerows(manifest)
        return len(manifest)
