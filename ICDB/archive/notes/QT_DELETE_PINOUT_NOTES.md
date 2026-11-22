# ICDB Qt — Delete pinout

- Added **Delete pinout** to the Pinout Library toolbar.
- Confirmation identifies the title and package. **No** is the default.
- Deletion is transactional. An unused pinout definition is removed from `pl_definitions`.
- Definitions referenced by any `pl_matches` status (Accepted, Suggested, Rejected) or by `pl_sources` are blocked. Existing published ICOCR pinout links are not silently deleted.
- Unsaved editor changes require a separate discard confirmation.
- After deletion, the pinout library and Components table are refreshed.
- No database schema changes.

## Verification

- Python compilation passed.
- Temporary SQLite tests passed: successful unused deletion, refusal for associated device, refusal for imported source.
- Windows GUI integration has not been tested in this environment.
