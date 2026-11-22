# ICDB PySide6 — Revision 14 (Unified Draft Editing)

Based on the Revision 13 Floating Buttons Hotfix.

## UI

- Pin role comboboxes use the editable-combo appearance of the Package picker while preventing free typing; each is inset within its table cell. Pad role matches.
- All comboboxes ignore mouse-wheel events to avoid accidental selection changes when scrolling.
- **Unsaved changes** is bold and dynamically centered over the main tab line, independent of the right-hand Save/Revert/Settings buttons.

## Transactional components

- Components tab inline metadata edits, Add device and Delete device are now staged instead of immediately writing to SQLite.
- Main-window Save writes component edits/additions/deletions and any staged pinout edits/group assignments within one SQLite write transaction.
- Revert discards both staged areas with confirmation.
- Component draft file automatically autosaves separately from the pinout draft and can be recovered after a crash; restoration checks the database snapshot of edited/deleted records.
- Component additions receive temporary negative UI-only IDs until Save.
- Existing source evidence and pinout links are preserved on metadata edits; component deletions remove their linked records only when Save commits.
- Bulk CSV imports and SVG rebuilding/publication are independent operations and are blocked while unsaved changes exist.

## Limitations

- Components and pinouts are each edited in their own UI; save operates on the currently staged pinout plus all staged component records.
- There is no Undo stack for individual staged component changes; Revert discards all pending edits.
- Crash recovery is timed (~450ms); very recent keystrokes can be lost if the process stops before the timer fires.
- The GUI has not been exercised in Windows; headless backend and transaction tests passed.
