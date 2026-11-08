"""Shared heading sorting, including numeric and natural part-number order."""
import re


from decimal import Decimal

PLAIN_NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)')


def sort_key(value):
    """Natural order: 74HC00 < 74hc01 < 74HC02 < 74HCT00; a cell that is just a decimal
    number (1.10, 1.25, 1.5, -2) sorts by value. Only ASCII digits are numeric, so
    superscripts such as '²' stay text. None sorts as empty text."""
    text = '' if value is None else str(value)
    plain = text.strip()
    if PLAIN_NUMBER.fullmatch(plain):
        # Same shape as a natural key for a bare integer, so mixed columns still compare.
        return ((0, ''), (1, Decimal(plain)), (0, ''))
    return tuple((1, int(chunk)) if chunk.isdecimal() else (0, chunk.casefold())
                 for chunk in re.split(r'([0-9]+)', text))


def enable_sorting(tree):
    tree._sort_column = None
    tree._sort_reverse = False
    tree._sort_titles = {c: tree.heading(c, 'text') for c in tree['columns']}
    for column in tree['columns']:
        tree.heading(column, command=lambda c=column: sort_table(tree, c))


def sort_table(tree, column=None):
    if column is not None:
        tree._sort_reverse = not tree._sort_reverse if tree._sort_column == column else False
        tree._sort_column = column
    if tree._sort_column is None:
        return
    column = tree._sort_column
    rows = sorted(tree.get_children(), key=lambda iid: sort_key(tree.set(iid, column)),
                  reverse=tree._sort_reverse)
    for index, iid in enumerate(rows):
        tree.move(iid, '', index)
    for name, title in tree._sort_titles.items():
        tree.heading(name, text=title + ((' ▼' if tree._sort_reverse else ' ▲') if name == column else ''))
