# ICDB Qt Revision 22 — Add pinout

Built from Revision 21. Existing database and ICOCR source unchanged.

## Components → Add pinout

- Renames **Assign pinout** to **Add pinout** beneath Source Evidence.
- Clicking **Add pinout** opens the Pinout Library immediately in new-definition mode with the selected component's part number as title and that component staged in its group.
- **Use existing definition** appears as a secondary button above the new pinout editor when started from a component. It opens the existing searchable definition picker, replaces the provisional new draft and stages the component association.
- No initial choice dialog or intermediate database save.
- Both saved and staged-new components are supported.
- New definitions can have group members before Save, including through the Groups tab.
- Combined Save creates the definition and assigns members in one SQLite transaction; rollback removes both on failure.
- Draft recovery records the source component for the secondary existing-definition action.
- Existing library pinout edits, revision-21 assignment helper, and other workflows retained.

## Scope and validation

Backend: 25 passed, 15 Qt tests skipped (PySide6 unavailable). Python compilation and ZIP integrity passed. Windows GUI appearance and interactions remain untested. Use a copied DATA directory for initial evaluation.
