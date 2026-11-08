"""Read KiCad S-expression symbol libraries without KiCad or third-party modules."""
from dataclasses import dataclass,field
from pathlib import Path
import re
import copy
import json
from collections import defaultdict
from pinout import Project,Pin,validate_count
from bulk import fingerprint,device_key


def parse_sexpr(text):
    roots=[];stack=[];i=0;n=len(text)
    while i<n:
        char=text[i]
        if char.isspace() or char=='\ufeff':i+=1;continue
        if char=='#':
            end=text.find('\n',i);i=n if end<0 else end+1;continue
        if char=='(':
            node=[]
            (stack[-1] if stack else roots).append(node);stack.append(node);i+=1
        elif char==')':
            if not stack:raise ValueError('Unexpected closing parenthesis')
            stack.pop();i+=1
        else:
            if not stack:raise ValueError('Text outside S-expression')
            if char=='"':
                i+=1;value=[]
                while i<n and text[i]!='"':
                    if text[i]=='\\':
                        i+=1
                        if i>=n:raise ValueError('Unterminated string escape')
                        value.append({'n':'\n','r':'\r','t':'\t','"':'"','\\':'\\'}.get(text[i],'\\'+text[i]))
                    else:value.append(text[i])
                    i+=1
                if i>=n:raise ValueError('Unterminated quoted string')
                i+=1;token=''.join(value)
            else:
                start=i
                while i<n and not text[i].isspace() and text[i] not in '()':i+=1
                token=text[start:i]
            stack[-1].append(token)
    if stack:raise ValueError('Unclosed parenthesis')
    if len(roots)!=1 or not roots[0] or roots[0][0]!='kicad_symbol_lib':
        raise ValueError('Expected a .kicad_sym symbol library (legacy .lib is unsupported)')
    return roots[0]


def children(node,key):
    return [x for x in node if isinstance(x,list) and x and x[0]==key]


def value(node,key,default=''):
    found=children(node,key)
    return found[0][1] if found and len(found[0])>1 else default


def properties(node):
    return {p[1]:p[2] for p in children(node,'property') if len(p)>=3}


@dataclass
class ImportResult:
    pinouts:dict=field(default_factory=dict)
    devices:list=field(default_factory=list)
    report:list=field(default_factory=list)
    legacy_pinouts:dict=field(default_factory=dict)
    libraries:list=field(default_factory=list)


def footprint_package_name(name):
    """Normalize only explicit physical-family synonyms; never infer TSOP type."""
    name=re.sub(r'^PowerSO-?20(?=[_*?]|$)','PowerSO20-20',name,flags=re.I)
    name=re.sub(r'^TSOP[-_]?1(?=-)','TSOP-I',name,flags=re.I)
    name=re.sub(r'^TSOP[-_]?2(?=-)','TSOP-II',name,flags=re.I)
    return name


def package_options(props,count):
    footprint=props.get('Footprint','').strip()
    if footprint and footprint!='~':
        name=footprint_package_name(footprint.split(':')[-1])
        if re.match(r'^SOT-89(?:_|$)',name,re.I): name='SOT-89-3'+name[6:]
        match=re.match(r'^(DIP|SOIC|MSOP|TSSOP|SSOP|TSOP-II|TSOP-I|PLCC|PowerSO20|LQFP|TQFP|QFP|QFN|DFN|TO-220|TO-252|TO-247|TO-263AB|TO-263|SOT-223|SOT-89)-(\d+)(?:_|$)',name,re.I)
        if not match:raise ValueError(f'unsupported explicit footprint: {footprint}')
        if int(match[2])!=count:raise ValueError(f'footprint count {match[2]} differs from {count} numbered pins')
        if re.search(r'(?:EP|Exposed|ThermalPad)',name,re.I):raise ValueError('exposed-pad footprints are unsupported')
        package = match[1].upper()
        package = 'QFP' if package in ('LQFP','TQFP') else package
        if package=='POWERSO20':package='PowerSO20'
        validate_count(package,count)
        return [(package,f'Explicit footprint: {footprint}')]
    filters=props.get('ki_fp_filters','')
    options={}
    for token in filters.split():
        name=footprint_package_name(token.split(':')[-1])
        match=re.match(r'^(DIP|SOIC|MSOP|TSSOP|SSOP|TSOP-II|TSOP-I|PLCC|PowerSO20|LQFP|TQFP|QFP|QFN|DFN|TO-220|TO-252|TO-247|TO-263AB|TO-263|SOT-223|SOT-89)(?=[*?0-9_-]|$)(.*)$',name,re.I)
        if not match:
            # Older official libraries use SO14*, SO16*, etc. as SOIC filters.
            short=re.fullmatch(r'SO(\d+)\*?',name,re.I)
            if short and int(short[1])==count:
                options['SOIC']=f'Package candidate from legacy KiCad footprint filter: {token}; confirm SOIC package against datasheet'
            continue
        suffix=match[2]
        counted=re.match(r'^[-_?]?(\d+)(?=[*?_]|$)',suffix)
        if counted and int(counted[1])!=count:continue
        package = match[1].upper()
        package = 'QFP' if package in ('LQFP','TQFP') else package
        if package=='POWERSO20':package='PowerSO20'
        try: validate_count(package,count)
        except ValueError: continue
        options[package]=f'Package candidate from KiCad footprint filter: {token}; confirm exact package variant against datasheet'
    if not options:raise ValueError('no supported explicit footprint or usable supported package footprint filter')
    return list(options.items())


