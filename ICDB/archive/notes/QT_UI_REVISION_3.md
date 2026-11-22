# ICDB PySide6 — UI revision 3

Based on `ICDB_0.8.6_PySide6_UI_Revision.zip` and the original ICDB backend.

## Changes

- **Settings > Appearance:** An independent, saved **Invert pinout images in dark mode** checkbox. Both Components and Pinout Library viewers follow the choice. Source SVG and raster images are not modified.
- **Pinout background:** The surrounding viewer background is taken from the rendered image's top-left pixel, so an inverted white-background diagram has a black surround and an uninverted diagram has a white surround.
- **Components:** A vertical splitter between the selected component's pinout and source evidence allows resizing either area. Part number, function and manufacturer can be edited directly by double-clicking the table cell or pressing an edit key. Changes are written using the original `builder.update_device()` validation. The Pinouts column is read-only. All four columns use user-resizable `Interactive` header sections, including Manufacturer.
- **Pinout Library:** Selection opens a zoomable SVG diagram. The pin table, diagram and accepted group member list are separated by a vertical splitter. Tables have adjustable columns.
- **Create pinout:** New Pinout, title, package, pin count, source, editable pin table, optional exposed pad, add/remove rows, paste tab-separated pin rows, preview, save, and save as new.
- **Groups:** List accepted devices for the selected definition; search available devices and add selected ones; remove selected group memberships; undo latest group edit. These use existing transactional `Library.add_group_members`, `remove_group_members`, and `undo` methods.
- **Publish:** Explicit, confirmed Publish accepted pinouts action calls the original `Library.publish()` to update references consumed by ICOCR. This is not the Matching or Import interface.

## Data safety

The app edits the existing shared database. Accepted group additions can fail if pinout geometry or other links conflict; failure is transactional. `Publish accepted pinouts` can replace or remove published reference links, and should only be used after confirming the desired group membership. Work from a backed-up copy of the DATA directory until the Qt UI has been validated on Windows.

## Validation

- Python compilation succeeded.
- Backend smoke tests exercised component modification, new SOIC definition creation, accepted group additions/removals, undo, and SVG publication against a temporary SQLite database.
- PySide6 GUI is not available in this build environment; interactive Windows behaviour has not been runtime-tested.
- Matching and Import sections remain omitted.
