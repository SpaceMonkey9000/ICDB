# ICDB PySide6 — Components and Pinout Library (initial migration)

Based on the supplied ICDB 0.8.6 source. **Matching and Import are deliberately excluded** from the new Qt interface.

## Start on Windows

1. Extract this complete archive to its own folder.
2. Run `setup_qt_windows.bat` (Python 3.11 x64 required).
3. Run `run_qt_windows.bat`.

The Qt launcher opens `icdb_qt.py`, not the original Tkinter `launch.py`. The original source and launcher are retained for reference; they are not part of the Qt interface.

ICDB uses the same DATA location configuration as the existing application. By default, source builds look for `DATA` adjacent to the ICDB directory. The database must already exist at `DATA/components.sqlite` or `DATA/db/components.sqlite`. A missing database produces an error instead of silently creating a new empty catalogue.

A DATA folder can be specified for a single launch:

`run_qt_windows.bat --data "D:\ICSuite\DATA"`

Settings → Data can save a different shared DATA location. Restart ICDB and ICOCR to apply; existing files are not moved.

## Implemented

### Components
- Search part number, manufacturer and function.
- Sortable table of catalogue records and linked pinout summaries.
- Add/edit/delete devices using existing `builder` functions.
- View source evidence and linked pinouts.
- Switch between linked image references and accepted native pinout definitions.
- Pan and wheel-zoom pinout viewer; double-click to fit.
- Datasheet web search.

### Pinout library
- Search/filter native pinout definitions.
- View title, package, accepted-device count and pin table.
- Edit pin metadata and existing pin rows.
- Preview the diagram, save in place, or save as a new definition, using the existing `Library.save()` validation and transactions.
- Zoom and pan in the diagram preview.

## Deliberately deferred
- Matching UI and review decisions, match suggestions, publishing.
- Import UI and all source-import workflows.
- Creation of brand-new pinout definitions from a blank form.
- Accepted-member management and group membership changes.
- Image-reference manager, image attachment and link editing.
- Bulk editing, duplicate merges, undo, long-operation progress, database exports.

**Important:** Editing an accepted native pinout definition does not publish updated SVG references to ICOCR. The existing separate publication process remains necessary. No matching or import workflow is invoked by the Qt interface.

## Data safety

This build uses the original `builder.connect`, `Pinouts`, and `Library` initializers and existing database schema. These can perform the same schema setup / migration as original ICDB, including backups for certain migrations. They are not strictly read-only. Test against a backup copy of the shared DATA folder until the migration is validated.

## Validation

- Python source syntax compilation passed.
- Headless backend CRUD/schema and pinout-definition search smoke test passed against a temporary database.
- The GUI itself has **not** been run on Windows or tested with a populated ICDB database. PySide6 is not installed in the build environment.

## Qt UI revision — November 18, 2026

- Hidden row-number headers in the Components table, Pinout library table, and editable pins table.
- Components page now has a horizontal table/details layout. The right side contains selected device identity, pinout/reference selection, zoomable pinout preview, and source evidence.
- Removed the File and View menus; Settings is a button in the upper-right of the main tab bar.
- Settings is a tabbed dialog: Appearance (Light / Dark graphite) and Data (shared DATA directory).
- Changing the appearance takes effect immediately and persists via Qt QSettings for this ICDB Qt application.
- Pinout images, including SVG diagrams and raster references, invert their displayed RGB colours in dark mode. Source image files remain unchanged. The viewer background follows the theme.
- Matching and Import remain excluded.

Note: inversion of multicolour images can produce unnatural colours; the current implementation intentionally applies the same full RGB inversion to both reference formats. Windows GUI validation is still outstanding.

## Qt UI revision 3

See `QT_UI_REVISION_3.md` for inline device editing, resizable pinout and evidence panes, independently configurable pinout inversion, native pinout creation, accepted-group management and explicit publication. Matching and Import remain excluded.

## Revision 13

See `QT_UI_REVISION_13.md` for the pin-role dropdown, global Pinout Library Save/Revert, tab-bar unsaved indicator, and crash-recovery drafts.
