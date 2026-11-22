# ICDB PySide6 Revision 12 — Transactional pinout editing

Built from `ICDB_0.8.6_PySide6_Revision11_Delete_Pinout.zip`.

## Changes

- Pinout editor values (properties and pins) remain drafts until **Save**.
- **Groups → Add devices / Remove** now stages accepted membership changes in memory. The group list immediately shows the staged result, but SQLite is unchanged.
- **Save** commits pinout definitions and accepted group membership deltas inside one SQLite `BEGIN IMMEDIATE` transaction. Group rejections are applied before validating the resulting pinout; additions are checked by existing acceptance validation.
- Any error rolls back definition, membership, approvals, and operation-log changes.
- **Revert**, changing selected pinout (after confirmation), and quitting (after confirmation) discard the current draft.
- **Undo draft** reverses the last staged group change, not a previously committed database operation.
- Revision and accepted-membership snapshots prevent overwriting an externally changed definition or accepted group.
- Saving a *new* pinout must precede adding devices; Save as new does not carry over an existing group's staged edits.

## Boundaries

- The transactional workflow covers **Pinout Library editor and accepted group membership**. The Components table's existing inline edit actions and CSV imports have not been converted to a shared application-wide draft.
- **Publish / Rebuild SVG** remains separate. The publication backend coordinates immutable file revisions and a database commit, but no single SQLite transaction can atomically encompass arbitrary external filesystem operations.
- Existing import/export logic and database schema are unchanged.
- Existing write lock and backend validation are reused.

## Testing

Run from the extracted project folder:

```
python test_transactional_edit.py
python test_delete_pinout.py
```

The headless transactional tests cover successful combined saves, changed membership, invalid component IDs, invalid pin data, conflicting accepted pinouts, changed database revisions and changed membership snapshots. Python compilation passed. Windows PySide6 UI interaction was **not** runtime tested in this environment.

Test against a copy of the ICDB DATA folder before adopting for production.
