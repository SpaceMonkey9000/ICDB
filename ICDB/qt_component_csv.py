"""Safe preview for ICDB's existing two-column component CSV importer.

No matching, pinout import, or overwrite behaviour is implemented here.
The actual commit is delegated to builder.import_file() to retain source evidence.
"""
import csv
import hashlib
import io
import re
from pathlib import Path
from builder import csv_selection_digest, part_key, function_key

_HEADERS = {'partnumber', 'part'}


def _delimiter(first_line):
    # Mirror builder.import_file's delimiter detection.
    quoted = False
    for char in first_line:
        if char == '"':
            quoted = not quoted
        elif not quoted and char in ',;':
            return char
    return ','


def preview_component_csv(db, path, *, excluded_lines=()):
    """Return {'rows', 'sha256', 'already_imported'}.

    rows: (start line, part, description, status, note). sha256 is passed back to
    builder.import_file so the import refuses a file that changed after the preview.
    """
    path = Path(path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    source_digest = csv_selection_digest(digest, excluded_lines)
    already_imported = db.execute('SELECT 1 FROM sources WHERE sha256 IN (?, ?)',
                                  (digest, source_digest)).fetchone() is not None
    text = raw.decode('utf-8-sig')
    first = next((s for s in text.splitlines() if s.strip()), '')
    reader = csv.reader(io.StringIO(text, newline=''), delimiter=_delimiter(first), strict=True)
    seen = set()
    existing = {}
    for row in db.execute('SELECT part_number,function FROM components'):
        existing.setdefault(part_key(row['part_number']), []).append(row['function'])
    rows = []
    first_record = True
    try:
        while True:
            # Report the line a record starts on, as builder.import_file does.
            line = reader.line_num + 1
            try:
                record = next(reader)
            except StopIteration:
                break
            if not record or len(record) == 1 and not record[0].strip():
                continue
            if len(record) != 2:
                raise ValueError(f'CSV line {line}: expected 2 columns; found {len(record)}')
            part, description = (field.strip() for field in record)
            key = re.sub(r'[ _-]', '', part.casefold())
            if first_record and key in _HEADERS and description.casefold() in ('description', 'function'):
                first_record = False
                continue
            first_record = False
            if not part or not description:
                raise ValueError(f'CSV line {line}: part number and description are required')
            if any(ch in part for ch in '\r\n\x00') or '\x00' in description:
                raise ValueError(f'CSV line {line}: invalid control character')
            if line in excluded_lines:
                continue
            k = part_key(part)
            if k in seen:
                status = 'Duplicate in CSV'
            elif k in existing:
                status = 'Already in ICDB'
            else:
                status = 'New'
            note = ''
            if status == 'Already in ICDB' and not any(function_key(description) == function_key(f) for f in existing[k]):
                note = 'Description differs; existing record will not be changed'
            rows.append((line, part.upper(), description, status, note))
            seen.add(k)
    except csv.Error as exc:
        raise ValueError(f'Invalid CSV near line {reader.line_num}: {exc}') from exc
    if not rows and not excluded_lines:
        raise ValueError('CSV contains no component rows')
    return {'rows': rows, 'sha256': digest, 'already_imported': already_imported}
