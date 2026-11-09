"""One DATA location, shared by ICDB and ICOCR. No directory writes on import."""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path


def location_file(environ=None):
    env=os.environ if environ is None else environ
    base=env.get('LOCALAPPDATA') or env.get('XDG_CONFIG_HOME') or str(Path.home()/'.config')
    return Path(base)/'IC_Tools'/'data_location.json'


def data_directory(app_root, environ=None):
    env=os.environ if environ is None else environ
    if env.get('ICLENS_DATA'):
        return Path(env['ICLENS_DATA']).expanduser().resolve()
    settings=location_file(env)
    if settings.exists():
        try:
            # Notepad and PowerShell 5 write a UTF-8 BOM.
            value=json.loads(settings.read_text('utf-8-sig'))
        except ValueError as exc:
            raise ValueError(f'DATA folder setting file is unreadable: {settings}\n{exc}\n'
                             'Fix or delete this file, then restart (or choose the DATA folder again).') from exc
        value=value.get('data_folder') if isinstance(value,dict) else None
        if not isinstance(value,str) or not value.strip():
            raise ValueError('Invalid DATA folder setting: '+str(settings))
        return Path(value).expanduser().resolve()
    if getattr(sys, 'frozen', False):
        base = env.get('LOCALAPPDATA') or env.get('XDG_CONFIG_HOME') or str(Path.home()/'.config')
        return (Path(base)/'ICSuite'/'DATA').resolve()
    return (Path(app_root).resolve().parent/'DATA').resolve()


def database_file(data):
    data = Path(data)
    # Preserve legacy root layout when present; otherwise use DATA/db.
    legacy = data/'components.sqlite'
    return legacy if legacy.is_file() else data/'db'/'components.sqlite'


def save_directory(folder, environ=None):
    folder=Path(folder).expanduser().resolve()
    folder.mkdir(parents=True,exist_ok=True)
    for name in ('models','pinouts'):(folder/name).mkdir(exist_ok=True)
    settings=location_file(environ);settings.parent.mkdir(parents=True,exist_ok=True)
    temp=settings.with_suffix('.tmp')
    with temp.open('w',encoding='utf-8') as handle:
        handle.write(json.dumps({'data_folder':str(folder)},indent=2));handle.flush();os.fsync(handle.fileno())
    temp.replace(settings)
    return folder


def choose_directory(parent, current):
    from tkinter import filedialog,messagebox
    folder=filedialog.askdirectory(parent=parent,title='Choose shared DATA folder',initialdir=str(current))
    if not folder:return
    try:
        selected=save_directory(folder)
    except Exception as exc:
        messagebox.showerror('DATA folder',str(exc),parent=parent);return
    messagebox.showinfo('DATA folder saved',f'Both programs will use:\n{selected}\n\nRestart ICDB and ICOCR to apply. This does not move existing files.',parent=parent)


def install_model(source, data):
    """Import ONNX plus its optional JSON sidecar without overwriting another model."""
    source=Path(source).resolve();folder=Path(data).resolve()/'models'
    if source.suffix.lower()!='.onnx' or not source.is_file():raise ValueError('Choose an ONNX model')
    folder.mkdir(parents=True,exist_ok=True)
    if source.is_relative_to(folder):return source
    files=[source]+([source.with_suffix('.json')] if source.with_suffix('.json').exists() else [])
    # A leftover sidecar would silently change how the new model is interpreted.
    if len(files)==1 and (folder/source.with_suffix('.json').name).exists():
        raise ValueError('A JSON sidecar already exists for this filename. Rename the model before importing.')
    for path in files:
        target=folder/path.name
        if target.exists() and hashlib.sha256(target.read_bytes()).digest()!=hashlib.sha256(path.read_bytes()).digest():
            raise ValueError('A different model/sidecar already exists: '+target.name+'. Rename the incoming files first.')
    for path in files:
        target=folder/path.name
        if not target.exists():
            temp=target.with_suffix(target.suffix+'.tmp');shutil.copy2(path,temp);temp.replace(target)
    return folder/source.name


def ocr_model_paths(data):
    """Seed stock OCR weights once, then run from DATA/models/ocr."""
    import rapidocr_onnxruntime
    import yaml
    package=Path(rapidocr_onnxruntime.__file__).parent
    config=yaml.safe_load((package/'config.yaml').read_text('utf-8'))
    folder=Path(data)/'models'/'ocr';folder.mkdir(parents=True,exist_ok=True)
    result={}
    for section in ('Det','Cls','Rec'):
        source=package/config[section]['model_path']
        target=folder/source.name
        if not target.exists():
            temporary=target.with_suffix('.tmp');shutil.copy2(source,temporary);temporary.replace(target)
        result[section.lower()+'_model_path']=str(target.resolve())
    return result