ROLE_BY_TYPE={'input':'Input','output':'Output','bidirectional':'I/O','tri_state':'Output','open_collector':'Output','open_emitter':'Output','no_connect':'NC','power_in':'Power','power_out':'Power'}
LABEL_PREFIX={'Input':'IN','Output':'OUT','I/O':'IO'}


def plain_name(name):
    """Convert KiCad text markup anywhere in a name: ~{CS} overbar -> /CS, V_{CC} or x^{2} -> VCC, x2."""
    for _ in range(4):
        updated=re.sub(r'~\{([^{}]*)\}',r'/\1',name)
        updated=re.sub(r'[_^]\{([^{}]*)\}',r'\1',updated)
        if updated==name:break
        name=updated
    return name


def copy_pins(pins):
    # Pin fields are immutable values, so new Pin objects make an independent (deep) copy cheaply.
    return [Pin(p.number,p.name,p.role,p.description) for p in pins]


def pad_key(number):
    """Natural order for mixed pad identifiers: 1, 2, 10, A1, A2, A10, EP."""
    return [(0,int(x),'') if x.isdecimal() else (1,0,x) for x in re.split(r'([0-9]+)',str(number)) if x]


def _legacy_pins(node, pad_numbers=False):
    """pad_numbers=True keeps non-numeric pads (EP, A1, 01) as string numbers; only for
    records retained as unsupported/unresolved, never for drawable package variants."""
    # Style 0 is common to styles; style 1 is normal. Never combine De Morgan style 2.
    selected=list(children(node,'pin'))
    for unit in children(node,'symbol'):
        name=unit[1] if len(unit)>1 else ''
        match=re.search(r'_(\d+)_(\d+)$',name)
        if not match:raise ValueError(f'unrecognised unit identifier: {name}')
        if int(match[2]) in (0,1):selected.extend(children(unit,'pin'))
    pins={}
    for item in selected:
        number=value(item,'number')
        if re.fullmatch(r'[1-9]\d*',number):number=int(number)
        elif not pad_numbers:raise ValueError(f'unsupported pin number: {number!r}')
        elif not isinstance(number,str) or not number.strip():raise ValueError('pin without a number')
        name=value(item,'name');electrical=item[1] if len(item)>1 else ''
        role=ROLE_BY_TYPE.get(electrical,'Signal')
        if role=='Power' and re.fullmatch(r'(?:[ADP]?GND|GROUND|GNDA|GNDD|GNDP)',name,re.I):role='Ground'
        unnamed=name in ('','~')
        if unnamed:
            prefix={'Input':'IN','Output':'OUT','I/O':'IO','Power':'PWR','Ground':'GND','NC':'NC'}.get(role,'PIN')
            name='NC' if role=='NC' else f'{prefix}{number}'
        if name.startswith('~{') and name.endswith('}') and name.count('{')==1:name='/'+name[2:-1]
        description=f'KiCad electrical type: {electrical}'
        if unnamed:description+='; generated label (original pin name absent)' 
        alternatives=children(item,'alternate')
        if alternatives:description+='; alternate functions: '+', '.join(str(x[1]) for x in alternatives if len(x)>1)
        pin=Pin(number,name,role,description)
        if number in pins and pins[number]!=pin:raise ValueError(f'conflicting definitions for pin {number}')
        pins[number]=pin
    if not pins:raise ValueError('no normal-style pins')
    return [pins[n] for n in sorted(pins,key=pad_key)]


def channel_name(index):
    result=''
    while index:
        index,rem=divmod(index-1,26);result=chr(65+rem)+result
    return result


