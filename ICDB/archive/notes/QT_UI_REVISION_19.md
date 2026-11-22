# ICDB Qt UI Revision 19 — bug fixes and performance

## Fixes
- **Groups tab:** each member was listed twice (the member query ran twice). Members are now listed once.
- **New pinouts with existing pin data:** saving a new pinout whose pins, package and exposed pad match an existing one used to return the existing pinout without a warning, so the new title was lost. Saving now refuses with the existing pinout's number. **Save as new** checks this when you click it. Imports still reuse identical definitions. This also applies to the Tk workbench's Save as new.
- **Deleting a group member:** if a component in a pinout group was staged for deletion while that pinout had unsaved edits, Save always failed. Deleted components are now removed from staged group memberships automatically. This matches the database cascade.
- **Recovered sessions:** the pinout and component recovery prompts now run one after the other instead of one opening inside the other. Some pinout drafts reference unsaved components whose own draft was discarded or is missing. Those references are removed and reported. Any that remain are shown in the Groups tab as "(missing unsaved component)", so they can be removed. Unreadable recovery entries are preserved and reported instead of raising an error.
- **Tkinter no longer required for Qt:** `database_version.py` imports Tkinter only when the Tk status label is created. `requirements-qt.txt` now lists PySide6, and `setup_qt_windows.bat` uses it.
- **Import:** the **Import new parts** button is re-enabled if the import is refused (unsaved edits) or fails. A failed preview reports its error.
- **Pin count:** the editor accepts up to 4096 pins, the same as storage. Imported large definitions now show their real count. If lowering the pin count would remove rows containing pin data, ICDB asks first.
- **New pinouts:** an unsaved new pinout stays in the editor when the search or filter changes. After Save, the new pinout is opened.
- **Smaller fixes:** Edit and the details panel handle a component that has disappeared. Revert handles a pinout deleted by another instance.

## Performance
- **Components list:** editing a cell updates only that row instead of rebuilding up to 15,000 rows (about 0.35 s to 0.02 s in testing). Pinout package labels are cached per definition revision instead of read again for every accepted link on each refresh. An empty search skips the per-row Unicode LIKE function.
- **Group picker:** staged edits are matched in Python rather than with one SQLite query per edited or added component.
- **Pinout preview:** the redundant full-size image copies were removed (up to about 144 MB each for large diagrams).
- **Publish:** unchanged SVGs are re-hashed only when their size or modification time changed. The new cache table `pl_file_hashes` is not counted in the content revision.
- **Deleting components:** linked records are deleted in batches rather than with per-row schema lookups.

## Tests
`test_revision19_fixes.py` adds 14 regression tests. The Qt tests run offscreen and are skipped if PySide6 is not installed. The full suite (29 tests) passes without Tkinter.
