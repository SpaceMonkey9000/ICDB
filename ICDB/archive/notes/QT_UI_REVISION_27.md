# Revision 27 — Staged pinout deletion

Delete pinout now stages deletion for the global Save/Revert workflow. View Changes and crash recovery include staged deletions. The backend deletion executes under the same SQLite transaction as component, pin and group edits. For a pinout with pending unassignments, its group changes are applied before deletion. External revision/member conflicts abort the commit. Published link cleanup remains inside the database transaction; SVG files are preserved.