def get_pins(node,pins=None):
    """Keep electrical pins intact while retaining source unit membership.

    pins may be a fresh copy of _legacy_pins(node); it is relabelled in place."""
    pins=_legacy_pins(node) if pins is None else pins
    records=defaultdict(list)
    selected=[(0,p) for p in children(node,'pin')]
    for unit in children(node,'symbol'):
        match=re.search(r'_(\d+)_(\d+)$',unit[1])
        if match and int(match[2]) in (0,1):
            selected.extend((int(match[1]),p) for p in children(unit,'pin'))
    for unit,item in selected:
        records[int(value(item,'number'))].append((unit,item))
    signal_types={'input','output','bidirectional','tri_state','open_collector','open_emitter'}
    signal_units=sorted({unit for unit,item in selected if unit>0 and item[1] in signal_types})
    channels={unit:channel_name(i+1) for i,unit in enumerate(signal_units)}
    named_units=defaultdict(set)
    for unit,item in selected:
        raw=value(item,'name')
        if unit in channels and item[1] in signal_types and raw not in ('','~'):
            named_units[raw].add(unit)
    unnamed=defaultdict(list)
    for number,items in records.items():
        units={u for u,_ in items};item=items[0][1]
        if len(units)==1 and value(item,'name') in ('','~'):
            # Group by label prefix: output and tri-state pins both become OUT_*.
            unnamed[(items[0][0],LABEL_PREFIX.get(ROLE_BY_TYPE.get(item[1]),'PIN'))].append(number)
    for pin in pins:
        items=records[pin.number];units=sorted({u for u,_ in items});item=items[0][1]
        raw=value(item,'name');channel=channels.get(units[0]) if len(units)==1 else None
        electrical=item[1];original_absent=raw in ('','~')
        generated=False
        # Legacy names keep the older whole-name overbar rule so earlier imports still refresh.
        pin.name=plain_name(pin.name)
        if original_absent and channel and electrical in signal_types:
            prefix=LABEL_PREFIX.get(pin.role,'PIN')
            peers=sorted(unnamed[(units[0],prefix)])
            suffix=str(peers.index(pin.number)+1) if len(peers)>1 else ''
            pin.name=f'{prefix}_{channel}{suffix}';generated=True
        elif raw in ('+','-','−') and electrical=='input' and channel:
            pin.name=f'IN_{channel}'+('−' if raw in ('-','−') else '+');generated=True
        if not generated and not original_absent and channel and electrical in signal_types and len(named_units[raw])>1:
            pin.name+='_'+channel;generated=True
        pin.description += '; KiCad source name: '+json.dumps(raw,ensure_ascii=False)+'; units: '+','.join(map(str,units))
        if generated:pin.description+='; display label derived from symbol unit (not a datasheet name)'
        if original_absent and not generated and pin.role!='NC':
            pin.description+='; no unambiguous signal unit; physical-pin fallback retained'
    return pins


