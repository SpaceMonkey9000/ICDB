"""ICPin 0.8.0: pin table parsing, validation and deterministic diagrams."""
from dataclasses import dataclass, asdict, field
from pathlib import Path
import csv
import io
import json
import re
import math
import os
from html import escape

# Renderer version: bump whenever drawn output changes (publish caches key on it).
VERSION = '0.8.2'
PACKAGES = ('DIP', 'SOIC', 'MSOP', 'TSSOP', 'SSOP', 'TSOP-I', 'TSOP-II', 'PLCC', 'PowerSO20', 'QFP', 'QFN', 'DFN', 'TO-220', 'TO-252', 'SOT-89', 'TO-247', 'TO-263', 'TO-263AB', 'SOT-223')
EXPOSED_PAD_PACKAGES = ('SOIC', 'MSOP', 'SSOP', 'TSSOP', 'QFP', 'QFN', 'DFN', 'PowerSO20')
MAX_PINS = 256
PLCC_COUNTS = (20, 28, 32, 44, 52, 68, 84)

def count_limits(package):
    if package == 'PowerSO20': return (20, 20, 1)
    if package == 'PLCC': return (20, 84, 4)
    if package in ('TSOP-I', 'TSOP-II'): return (8, 86, 2)
    if package in ('QFP', 'QFN'): return (4, MAX_PINS, 4)
    if package in ('TO-220', 'TO-252', 'TO-263'): return (3, 7, 2)
    if package == 'TO-247': return (3, 4, 1)
    if package == 'TO-263AB': return (3, 7, 2)
    if package == 'SOT-223': return (3, 4, 1)
    if package == 'SOT-89': return (3, 3, 1)
    return (4, 64, 2)

def validate_count(package, count):
    if package not in PACKAGES:
        raise ValueError('Choose a supported package: ' + ', '.join(PACKAGES))
    if package == 'PLCC' and (type(count) is not int or count not in PLCC_COUNTS):
        raise ValueError('PLCC pin count must be ' + ', '.join(map(str, PLCC_COUNTS)) + '.')
    low, high, step = count_limits(package)
    if type(count) is not int or not low <= count <= high or (count-low) % step:
        if low == high: rule = str(low)
        elif package in ('TO-220', 'TO-252', 'TO-263'): rule = '3, 5 or 7'
        else: rule = f'{low}–{high}, in steps of {step}'
        raise ValueError(f'{package} pin count must be {rule}.')

def package_view(package):
    return 'Front view' if package in ('TO-220', 'TO-247') else 'Top view'

ROLES = ('Signal', 'Power', 'Ground', 'Input', 'Output', 'I/O', 'NC')
# Characters that XML 1.0 forbids even when escaped (ICDB rejects such SVGs).
XML_ILLEGAL = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')


def xml_safe(text):
    return XML_ILLEGAL.sub('', text)


def check_text(label, text):
    bad = XML_ILLEGAL.search(text)
    if bad:
        raise ValueError(f'{label} contains an invisible control character (U+{ord(bad.group()):04X}); retype it or remove it.')

def exposed_pad(data):
    """Canonical optional terminal; normal lead count excludes the underside pad."""
    pad = data.get('exposed_pad') if isinstance(data, dict) else data.exposed_pad
    if pad is None:
        return None
    if not isinstance(pad, dict):
        raise ValueError('Exposed pad must be a terminal object or null.')
    if type(pad.get('enabled', True)) is not bool:
        raise ValueError('Exposed pad enabled must be true or false.')
    if not pad.get('enabled', True):
        return None
    number = pad.get('number', 'EP')
    if isinstance(number, bool) or not isinstance(number, (str, int)) or not str(number).strip():
        raise ValueError('Enter an exposed-pad identifier, such as EP or 9.')
    result = dict(number=str(number).strip(), name=pad.get('name', ''),
                  role=pad.get('role', 'Signal'), description=pad.get('description', ''))
    for key in ('number', 'name', 'role', 'description'):
        if not isinstance(result[key], str):
            raise ValueError('Exposed-pad '+key+' must be text.')
        check_text('Exposed-pad '+key, result[key])
    if not result['name'].strip():
        raise ValueError('Enter the exposed-pad connection/name (GND, VIN, NC, etc.).')
    if result['role'] not in ROLES:
        raise ValueError('Unknown exposed-pad role: '+result['role'])
    pins = data.get('pins', []) if isinstance(data, dict) else data.pins
    numbers = [p['number'] if isinstance(p, dict) else p.number for p in pins]
    def identity(n):
        s = str(n).strip()
        return str(int(s)) if s.isdecimal() else s.casefold()
    if identity(number) in {identity(n) for n in numbers}:
        raise ValueError('Exposed-pad identifier duplicates a normal lead number.')
    return result


