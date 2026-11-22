# Revision 15 — Add Devices group picker fix

Revision 14 converted component creation into a staged operation. The Pinout Library Add Devices dialog queried SQLite only, so components added on the Components tab but not yet committed disappeared from the picker. Temporary negative component IDs also could not be used directly in `pl_matches`.

Changes:
- Add Devices now searches both persisted components and staged component additions/edits.
- Staged deletions are excluded from search results.
- New components are marked `New — unsaved` in the dialog.
- Staged members appear in the Groups tab before Save.
- Save maps temporary component IDs to inserted SQLite component IDs before accepting group membership, within the existing transaction.
- Failed group assignment rolls back both component insertion and pinout membership.
- No changes to styling, database file format, recovery journal or SVG publishing.

Tests: test_staged_group_devices.py, test_component_stage.py, test_transactional_edit.py, test_delete_pinout.py, test_draft_recovery.py.
Windows GUI requires validation against a copied DATA folder.
