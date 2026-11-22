# ICDB developer notes

## Code layout

| Module | Purpose |
| --- | --- |
| `icdb_qt.py` | Entry point, `MainWindow` (tabs, settings, theme, close handling), `--self-test` |
| `ui/common.py` | SVG and image rendering, palettes, dark title bars, `APP_ROOT` |
| `ui/components_page.py` | Components tab |
| `ui/pinout_library/page.py` | Pinout library tab: layout, list and preview |
| `ui/pinout_library/pin_editor.py`, `drafts.py`, `groups.py`, `actions.py` | Pin table editing, staged drafts, the Groups panel and new/delete/save/publish |
| `ui/import_page.py` | Import tab |
| `ui/session.py` | Staged session for the whole window: Save, Revert, View changes, recovery |
| `ui/icocr_handoff.py` | `--open-part`, `--add-part` and navigation between tabs |
| `ui/job_runner.py`, `ui/jobs.py` | Background database jobs |
| `ui/dialogs.py`, `ui/settings_dialog.py`, `ui/pinout_view.py` | Dialogs and the diagram view |
| `qt_component_draft.py` | Staged component edits, additions and deletions |
| `qt_draft_store.py` | Atomic JSON recovery drafts per database |
| `qt_pin_changes.py` | Text for **View changes** |
| `qt_component_csv.py` | Preview for the part-number CSV import |
| `qt_open_component.py` | Exact part lookup for `--open-part` / `--add-part` |
| `builder.py` | Database connection, schema, component CRUD and CSV import |
| `pin_library.py` | Pinout definitions, groups, transactions and publishing |
| `pinout.py` | Pin table parsing, validation and SVG diagram rendering |
| `pinouts.py` | Published asset and link tables read by ICOCR |
| `pinout_matcher.py`, `rule_api.py` | Match decision schema and rule loading; the matching scan itself is not exposed in the Qt app |
| `library_queries.py` | Light row queries for the lists |
| `icpin_bundle.py` | ICPin identifiers and helpers used by the library |
| `database_version.py` | Database version table and triggers |
| `reference_images.py` | SVG and raster loading, shared with ICOCR |
| `shared_data.py`, `data_lock.py` | DATA location and folder lock, shared with ICOCR |
| `version.py` | `APP_VERSION`, the only place the application version is set |

## Running from source and tests

```bat
setup_qt_windows.bat
.venv-qt\Scripts\python -m pip install -r requirements-dev.txt
.venv-qt\Scripts\python -m pytest tests
```

Qt tests run offscreen and are skipped if PySide6 is missing; run the suite with
PySide6 installed before a release. `tests/conftest.py` puts the application folder
on the import path. `tests/test_revision19_fixes.py` also checks that the backend
imports without Tkinter.

`python icdb_qt.py --self-test --report report.json` opens the main window against a
temporary DATA folder and temporary settings, then exits 0 on success. The build uses
it to check a packaged exe.

`python tools/release_manifest.py` rewrites `RELEASE_MANIFEST.json` and
`SHA256SUMS.txt` from the files that ship (everything except `tests/`, `tools/`,
`archive/` and hidden folders).

## DATA contract with ICOCR

ICDB and ICOCR are separate programs that share one DATA folder. Both must agree on:

- **Location:** `shared_data.data_directory()`: `ICLENS_DATA`, then
  `%LOCALAPPDATA%\ICSuite\data_location.json`, then the older
  `%LOCALAPPDATA%\IC_Tools\data_location.json` (read only), then the default. Both
  applications save to the `ICSuite` file with `shared_data.save_directory()`.
- **Lock:** `data_lock.DataLease`. Both apps take a shared lock on
  `DATA\.icsuite.lock`; a DATA updater takes it exclusively.
- **Database:** `DATA\db\components.sqlite`, or `DATA\components.sqlite` in older
  layouts. ICOCR reads `components`, `entries`, `sources`, `pinout_assets` and
  `pinout_links`.
- **Published diagrams:** `DATA\pinouts\generated\<sha256>.svg`, referenced from
  `pinout_assets.path` as a path relative to DATA. Files are content-addressed and
  never overwritten; older revisions stay on disk.

### Shared files

These files are shared and must be byte-identical in ICDB and ICOCR:

| File | Contents |
| --- | --- |
| `shared_data.py` | Finding and saving the DATA folder, and the database path |
| `data_lock.py` | The lock on the DATA folder |
| `reference_images.py` | Loading SVG and raster pinouts |
| `tools/check_shared_files.py` | Compares the shared files with the other application |
| `tests/test_shared_data.py` | Tests of DATA folder resolution |
| `tests/test_data_contract.py` | ICDB publishes into a temporary DATA folder; ICOCR reads it back |

Change a shared file in one application, then copy it to the other.
`python tools/check_shared_files.py` (with the other application next to this one,
or its folder as an argument) fails if any copy differs. The two shared tests do the
same check, and run the contract test, when the other application is next to this
one; otherwise they are skipped.

## Database version

`database_version.install()` creates `icdb_database_version` (base, revision) and
triggers on the content tables that add one to `revision` for every inserted,
changed or deleted row. A rolled-back transaction rolls back its increments, and
updates that change nothing do not count. The base comes from the DATA builder's
stamp, or from the installer's `data-pack-installed.json`, else it is `Unversioned`.
Caches and settings tables (for example `pl_file_hashes`) are not counted.

## Design decisions

- **One Save for everything.** Component edits, pinout definitions, group changes and
  pinout deletions are staged in memory and written by one `BEGIN IMMEDIATE`
  transaction. A failure rolls back all of it. Revision and group-membership snapshots
  stop a Save from overwriting changes made by another instance.
- **Recovery drafts are not the database.** They are JSON files written atomically
  about 450 ms after an edit. A draft is restored only if the records it touches are
  unchanged.
- **Publishing is separate from Save,** because it writes files as well as database
  rows. New SVGs are written first; the link changes are committed after. A failed
  render leaves the previous links in place. After Save succeeds, the pinouts that Save
  changed are published automatically: saved pinouts with devices and the pinouts of
  renamed devices (`Library.publish(definition_ids=...)`). A JSON import publishes
  everything. Settings → Tools publishes the whole catalogue.
- **The renderer version is part of the asset identity.** Bump `pinout.VERSION` when
  diagrams change so Publish regenerates them.
- **Identical pin data is refused** for a new pinout, with the existing pinout's
  number, so a title is never silently lost.
- **The Qt app only imports part-number CSVs.** The matching UI and the KiCad, master
  database and ICPin importers were removed in Phase 1. They are in git history and
  in the Phase 1 archive.

## Things to fix later

- Set the Qt application and organisation name, so recovery drafts and settings have
  the same location from source and from the exe.
- Add a log file and an unhandled-error dialog.
- `ComponentsPage.edit()` and the edit form of `DeviceDialog` are no longer reachable
  from the UI.
- Phase 3 moved code without changing it. Large classes are split into mixins
  (`SessionMixin`, `PinoutGroupsMixin` and so on) that share the window's attributes.
  Turning them into separate controller objects with their own state is a later step.
- `pinout_matcher.scan()` and the rule loader in `rule_api.py` are unused by the Qt
  app; keep the schema parts.
