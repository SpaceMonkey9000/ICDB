"""Exact and unambiguous component resolution for CLI navigation."""

def resolve_part(db, part):
    part = (part or '').strip()
    if not part:
        raise ValueError('Component part number is empty')
    matches = list(db.execute('''SELECT id, part_number FROM components
                                 WHERE part_number = ? COLLATE NOCASE
                                 ORDER BY id LIMIT 3''', (part,)))
    if not matches:
        raise LookupError(f'Component {part!r} is not in the selected ICDB database')
    if len(matches) > 1:
        raise ValueError(f'Multiple components match {part!r}; select the correct record manually')
    return matches[0][0], matches[0][1]
