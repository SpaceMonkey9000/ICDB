# Changelog

All notable changes to ICDB. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Releases are listed newest
first.

## [0.8.6-beta.1] - Unreleased

First beta of the PySide6 (Qt) application. It replaces the Tk interface and
summarises Qt UI revisions 3 to 29.

### Added

- Qt interface with three tabs: Components, Pinout library and Import.
- One **Save** for all tabs: component edits, new and deleted components, pinout
  definitions, group changes and pinout deletions are staged and written in one
  transaction. **Revert** discards them and **View changes** lists them pin by pin.
- Crash recovery drafts for staged components and pinouts, restored only when the
  database records they touch are unchanged.
- Pinout library with list, editor and live preview: create, edit, duplicate and
  delete pinouts; pin roles as a list; paste pin tables; up to 4096 pins.
- Groups tab to add and remove the components that share a pinout, including
  components that are not saved yet.
- Components tab actions: **Search datasheet**, **Edit pinout**, **Assign pinout**
  and **New pinout**.
- Automatic publishing to ICOCR of new pinouts with devices, after Save.
- Settings → Tools: **Publish pinouts** and **Rebuild all SVGs**, run in the
  background.
- Command-line options `--data`, `--open-part` and `--add-part`, used by ICOCR's
  **Open in ICDB** and **Add to ICDB**.
- `--self-test` in the Qt application, for checking packaged builds.
- Light and Dark graphite themes, dark Windows title bars, and an option to invert
  pinout images in dark mode.

### Changed

- The Components list shows Part number, Function and Pinouts. The manufacturer is
  shown in the details.
- The Import tab imports part-number CSV files only (`part_number,description`).
  Existing parts are skipped and never changed.
- Editing a component cell updates only that row instead of reloading the list.
- Publish re-hashes an unchanged SVG only when its size or date changed.
- Documentation rewritten for the Qt application: README, user guide,
  troubleshooting and developer notes.
- `shared_data.py`, `data_lock.py` and `reference_images.py` are now identical in ICDB
  and ICOCR, checked by `tools/check_shared_files.py` and a shared contract test.
- `icdb_qt.py` split into the `ui/` package (about 2,900 lines down to 300); no change
  in behaviour.

### Fixed

- Group members were listed twice in the Groups tab.
- Saving a new pinout with the same pins as an existing one silently reused the
  existing pinout and lost the new title. It is now refused with the existing
  pinout's number.
- Save always failed when a component in a pinout group was deleted while that
  pinout had unsaved edits.
- A pinout could not be deleted after all its devices had been removed.
- The pinout and component recovery prompts opened inside each other.
- The Import button stayed disabled after a refused or failed import.
- ICDB started with the alias prototype's start-up code: it always used a `DATA` folder
  next to the application folder, refused `--data`, ignored `ICLENS_DATA` and the saved
  setting, and **Settings → Data → Change…** did nothing. It now finds the DATA folder
  as documented, and uses the `ICSuite / ICDB-PySide6` settings.
- Save always failed when an import was staged next to component changes that touch
  the same parts. The import preview now includes the staged component changes. If
  components change after an import is staged, Save previews the import again.
- **Undo deletion** on a pinout left its devices removed, so Save still unassigned them.
- A staged pinout deletion could not be saved while its unfinished pin edits were invalid.
- Pinouts saved from the close dialog, or whose publication failed or was refused, were
  not published until a manual publish. Pending publications are now saved together
  with the changes and finished at the next start.
- Publishing never removed superseded generated SVGs; they are now removed, and
  **Removed** in the publish result counts them.
- The pinout delete button could keep the label of the previously open pinout.
- A first selection in the Pinout library could crash before the window finished
  starting.
- Floating Save and Revert windows appeared on Windows.
- The DATA folder chosen in Settings → Data was saved in the old `IC_Tools` location,
  so ICOCR, which reads the `ICSuite` location first, could keep using another folder.
  Both programs now save and read the same setting.
- An untouched **New pinout** was staged straight away and dropped out of sight
  when another pinout was opened. Save then wrote a hidden "New device" pinout, or
  failed when there were two. A new pinout is now staged only once it is edited or
  given devices, and staged new pinouts are listed (in italics, marked *new,
  unsaved*) until Save. **Delete pinout** reads **Discard new pinout** for them.
- Problems that Save would refuse are now caught when the change is made, rather
  than failing the whole Save:
  - adding a device that already has a pinout in the same package is refused, with
    the conflicting pinout named;
  - changing the package or pin count of a pinout with assigned devices shows a
    warning on the right of the status bar while the Pinout library is open (hover
    for details);
  - deleting a pinout with assigned devices offers to remove them first.
  When Save still fails, the error names the pinout.
- **Keep for later** on recovery drafts did not keep them. The first component edit
  overwrote a kept component draft, and Save, Revert or Discard on exit deleted kept
  drafts. Kept drafts are now set aside and offered again at the next start.
- The two recovery prompts at start-up could be answered differently, which left
  pinout groups pointing at unsaved components that were not restored. There is now
  one prompt for both, components are restored first, and group entries for
  components that could not be restored are removed.
- Opening a pinout with many pins was slow (about 1.3 s for 1024 pins): each pin
  had its own role list widget. The role list now opens only in the cell being edited.
- A new pinout started from Components showed "New device" in the preview instead
  of the part number.
- **Add device** accepted an empty part number and then closed, losing what was
  typed. Duplicate part numbers (same manufacturer) were only refused at Save. Both
  are now checked in the dialog, which stays open, and when a part number is edited
  in the table.
- The manufacturer could not be changed after adding a device. **Edit device** now
  edits part number, function and manufacturer; aliases follow the edited device.
- With no pinout open, the editor fields could be edited but the changes were
  ignored. The editor is now disabled until a pinout is open, and clearing it also
  resets the package and exposed pad fields.
- Disabled controls looked the same as enabled ones.
- The automatic publish after Save was reported as "deferred" when another operation
  was running, but never ran. It now runs when that operation finishes, and
  **Publish to ICOCR** stays visible while saved pinouts are unpublished.
- **View changes** showed an alias's part number as it was when the alias was added,
  not after a later rename.
- Saving one pinout change could keep the window busy on "Publishing pinouts" for
  over a minute on a large database: the automatic publish after Save checked every
  pinout assignment in the database. It now publishes only the pinouts that Save
  changed (and those of renamed devices, whose labels changed), and shows progress
  in the status bar. **Publish pinouts** in Settings → Tools still publishes everything.
- Publishing checked each SVG's location with about eight file-system lookups;
  it now uses one, which matters on Windows and network drives.

### Removed

- The Tk interface and its launcher (`launch.py`, `run_ICDB_windows.bat`).
- The matching review UI and the KiCad, master database, ICPin and pin-table CSV
  importers. ICDB keeps only the part-number CSV import for now.
- Per-revision release notes; they are kept under `archive/notes`.

### Known issues

- No log file.
- Recovery drafts made from source are not found by the installed exe.

## Earlier releases

Releases up to ICDB 0.8.6 (Tk) are in
[archive/CHANGELOG-0.8.6-and-earlier.md](archive/CHANGELOG-0.8.6-and-earlier.md).
