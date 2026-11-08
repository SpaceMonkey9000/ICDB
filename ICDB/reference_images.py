"""Static SVG and raster reference loading shared by ICDB and ICOCR."""
import io
import math
import sys
import re
from pathlib import Path
import xml.etree.ElementTree as ET
from PIL import Image

MAX_PIXELS = 24_000_000

def _svg(path):
    data = Path(path).read_bytes()
    if len(data) > 8_000_000:
        raise ValueError('SVG must be smaller than 8 MB')
    # Decode first so UTF-16 cannot bypass declaration checks.
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        text = data.decode('utf-16')
    else:
        text = data.decode('utf-8-sig')
    if re.search(r'<!\s*(DOCTYPE|ENTITY)', text, re.I):
        raise ValueError('SVG declarations and entities are not supported')
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError('Invalid SVG: '+str(exc)) from exc
    if root.tag != '{http://www.w3.org/2000/svg}svg' and root.tag != 'svg':
        raise ValueError('Expected an SVG document')
    for node in root.iter():
        tag = node.tag.split('}')[-1]
        if tag in {'script','foreignObject','image','style','animate','animateTransform','set'}:
            raise ValueError('Use a static SVG with embedded styles and no external resources')
        for key, value in node.attrib.items():
            name = key.split('}')[-1].lower()
            if name.startswith('on') or name == 'base' or (name in {'href','src'} and not value.startswith('#')):
                raise ValueError('SVG external resources and event handlers are not supported')
            if '\\' in value or '@' in value:
                raise ValueError('SVG escaped styles and imports are not supported')
            for target in re.findall(r'url\s*\((.*?)\)', value, re.I):
                if not target.strip(' \"\'').startswith('#'):
                    raise ValueError('SVG external resources are not supported')
    def length(value):
        m = re.fullmatch(r'\s*([0-9]+(?:\.[0-9]*)?|\.[0-9]+)(px|mm|cm|in|pt|pc)?\s*', value or '')
        return float(m[1])*{'px':1,'mm':96/25.4,'cm':96/2.54,'in':96,'pt':96/72,'pc':16,None:1}[m[2]] if m else None
    width, height = length(root.get('width')), length(root.get('height'))
    if not width or not height:
        try:
            box = [float(v) for v in re.split(r'[ ,]+', root.get('viewBox','').strip())]
            if len(box) != 4: raise ValueError()
            width, height = box[2:]
        except ValueError as exc:
            raise ValueError('SVG needs width/height or a valid viewBox') from exc
    if not all(math.isfinite(v) and v > 0 for v in (width,height)):
        raise ValueError('Invalid SVG dimensions')
    return text, width, height

def load_reference_image(path, max_size=(2400,2400)):
    path = Path(path)
    if path.suffix.lower() == '.svg':
        text, width, height = _svg(path)
        try:
            import resvg_py
        except ImportError as exc:
            raise ValueError('SVG support needs resvg_py; install the release requirements') from exc
        scale = min(max_size[0]/width, max_size[1]/height)
        size = (max(1,round(width*scale)), max(1,round(height*scale)))
        if size[0]*size[1] > MAX_PIXELS:
            raise ValueError('Requested SVG preview is too large')
        try:
            png = resvg_py.svg_to_bytes(svg_string=text, width=size[0], height=size[1], background='white',
                sans_serif_family=('Arial' if sys.platform == 'win32' else 'Helvetica' if sys.platform == 'darwin' else 'DejaVu Sans'))
        except Exception as exc:
            raise ValueError('Cannot render SVG: '+str(exc)) from exc
        with Image.open(io.BytesIO(png)) as im:
            return im.convert('RGB')
    with Image.open(path) as im:
        if im.format not in {'JPEG','PNG','BMP','WEBP'} or im.width*im.height > MAX_PIXELS:
            raise ValueError('Use JPG, PNG, BMP or WebP images under 24 megapixels, or SVG')
        return im.convert('RGB')

def reference_suffix(path):
    if Path(path).suffix.lower() == '.svg':
        load_reference_image(path, (512,512))
        return '.svg'
    with Image.open(path) as im:
        if im.format not in {'JPEG','PNG','BMP','WEBP'} or im.width*im.height > MAX_PIXELS:
            raise ValueError('Use JPG, PNG, BMP or WebP images under 24 megapixels, or SVG')
        suffix = {'JPEG':'.jpg','PNG':'.png','BMP':'.bmp','WEBP':'.webp'}[im.format]
        im.verify()
        return suffix
