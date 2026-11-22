# Revision 20 — ICOCR integration and component pinout navigation

- Main Components toolbar no longer includes Search datasheet.
- Under Source evidence: Search datasheet and Edit pinout.
- The Edit pinout button is available for accepted library definitions, opening
  the exact definition ID in the Pinout Library and preserving drafts.
- Legacy image-only pinout links are not library definitions; Edit pinout stays
  disabled for these selections.
- `--add-part PART` stages a new component using the existing component draft
  editor after startup/recovery. An existing part opens without creating a duplicate.
- Add does not write to SQLite until global Save is clicked. No DATA schema changes.
- `--open-part PART` from Revision 19 continues to work.
- A running-instance IPC handler is not implemented in this revision.