def load_libraries(paths, preserve_unsupported=False):
    result=ImportResult();registry={};bad=set()
    for raw in paths:
        path=Path(raw)
        namespace=path.parent.name.removesuffix('.kicad_symdir') if path.parent.name.endswith('.kicad_symdir') else path.stem
        try:
            root=parse_sexpr(path.read_text(encoding='utf-8-sig'))
            symbols=children(root,'symbol')
            # Check the whole file before registering anything, so a FILE ERROR imports nothing from it.
            if any(len(symbol)<2 or not isinstance(symbol[1],str) for symbol in symbols):raise ValueError('Invalid symbol name')
        except (OSError,ValueError) as exc:
            result.report.append(f'FILE ERROR {path.name}: {exc}');continue
        result.libraries.append(namespace)
        for symbol in symbols:
            key=(namespace,symbol[1])
            if key in registry:
                bad.add(key);result.report.append(f'REJECTED {namespace}:{symbol[1]}: duplicate symbol identity in selected files')
            else:registry[key]=(symbol,path)
    cache={}
    def resolve(key,chain=()):
        if key in bad:raise ValueError('duplicate symbol identity')
        if key in chain:raise ValueError('inheritance cycle')
        if len(chain)>100:raise ValueError('inheritance chain too deep')
        if key in cache:return cache[key]
        if key not in registry:raise ValueError(f'missing inherited symbol: {key[0]}:{key[1]} (select its file too)')
        symbol,path=registry[key];props={};pin_node=symbol
        parent=value(symbol,'extends')
        if parent:
            parentkey=tuple(parent.split(':',1)) if ':' in parent else (key[0],parent)
            inherited,pin_node=resolve(parentkey,chain+(key,));props.update(inherited)
            if children(symbol,'pin') or children(symbol,'symbol'):raise ValueError('derived symbol overrides pin units; manual review required')
        props.update(properties(symbol));cache[key]=(props,pin_node);return cache[key]
    for key,(raw,path) in registry.items():
        namespace,name=key;props=properties(raw);pins=[]
        try:
            props,node=resolve(key)
            # Parse pins once; every package variant gets its own copies (editing one never edits another).
            legacy=_legacy_pins(node);pins=get_pins(node,copy_pins(legacy));count=max(p.number for p in pins)
            unnamed=sum('generated label' in p.description for p in pins)
            if unnamed:result.report.append(f'NOTE {namespace}:{name}: {unnamed} unnamed pins use unit-aware labels where unambiguous, otherwise role/number fallbacks')
            packages=package_options(props,count)
            for package, _ in packages:
                Project(name,package,count,pins=pins).validate()
            for package,reason in packages:
                identifier=f'KiCad:{namespace}:{name}:{package}-{count}'
                datasheet=props.get('Datasheet','');datasheet='' if datasheet=='~' else datasheet
                source=f'KiCad {namespace}:{name}; {reason}'+(f'; {datasheet}' if datasheet else '')
                result.pinouts[identifier]={'project':Project(name,package,count,source=source,pins=copy_pins(pins)),'accepted':False}
                result.legacy_pinouts[identifier]=Project(name,package,count,source=source,pins=copy_pins(legacy))
                manufacturer=props.get('Manufacturer') or props.get('manufacturer') or 'Unspecified (KiCad)'
                result.devices.append(dict(device=name,manufacturer=manufacturer,package=f'{package}-{count}',pinout_id=identifier,source_url=datasheet,source_page='',notes=f'Imported from {path.name}; {reason}; source page not provided by library'))
                result.report.append(f'IMPORTED {namespace}:{name} → {package}-{count}. {reason}')
        except (ValueError,TypeError,IndexError) as exc:
            if preserve_unsupported and not pins:
                # Pads such as EP, A1 or 01: keep the record with its pad names for review.
                try:
                    pins=[Pin(p.number,plain_name(p.name),p.role,p.description) for p in _legacy_pins(resolve(key)[1],pad_numbers=True)]
                    if any(isinstance(p.number,str) for p in pins):
                        exc=ValueError(f'{exc}; pad identifiers kept as text')
                    else:pins=[]
                except (ValueError,TypeError,IndexError):pins=[]
            if preserve_unsupported and pins:
                raw_package = props.get('Footprint') or 'Unresolved package'
                identifier = f'KiCad:{namespace}:{name}:unresolved'
                result.pinouts[identifier] = {'project':Project(name, raw_package, len(pins),
                    source=props.get('Datasheet',''), pins=copy_pins(pins)), 'accepted':False}
                result.devices.append(dict(device=name,manufacturer=props.get('Manufacturer') or '',
                    package=f'{raw_package}-{len(pins)}',pinout_id=identifier,source_url=props.get('Datasheet',''),
                    source_page='',notes=str(exc)))
                result.report.append(f'RETAINED {namespace}:{name}: {exc}')
                continue
            result.report.append(f'SKIPPED {namespace}:{name}: {exc}')
            result.devices.append(dict(device=name,manufacturer=props.get('Manufacturer') or 'Unspecified (KiCad)',package=props.get('Footprint') or 'Unresolved',pinout_id='',source_url=props.get('Datasheet','').replace('~','') if props.get('Datasheet')=='~' else props.get('Datasheet',''),source_page='',notes=f'KiCad {namespace}:{name}: {exc}'))
    return result


def merge_result(catalog,result):
    """Merge with existing-ID protection; do not attach links to conflicting data."""
    report=list(result.report);added=[];blocked=set()
    for identifier,entry in result.pinouts.items():
        if identifier in catalog.retired_ids:
            blocked.add(identifier);report.append(f'CONFLICT {identifier}: deleted identity; use a new pinout ID');continue
        if identifier in catalog.pinouts:
            if fingerprint(catalog.pinouts[identifier]['project'])!=fingerprint(entry['project']):
                legacy=result.legacy_pinouts.get(identifier)
                if legacy is not None and fingerprint(catalog.pinouts[identifier]['project'])==fingerprint(legacy):
                    updated=copy.deepcopy(catalog.pinouts[identifier]['project'])
                    updated.pins=copy.deepcopy(entry['project'].pins)
                    catalog.pinouts[identifier]={'project':updated,'accepted':False}
                    report.append(f'UPDATED {identifier}: unit-aware pin labels refreshed; title, package and source note kept; identity retained')
                else:
                    blocked.add(identifier);report.append(f'CONFLICT {identifier}: existing mapping and links kept')
            else:report.append(f'UNCHANGED {identifier}')
        else:catalog.pinouts[identifier]=entry;added.append(identifier)
    keys={device_key(d):d for d in catalog.devices}
    for row in result.devices:
        if row['pinout_id'] in blocked:continue
        key=device_key(row)
        if key in keys:
            if keys[key]!=row:report.append(f'CONFLICT device {row["device"]} / {row["package"]}: existing link/source kept')
            continue
        catalog.devices.append(row);keys[key]=row
        if row['pinout_id'] in catalog.pinouts:catalog.pinouts[row['pinout_id']]['accepted']=False
    catalog.report=report;catalog.dirty=True
    return added