def project_label(data):
    package = data['package'] if isinstance(data, dict) else data.package
    count = data['count'] if isinstance(data, dict) else data.count
    return f'{package}-{count}' + ('-EP' if exposed_pad(data) else '')


@dataclass
class Pin:
    number: int
    name: str
    role: str = 'Signal'
    description: str = ''

@dataclass
class Project:
    device: str = 'Untitled device'
    package: str = 'SOIC'
    count: int = 8
    source: str = ''
    verified: bool = False
    pins: list[Pin] = field(default_factory=list)
    exposed_pad: dict | None = None

    def validate(self):
        validate_count(self.package, self.count)
        if not self.device.strip():
            raise ValueError('Enter a device name.')
        check_text('The device name', self.device)
        if exposed_pad(self) and self.package not in EXPOSED_PAD_PACKAGES:
            raise ValueError('Exposed pad is not supported for '+self.package+'.')
        seen = set()
        for pin in self.pins:
            if type(pin.number) is not int or not 1 <= pin.number <= self.count:
                raise ValueError(f'Pin number {pin.number} is outside 1–{self.count}.')
            if pin.number in seen:
                raise ValueError(f'Duplicate pin number: {pin.number}.')
            seen.add(pin.number)
            if not pin.name.strip():
                raise ValueError(f'Pin {pin.number} needs a name. Use NC for an unconnected pin.')
            check_text(f'The name of pin {pin.number}', pin.name)
            if pin.role not in ROLES:
                raise ValueError(f'Unknown role for pin {pin.number}: {pin.role}.')
        missing = sorted(set(range(1, self.count + 1)) - seen)
        if missing:
            raise ValueError('Missing pin numbers: ' + ', '.join(map(str, missing)))

    def save(self, path):
        self.validate()
        payload = {'schema_version': 1, **asdict(self)}
        if exposed_pad(self): payload['exposed_pad'] = exposed_pad(self)
        else: payload.pop('exposed_pad', None)
        target = Path(path)
        temp = target.with_name(target.name + '.tmp')
        try:
            with temp.open('w', encoding='utf-8') as handle:
                handle.write(json.dumps(payload, indent=2, ensure_ascii=False))
                handle.flush()
                os.fsync(handle.fileno())
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict) or data.get('schema_version') != 1:
            raise ValueError('Unsupported project format.')
        data = dict(data)
        data.pop('schema_version')
        data['pins'] = [Pin(**pin) for pin in data['pins']]
        result = cls(**data)
        clean_project(result)
        result.validate()
        return result


def clean_project(project):
    """Drop XML-illegal characters from drawn text so older files still open."""
    if isinstance(project.device, str):
        project.device = xml_safe(project.device)
    for pin in project.pins:
        if isinstance(pin.name, str):
            pin.name = xml_safe(pin.name)
    return project


def guess_delimiter(text, lines):
    """Of the separators in the first row, prefer tab, semicolon, then comma: the first that splits every sampled row into 2-4 cells."""
    sample = '\n'.join(text.splitlines()[:40])
    for delimiter in ('\t', ';', ','):
        if delimiter not in lines[0]:
            continue
        try:
            rows = [row for row in csv.reader(io.StringIO(sample), delimiter=delimiter) if any(x.strip() for x in row)]
        except csv.Error:
            continue
        if rows and all(2 <= len(row) <= 4 for row in rows):
            return delimiter
    return next((d for d in ('\t', ';', ',') if d in lines[0]), None)


