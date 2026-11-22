# ICDB PySide6 — Pinout Library layout revision 5

Built from Revision 4; no database schema or backend changes.

## Layout
- Left: searchable pinout library table (Title, Package, Devices); no visible internal ID column. Stable definition IDs remain in Qt UserRole for correct record handling.
- Middle: permanently visible pinout editor tabs: Pins, Groups, Properties.
- Right: zoomable/pannable pinout preview, always visible.
- Three independently adjustable panes, saved using the existing splitter preference.

## Editing
- Removed Edit mode and Edit button.
- New, Save and Revert controls are permanently visible.
- Selecting a different row prompts to discard unsaved pin-definition edits.
- Revert reloads the stored definition. Group changes remain immediate writes under existing backend semantics and cannot be reverted by Revert; use the Groups tab Undo action where supported.
- Settings > Tools remains the entry point for Publish accepted pinouts.

## Validation
- Python syntax compilation and static structure checks passed.
- GUI operation not tested on Windows; PySide6 unavailable in this environment.
- Use a copy of the DATA directory for initial editing tests.
