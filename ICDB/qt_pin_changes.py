"""Concise, dependency-free pinout change review formatting."""

PIN_FIELDS = ('name', 'role', 'description')


def _pin_number(pin):
    return str(pin.get('number', '')).strip()


def _index_pins(pins):
    """Index by pin number, retaining duplicate numbers deterministically."""
    counts = {}
    order = []
    indexed = {}
    for pin in pins:
        number = _pin_number(pin)
        occurrence = counts.get(number, 0)
        counts[number] = occurrence + 1
        key = (number, occurrence)
        order.append(key)
        indexed[key] = pin
    return order, indexed


def summarize_pin_changes(before, after):
    """Return a compact list of changed pins; omit unchanged entries.

    Both sequences contain dicts with number/name/role/description. The new
    editor's draft representation (list of 4-item rows) is accepted too.
    """
    def as_dict(p):
        if isinstance(p, dict):
            return p
        return dict(zip(('number', 'name', 'role', 'description'), p))

    old = [as_dict(p) for p in before]
    new = [as_dict(p) for p in after]
    old_order, old_map = _index_pins(old)
    new_order, new_map = _index_pins(new)
    changes = []
    for key in old_order:
        number, occurrence = key
        label = f'Pin {number}' + (f' (entry {occurrence + 1})' if occurrence else '')
        if key not in new_map:
            changes.append(f'{label}: removed ({old_map[key].get("name", "")})')
            continue
        old_pin, new_pin = old_map[key], new_map[key]
        fields = []
        for field in PIN_FIELDS:
            before_value = str(old_pin.get(field, '') or '')
            after_value = str(new_pin.get(field, '') or '')
            if before_value != after_value:
                fields.append(f'{field}: {before_value!r} -> {after_value!r}')
        if fields:
            changes.append(f'{label}: ' + '; '.join(fields))
    for key in new_order:
        if key not in old_map:
            number, occurrence = key
            label = f'Pin {number}' + (f' (entry {occurrence + 1})' if occurrence else '')
            changes.append(f'{label}: added ({new_map[key].get("name", "")})')
    if not changes and len(old_order) == len(new_order) and old_order != new_order:
        changes.append('Pin order changed')
    elif changes and old_order != new_order and set(old_order) == set(new_order):
        changes.append('Pin order changed')
    if not changes:
        return []
    unchanged = sum(1 for key in old_order if key in new_map and
                    all(str(old_map[key].get(f, '') or '') == str(new_map[key].get(f, '') or '')
                        for f in PIN_FIELDS))
    return [f'Pins: {len(changes)} change(s), {unchanged} unchanged'] + changes