def parse_table(text):
    """Accept CSV, TSV, semicolon tables, or '1 NAME' lines. Never infer roles."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError('Paste a pin table first.')
    delimiter = guess_delimiter(text, lines)
    if delimiter:
        # Parse the original text so quoted cells may span several lines.
        rows = (row for row in csv.reader(io.StringIO(text), delimiter=delimiter) if any(x.strip() for x in row))
    else:
        rows = (re.split(r'\s+', line.strip(), maxsplit=1) for line in lines)
    pins = []
    seen = set()
    for index, row in enumerate(rows, 1):
        row = [x.strip() for x in row]
        if index == 1 and row[0].casefold() in ('pin', 'number', 'pin number', 'pin_number'):
            continue
        if len(row) < 2 or len(row) > 4:
            raise ValueError(f'Row {index}: use number, name, optional role, optional description.')
        try:
            number = int(row[0])
        except ValueError:
            raise ValueError(f'Row {index}: {row[0]!r} is not a pin number.') from None
        if number in seen:
            raise ValueError(f'Row {index}: duplicate pin {number}.')
        if number < 1 or number > MAX_PINS or not row[1]:
            raise ValueError(f'Row {index}: use pin numbers 1–256 and a non-empty name.')
        role = row[2] if len(row) >= 3 and row[2] else 'Signal'
        role = next((r for r in ROLES if r.casefold() == role.casefold()), None)
        if role is None:
            raise ValueError(f'Row {index}: role must be one of {", ".join(ROLES)}.')
        seen.add(number)
        pins.append(Pin(number, row[1], role, row[3] if len(row) == 4 else ''))
    if not pins:
        raise ValueError('The table contains no pins.')
    return sorted(pins, key=lambda pin: pin.number)


def table_text(pins):
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter='\t', lineterminator='\n')
    writer.writerow(('Number', 'Name', 'Role', 'Description'))
    for pin in sorted(pins, key=lambda pin: pin.number):
        writer.writerow((pin.number, pin.name, pin.role, pin.description))
    return output.getvalue()


class Scene:
    def __init__(self, width, height):
        self.width, self.height, self.items = width, height, []

    def rect(self, x, y, w, h, fill, stroke='none', dash=None):
        style = {'fill': fill, 'stroke': stroke}
        if dash: style['dash'] = dash
        self.items.append(('rect', (x, y, w, h), style))

    def ellipse(self, x, y, w, h, fill, stroke='none'):
        self.items.append(('ellipse', (x, y, w, h), {'fill': fill, 'stroke': stroke}))

    def polygon(self, points, fill='#ffffff', stroke='#000000'):
        self.items.append(('polygon', tuple(v for point in points for v in point), {'fill':fill,'stroke':stroke}))

    def line(self, x1, y1, x2, y2):
        self.items.append(('line',(x1,y1,x2,y2),{'fill':'#000000','stroke':'#000000'}))

    def rounded_rect(self, x, y, w, h, radius):
        points=[]
        for cx,cy,start in [(x+w-radius,y+radius,-90),(x+w-radius,y+h-radius,0),(x+radius,y+h-radius,90),(x+radius,y+radius,180)]:
            for i in range(7):
                angle=math.radians(start+i*15)
                points.append((cx+radius*math.cos(angle),cy+radius*math.sin(angle)))
        self.polygon(points)


    def text(self, x, y, value, size=16, fill='#182235', anchor='middle', bold=False, rotation=0):
        # SVG collapses whitespace but Tk draws newlines; store one form for both.
        value = display_text(value)
        self.items.append(('text', (x, y), dict(value=value, size=size, fill=fill, anchor=anchor, bold=bold, rotation=rotation)))

    def svg(self):
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}">']
        for kind, pos, style in self.items:
            if kind == 'text':
                x, y = pos
                transform = f' transform="rotate({-style.get("rotation", 0)} {x} {y})"' if style.get('rotation') else ''
                parts.append(f'<text{transform} x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="{style["size"]}" font-weight="{700 if style["bold"] else 400}" fill="{style["fill"]}" text-anchor="{style["anchor"]}" dominant-baseline="central">{escape(xml_safe(style["value"]))}</text>')
            elif kind == 'polygon':
                points=' '.join(f'{pos[i]:.3f},{pos[i+1]:.3f}' for i in range(0,len(pos),2))
                parts.append(f'<polygon points="{points}" fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-linejoin="round"/>')
            elif kind == 'line':
                parts.append(f'<line x1="{pos[0]}" y1="{pos[1]}" x2="{pos[2]}" y2="{pos[3]}" stroke="#000000"/>')
            elif kind == 'rect':

                x, y, w, h = pos
                dashed = ' stroke-dasharray="'+style['dash']+'"' if style.get('dash') else ''
                parts.append(f'<rect{dashed} x="{x}" y="{y}" width="{w}" height="{h}" fill="{style["fill"]}" stroke="{style["stroke"]}"/>')
            else:
                x, y, w, h = pos
                parts.append(f'<ellipse cx="{x+w/2}" cy="{y+h/2}" rx="{w/2}" ry="{h/2}" fill="{style["fill"]}" stroke="{style.get("stroke", "none")}"/>')
        return '\n'.join(parts + ['</svg>'])

    def draw_canvas(self, canvas):
        canvas.delete('all')
        scale = min(max(canvas.winfo_width(), 100) / self.width, max(canvas.winfo_height(), 100) / self.height)
        dx = (canvas.winfo_width() - self.width * scale) / 2
        dy = (canvas.winfo_height() - self.height * scale) / 2
        for kind, pos, s in self.items:
            x, y = pos[:2]
            x, y = dx + x * scale, dy + y * scale
            if kind == 'text':
                canvas.create_text(x, y, text=s['value'], fill=s['fill'], angle=s.get('rotation',0), anchor={'start':'w', 'middle':'center', 'end':'e'}[s['anchor']], font=('Arial', -max(1, round(s['size'] * scale)), 'bold' if s['bold'] else 'normal'))
            elif kind in ('polygon','line'):
                coords=[(dx if i%2==0 else dy)+value*scale for i,value in enumerate(pos)]
                if kind=='line':canvas.create_line(*coords,fill=s['fill'],width=max(1,scale))
                else:canvas.create_polygon(*coords,fill=s['fill'],outline=s['stroke'],width=max(1,scale))
            else:
                coords = (x, y, x+pos[2]*scale, y+pos[3]*scale)

                method = canvas.create_rectangle if kind == 'rect' else canvas.create_oval
                options = {'dash': tuple(int(x) for x in s['dash'].split())} if s.get('dash') else {}
                method(*coords, **options, fill=s['fill'], outline='' if s.get('stroke', 'none') == 'none' else s['stroke'],width=max(1,scale))


def display_text(value):
    """Rendered form of a label: whitespace runs (including newlines) become one space."""
    return ' '.join(str(value).split())


# Estimates assume Arial; viewers substitute other sans-serif fonts, which run wider.
TEXT_PADDING = 1.1


def text_extent(text,size):
    # Conservative bounds without adding a font-library dependency to ICPin.
    text = display_text(text)
    return sum(.4 if c in ' ilI.,:;!|\'' else 1.05 if c in 'MWmw@#%&' or ord(c)>127 else .8 for c in text)*size*TEXT_PADDING


def digits_width(text, size):
    """Arial digits are 0.556 em wide; used to keep pin numbers clear of outlines."""
    return len(str(text))*.556*size


def draw_exposed_pad(scene, project, left, top, right, bottom):
    pad = exposed_pad(project)
    if pad is None:
        return
    gap = 38 if project.package in ('QFN', 'DFN') else 28
    l, r, t, b = left+gap, right-gap, top+gap, bottom-gap
    cx, cy = (l+r)/2, (t+b)/2
    # Small bodies still need enough space for the identifier and connection.
    if r-l < 30: l, r = cx-15, cx+15
    if b-t < 50: t, b = cy-25, cy+25
    scene.rect(l, t, r-l, b-t, '#f3f3f3', '#000000', dash='4 3')
    for value, y, size, bold in [(pad['number'],cy-15,12,False),
                                 (pad['name'],cy+1,14,True),('underside',cy+17,9,False)]:
        size = min(size, size*(r-l-8)/max(1,text_extent(value,size)))
        scene.text(cx,y,value,size,'#000000',bold=bold)


def diagram(project):
    project.validate()
    if project.package == 'PLCC':
        return plcc_diagram(project)
    if project.package == 'TSOP-II':
        return tsop_ii_diagram(project)
    if project.package in ('QFP', 'QFN', 'DFN'):
        return leadless_quad_diagram(project)
    if project.package in ('TO-220', 'TO-252', 'SOT-89', 'TO-247', 'TO-263', 'TO-263AB', 'SOT-223'):
        return power_diagram(project)
    half=project.count//2
    body_width,pitch,lead_length,lead_height={'DIP':(98,30,11,10),'SOIC':(114,30,28,9),'MSOP':(100,24,24,7),'TSSOP':(170,24,32,7),
        'SSOP':(136,24,28,7),'TSOP-I':(max(330,((half-1)*22+52)*1.45),22,28,7),'PowerSO20':(210,26,23,10)}[project.package]
    margin=max(60,max(text_extent(p.name,16) for p in project.pins)+lead_length+18)
    width=math.ceil(max(margin*2+body_width,text_extent(project.device,22)+24))
    cx=width/2;left=cx-body_width/2;right=cx+body_width/2
    top=76;end_space=26;body_height=(half-1)*pitch+end_space*2
    height=top+body_height+12
    scene=Scene(width,height);scene.rect(0,0,width,height,'#ffffff')
    scene.text(cx,22,project.device,22,'#000000',bold=True)
    scene.text(cx,49,('PowerSO20' + ('-EP' if exposed_pad(project) else '')) if project.package=='PowerSO20' else project_label(project),14,'#000000')
    # Leads are behind the moulded body. Segment lines suggest the lead bends.
    for pin in project.pins:
        is_left=pin.number<=half;row=pin.number-1 if is_left else project.count-pin.number
        y=top+end_space+row*pitch;edge=left if is_left else right
        scene.rect(edge-lead_length if is_left else edge,y-lead_height/2,lead_length,lead_height,'#ffffff','#000000')
        if project.package!='DIP':
            for fraction in (.4,.75):
                x=edge+(-1 if is_left else 1)*lead_length*fraction
                scene.line(x,y-lead_height/2,x,y+lead_height/2)
    if project.package=='DIP':
        # Two continuous notched contours, avoiding white masks over the outline.
        for inset,radius in [(0,10),(3,12)]:
            x1=left+inset;x2=right-inset;y1=top+inset;bottom=top+body_height-inset
            points=[(x1,y1),(cx-radius,y1)]
            points.extend((cx+radius*math.cos(math.pi-i*math.pi/20),y1+radius*math.sin(math.pi-i*math.pi/20)) for i in range(21))
            points.extend([(x2,y1),(x2,bottom),(x1,bottom)])
            scene.polygon(points)
    elif project.package in ('SOIC','SSOP'):
        scene.rounded_rect(left,top,body_width,body_height,7)
        scene.rounded_rect(left+3,top+3,body_width-6,body_height-6,5)
        scene.ellipse(left+22,top+11,9,9,'#ffffff','#000000')
    elif project.package=='PowerSO20':
        # Top view: the two short-edge recesses follow the supplied outline.
        # The underside thermal slug is not an invented numbered terminal.
        for inset in (0,4):
            l,r,t,b=left+inset,right-inset,top+inset,top+body_height-inset
            notch=22-inset;depth=20-inset;corner=9
            scene.polygon([(l+corner,t),(cx-notch,t),(cx-notch,t+depth),(cx+notch,t+depth),
                (cx+notch,t),(r-corner,t),(r,t+corner),(r,b-corner),(r-corner,b),
                (cx+notch,b),(cx+notch,b-depth),(cx-notch,b-depth),(cx-notch,b),
                (l+corner,b),(l,b-corner),(l,t+corner)])
        scene.ellipse(left+20,top+11,9,9,'#ffffff','#000000')
    else:
        scene.rect(left,top,body_width,body_height,'#ffffff','#000000')
        scene.rect(left+5,top+5,body_width-10,body_height-10,'#ffffff','#000000')
        for x,y,sx,sy in [(left,top,1,1),(right,top,-1,1),(left,top+body_height,1,-1),(right,top+body_height,-1,-1)]:
            scene.line(x,y,x+sx*5,y+sy*5)
        scene.ellipse(left+27,top+10,12,12,'#ffffff','#000000')
    draw_exposed_pad(scene, project, left, top, right, top+body_height)
    for pin in project.pins:
        is_left=pin.number<=half;row=pin.number-1 if is_left else project.count-pin.number
        y=top+end_space+row*pitch
        scene.text(left+12 if is_left else right-12,y,str(pin.number),13,'#000000','start' if is_left else 'end')
        scene.text(left-lead_length-8 if is_left else right+lead_length+8,y,pin.name,16,'#000000','end' if is_left else 'start',True)
    return scene


def tsop_ii_diagram(project):
    """Top view matching the reference: pin 1 lower left, CCW numbering."""
    n=project.count//2;pitch,end,lead=28,26,28
    bw=max(210,(n-1)*pitch+2*end);bh=max(130,bw*.42)
    room=max(text_extent(p.name,16) for p in project.pins)+lead+38
    width=math.ceil(max(bw+60,text_extent(project.device,22)+24));cx=width/2
    left=cx-bw/2;right=left+bw;top=76+room;bottom=top+bh
    scene=Scene(width,math.ceil(bottom+room));scene.rect(0,0,width,scene.height,'#ffffff')
    scene.text(cx,22,project.device,22,'#000000',bold=True)
    scene.text(cx,49,f'TSOP-II-{project.count}',14,'#000000')
    positions=[]
    for pin in sorted(project.pins,key=lambda p:p.number):
        lower=pin.number<=n;row=pin.number-1 if lower else project.count-pin.number
        x=left+end+row*pitch;y=bottom if lower else top;dy=1 if lower else -1
        positions.append((pin,x,y,dy))
        scene.rect(x-3.5,y if lower else y-lead,7,lead,'#ffffff','#000000')
        for f in (.4,.75):scene.line(x-3.5,y+dy*lead*f,x+3.5,y+dy*lead*f)
    for inset in (0,4):
        scene.rect(left+inset,top+inset,bw-2*inset,bh-2*inset,'#ffffff','#000000')
    for x,y,sx,sy in [(left,top,1,1),(right,top,-1,1),(left,bottom,1,-1),(right,bottom,-1,-1)]:
        scene.line(x,y,x+sx*4,y+sy*4)
    scene.ellipse(left+12,bottom-34,10,10,'#ffffff','#000000')
    for pin,x,y,dy in positions:
        scene.text(x,y-dy*12,str(pin.number),12,'#000000')
        scene.text(x,y+dy*(lead+10),pin.name,16,'#000000','end' if dy>0 else 'start',True,rotation=90)
    return scene


def plcc_positions(count):
    """PLCC32 is rectangular (7/9/7/9); other supported sizes are square.

    Pin 1 is at the middle of the top edge, not at the QFP corner.
    Coordinates are relative to the body, in counter-clockwise order.
    """
    horizontal,vertical=(7,9) if count==32 else (count//4,count//4)
    pitch,end=32,34;bw=(horizontal-1)*pitch+2*end;bh=(vertical-1)*pitch+2*end
    edge=[(bw-end-i*pitch,0,0,-1) for i in range(horizontal)]
    edge += [(0,end+i*pitch,-1,0) for i in range(vertical)]
    edge += [(end+i*pitch,bh,0,1) for i in range(horizontal)]
    edge += [(bw,bh-end-i*pitch,1,0) for i in range(vertical)]
    return bw,bh,{(i-horizontal//2)%count+1:pos for i,pos in enumerate(edge)}


def plcc_diagram(project):
    bw,bh,positions=plcc_positions(project.count);lead=16
    margin=max(65,max(text_extent(p.name,16) for p in project.pins)+lead+38)
    width=math.ceil(max(bw+2*margin,text_extent(project.device,22)+24));cx=width/2
    left=cx-bw/2;top=76+margin;right=left+bw;bottom=top+bh
    scene=Scene(width,math.ceil(bottom+margin));scene.rect(0,0,width,scene.height,'#ffffff')
    scene.text(cx,22,project.device,22,'#000000',bold=True)
    scene.text(cx,49,f'PLCC-{project.count}',14,'#000000')
    for x,y,dx,dy in positions.values():
        x+=left;y+=top
        if dx:
            scene.rect(x-lead if dx<0 else x,y-6,lead,12,'#ffffff','#000000')
            scene.line(x+dx*9,y-4,x+dx*9,y+4)
        else:
            scene.rect(x-6,y-lead if dy<0 else y,12,lead,'#ffffff','#000000')
            scene.line(x-4,y+dy*9,x+4,y+dy*9)
    # Bevel at the pin-1 end; compact J leads rather than QFP gull wings.
    for inset,bevel in [(0,16),(4,13)]:
        l,r,t,b=left+inset,right-inset,top+inset,bottom-inset
        scene.polygon([(l+bevel,t),(r,t),(r,b),(l,b),(l,t+bevel)])
    scene.ellipse(cx-8,top+23,16,11,'#ffffff','#000000')
    for pin in project.pins:
        x,y,dx,dy=positions[pin.number];x+=left;y+=top
        scene.text(x-dx*13,y-dy*12,str(pin.number),12,'#000000')
        scene.text(x+dx*(lead+10),y+dy*(lead+10),pin.name,16,'#000000',
            ('end' if dx<0 else 'start') if dx else ('end' if dy>0 else 'start'),True,rotation=0 if dx else 90)
    return scene


def outline(scene, left, top, right, bottom, bevel=7):
    scene.polygon([(left+bevel,top),(right-bevel,top),(right,top+bevel),
                   (right,bottom-bevel),(right-bevel,bottom),(left+bevel,bottom),
                   (left,bottom-bevel),(left,top+bevel)])


def leadless_quad_diagram(project):
    """Top-view numbering; leadless underside metallization projected onto it.

    The projection is deliberate: changing to a bottom view would mirror saved
    electrical mappings. Central pads are geometry only, not an inferred pin.
    """
    qfp = project.package == 'QFP'
    quad = project.package != 'DFN'
    n = project.count // (4 if quad else 2)
    pitch, end = 32, 34
    span = max(120,(n-1)*pitch+2*end)
    bw, bh = (span,span) if quad else (max(150,span*.65),span)
    lead = 28 if qfp else 0
    room = max(text_extent(p.name,16) for p in project.pins)+lead+42
    margin = max(65,room)
    width = math.ceil(max(bw+2*margin,text_extent(project.device,22)+24))
    cx=width/2; left=cx-bw/2; right=left+bw
    top=76+margin; bottom=top+bh
    scene=Scene(width,math.ceil(bottom+margin))
    scene.rect(0,0,scene.width,scene.height,'#ffffff')
    scene.text(cx,22,project.device,22,'#000000',bold=True)
    scene.text(cx,49,project_label(project),14,'#000000')
    positions=[]
    for pin in sorted(project.pins,key=lambda p:p.number):
        side,row=divmod(pin.number-1,n)
        if not quad:
            # Vertical DFN, pin 1 at upper left, counter-clockwise (top view).
            x,y,dx,dy=(left,top+end+row*pitch,-1,0) if side==0 else (right,bottom-end-row*pitch,1,0)
        elif side==0: x,y,dx,dy=left,top+end+row*pitch,-1,0
        elif side==1: x,y,dx,dy=left+end+row*pitch,bottom,0,1
        elif side==2: x,y,dx,dy=right,bottom-end-row*pitch,1,0
        else: x,y,dx,dy=right-end-row*pitch,top,0,-1
        positions.append((pin,x,y,dx,dy))
        if qfp:
            if dx:
                scene.rect(x-lead if dx<0 else x,y-4,lead,8,'#ffffff','#000000')
                for f in (.4,.75):scene.line(x+dx*lead*f,y-4,x+dx*lead*f,y+4)
            else:
                scene.rect(x-4,y-lead if dy<0 else y,8,lead,'#ffffff','#000000')
                for f in (.4,.75):scene.line(x-4,y+dy*lead*f,x+4,y+dy*lead*f)
    if qfp:
        outline(scene,left,top,right,bottom)
        outline(scene,left+4,top+4,right-4,bottom-4,5)
        # Three-digit numbers on the top row reach the corner; tuck the marker into it.
        marker=10 if project.count>=100 else 15
        scene.ellipse(left+marker,top+marker,10,10,'#ffffff','#000000')
    else:
        scene.rect(left,top,bw,bh,'#ffffff','#000000')
        # Terminals sit inside the package edge, with a clipped inner tip.
        for pin,x,y,dx,dy in positions:
            ux,uy=-dy,dx
            points=[(x+ux*u-dx*v,y+uy*u-dy*v) for u,v in [(-7,0),(7,0),(7,21),(3,25),(-3,25),(-7,21)]]
            scene.polygon(points)
    draw_exposed_pad(scene, project, left, top, right, bottom)
    for pin,x,y,dx,dy in positions:
        label=str(pin.number)
        if qfp:
            # Side-row numbers are horizontal: long ones move inward to clear the outline.
            inset=12 if not dx or len(label)<3 else 6+digits_width(label,12)/2
            nx,ny=x-dx*inset,y-dy*12
        else:
            nx,ny=x+dx*13,y+dy*13
        scene.text(nx,ny,label,12,'#000000')
        distance=lead+10 if qfp else 29
        scene.text(x+dx*distance,y+dy*distance,pin.name,16,'#000000',
                   ('end' if dx<0 else 'start') if dx else ('end' if dy>0 else 'start'),True,
                   rotation=0 if dx else 90)
    return scene


def power_diagram(project):
    """Reference-style outlines; tab geometry does not assign electrical pins."""
    pkg=project.package
    is220=pkg=='TO-220'; is247=pkg=='TO-247'; sot=pkg in ('SOT-89','SOT-223')
    leads=3 if pkg=='SOT-223' else project.count
    wide=pkg in ('TO-263','TO-263AB')
    bw=190 if sot else 180 if is247 or wide else 156
    tab=next((p for p in project.pins if p.number==4),None) if pkg=='SOT-223' else None
    width=math.ceil(max(340,text_extent(project.device,22)+24, 240+2*text_extent(tab.name,14) if tab else 340))
    cx=width/2;left=cx-bw/2;right=cx+bw/2
    tab_top=82;body_top=128 if pkg=='SOT-223' else 106 if sot else 174 if is220 else 82 if is247 else 105
    body_bottom=218 if pkg=='SOT-223' else 210 if sot else 310 if is220 or is247 else 258
    lead_end=264 if pkg=='SOT-223' else 256 if sot else body_bottom+72
    # The SOT-223 tab label sits beside the tab; only the bottom leads need room below.
    label_room=max(text_extent(p.name,16) for p in project.pins if p is not tab)+44
    scene=Scene(width,math.ceil(lead_end+label_room+12))
    scene.rect(0,0,scene.width,scene.height,'#ffffff')
    scene.text(cx,22,project.device,22,'#000000',bold=True)
    scene.text(cx,49,pkg if project.count==3 else f'{pkg} · {project.count} pins',14,'#000000')
    if pkg=='SOT-223':
        # Wide rectangular tab and formed leads, matching the top-view reference.
        scene.rect(cx-39,tab_top,78,body_top-tab_top+8,'#ffffff','#000000')
        for y in (tab_top+14,tab_top+28):
            scene.line(cx-39,y,cx+39,y)
    elif sot:
        scene.rounded_rect(cx-34,tab_top,68,body_top-tab_top+12,8)
    else:
        scene.polygon([(left+17,tab_top),(right-17,tab_top),(right-4,tab_top+13),
                       (right-4,body_top+10),(left+4,body_top+10),(left+4,tab_top+13)])
        if is220:scene.ellipse(cx-26,tab_top+18,52,52,'#ffffff','#000000')
    pitch=bw/(leads+0.5)
    for pin in sorted(project.pins,key=lambda p:p.number):
        if pkg=='SOT-223' and pin.number==4:
            scene.text(cx,tab_top-10,'4',12,'#000000')
            scene.text(right+14,tab_top+14,pin.name,14,'#000000','start',True)
            continue
        x=cx+(pin.number-(leads+1)/2)*pitch
        end=body_bottom+18 if pkg in ('TO-252','TO-263AB') and project.count==3 and pin.number==2 else lead_end
        if pkg=='TO-263AB' and project.count==3 and pin.number==2:
            scene.rect(x-9,body_bottom-6,18,end-body_bottom+6,'#ffffff','#000000')
        elif is220 or is247 or wide:
            scene.polygon([(x-9,body_bottom-8),(x+9,body_bottom-8),(x+9,body_bottom+30),
                           (x+5,body_bottom+30),(x+5,end),(x-5,end),
                           (x-5,body_bottom+30),(x-9,body_bottom+30)])
            scene.line(x,body_bottom+4,x,end-6)
        else:
            scene.rect(x-9,body_bottom-6,18,end-body_bottom+6,'#ffffff','#000000')
            if pkg=='SOT-223':
                for y in (body_bottom+15,body_bottom+32):
                    scene.line(x-9,y,x+9,y)
            else:
                scene.line(x-5,body_bottom+3,x-5,end)
            if pkg=='TO-252' and pin.number!=2:scene.line(x-9,end-16,x+9,end-16)
        scene.text(x,end+14,str(pin.number),13,'#000000')
        scene.text(x,end+30,pin.name,16,'#000000','end',True,rotation=90)
    if sot:
        scene.rect(left,body_top,bw,body_bottom-body_top,'#ffffff','#000000')
        scene.rect(left+4,body_top+4,bw-8,body_bottom-body_top-8,'#ffffff','#000000')
    elif is247:
        scene.rect(left,body_top,bw,body_bottom-body_top,'#ffffff','#000000')
        scene.rect(left+5,body_top+5,bw-10,body_bottom-body_top-10,'#ffffff','#000000')
        scene.ellipse(cx-17,body_top+30,34,34,'#ffffff','#000000')
        for edge in (left,right-20):
            scene.rect(edge,body_top+28,20,44,'#ffffff','#000000')
    elif is220:
        scene.rect(left,body_top,bw,body_bottom-body_top,'#ffffff','#000000')
        scene.polygon([(left+4,body_top+4),(right-4,body_top+4),(right-10,body_top+17),(left+10,body_top+17)])
        scene.rect(left+10,body_top+17,bw-20,body_bottom-body_top-21,'#ffffff','#000000')
        # Semi-circular moulding recesses at either side.
        for edge,direction in [(left,1),(right,-1)]:
            pts=[(edge,body_bottom-62)]
            pts += [(edge+direction*15*math.sin(math.pi*i/20),body_bottom-47-15*math.cos(math.pi*i/20)) for i in range(21)]
            scene.polygon(pts)
        scene.ellipse(cx-9,body_bottom-32,18,18,'#ffffff','#000000')
    else:
        scene.polygon([(left+14,body_top),(right-14,body_top),(right,body_top+15),
                       (right,body_bottom),(left,body_bottom),(left,body_top+15)])
        scene.polygon([(left+16,body_top+4),(right-16,body_top+4),(right-4,body_top+17),
                       (right-4,body_bottom-4),(left+4,body_bottom-4),(left+4,body_top+17)])
        if not wide: scene.ellipse(cx-14,body_bottom-56,28,28,'#ffffff','#000000')
        if pkg=='TO-263':
            for edge,direction in [(left,1),(right,-1)]:
                pts=[(edge,body_bottom-62)]
                pts += [(edge+direction*13*math.sin(math.pi*i/20),body_bottom-47-15*math.cos(math.pi*i/20)) for i in range(21)]
                scene.polygon(pts)
    return scene
