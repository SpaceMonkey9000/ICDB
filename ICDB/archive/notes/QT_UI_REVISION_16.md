# Revision 16 — Multi-pinout editing sessions and change review

- Switching between pinouts stores the current editor state in an in-memory per-definition draft; no discard prompt.
- New pinouts can be staged alongside existing pinout changes. **Save as new** now stages a copy, rather than writing immediately.
- The top Save button validates and applies all staged component changes, pinout definitions and group memberships under one SQLite BEGIN IMMEDIATE / COMMIT. Database exceptions trigger ROLLBACK.
- Added **View changes** beside Save, and as an action in both the Save confirmation and close-window confirmation. Shows per-component changes, pinout properties, pin diffs, exposed-pad changes and accepted-device group changes.
- Recovery journal now stores multiple pinout drafts in one atomic JSON file, keyed to the underlying database path. Legacy single-pinout journals remain readable. Restoration verifies database revision and group membership for each draft; if any conflict exists the session is preserved and not automatically restored.
- Existing component draft remains in its own journal. Close offers Save / View changes / Keep Draft / Discard / Cancel.
- Fixed group member list to display persisted members as well as staged new members.
- Other externally-written operations (CSV import, SVG publishing, and deleting unused pinout definitions) are still separate; a database migration to stage deletion was not part of this revision.

## Validation

Headless database tests: transactional, component-stage, group-staging, deletion, draft-recovery and multi-pinout rollback/session persistence all pass. Python compilation and ZIP verification pass. PySide6 is unavailable in the build environment; Windows GUI and interactive workflow need testing against a copied DATA directory.
