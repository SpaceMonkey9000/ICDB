# ICDB Qt Revision 13 — Editor controls and crash recovery

Based on Revision 12 transactional pinout editing. No ICDB schema migration.

## Changes

- **Pin role** in the pin table is a `QComboBox` using the six existing `pinout.ROLES` values. This applies to loaded definitions, added rows, pasted rows and recovered drafts.
- **Unsaved pinout changes** appears on the top tab bar whenever the Pinout Library has staged edits.
- **Save** and **Revert** buttons sit beside **Settings** and remain visible on the Components, Pinout Library and Import tabs. They act **only on staged Pinout Library edits**. Component inline editing and CSV import still commit using their existing behavior.
- Save performs the Revision 12 transaction for pinout definitions and accepted groups. Revert discards the draft, including group changes.
- An automatically updated recovery draft is written ~450 ms after edits to an application-specific folder in the user's AppData. The draft is JSON, written atomically using a temporary file and `os.replace`; it does not change `components.sqlite`.
- On next launch, a recovery prompt offers Restore, Discard or Keep for later. Restore recovers the edit fields and group additions/removals **in memory**; Save is still required to commit.
- Recovery refuses to apply a draft if the pinout revision or accepted group memberships differ from the database. In that case it preserves the draft for manual inspection and displays the path.
- Normal exit with unsaved edits offers Save, Keep Draft, Discard or Cancel. Save requires successful transaction completion; Keep Draft requires a successful journal write.

## Limitations / safety

- Drafts capture committed widget values, not text still being typed inside an uncommitted table-cell editor. A crash before the ~450 ms timer fires can lose the most recent edit.
- Only Pinout Library edits have crash recovery. Component table and import are outside this draft system.
- Save/Revert do not publish SVGs. Publication remains a separate operation because it changes external files as well as SQLite records.
- The application has not been launched on Windows in this execution environment; Qt GUI behaviour needs live testing.
- Keep-for-later and conflicted drafts are protected from initial selection changes; when a new draft is saved, an older protected draft is renamed with a `.preserved-<timestamp>.json` suffix. Review any preserved drafts manually.

## Tests

- `python test_transactional_edit.py`
- `python test_delete_pinout.py`
- `python test_draft_recovery.py`
- `python -m compileall -q icdb_qt.py qt_draft_store.py`
