# Revision 26 — Delete pinout after unassigning

## Cause
Removing a component from a pinout group changes its `pl_matches` record from `Accepted` to `Rejected`. The previous delete guard counted every match, including rejected matches, and incorrectly blocked deletion after unassignment.

## Correction
- A saved definition can be deleted when there are **no Accepted matches** and **no imported source references**.
- Remaining Suggested and Rejected matches are detached during the same SQLite transaction.
- Published component links belonging exclusively to those detached matches are removed. Existing SVG asset files are retained (content-addressed assets can be shared).
- Shared or reassigned publication links abort deletion instead of silently removing unrelated data.
- Accepted device associations and imported source references still block deletion.
- Confirmation dialog explains the deletion scope.

## Note
Click global Save after removing device group members. An unsaved group edit is not a database unassignment.

## Validation
26 passed; 17 Qt tests skipped. Python compile and ZIP integrity passed. Windows GUI untested.
