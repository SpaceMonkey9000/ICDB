# ICDB PySide6 UI Revision 7

Based on Revision 6. No database schema change.

- **Add devices to pinout group**: Removed Manufacturer column; added **Current pinout**, populated from Accepted `pl_matches` associations. Shows all accepted pinouts when more than one exists, including package family and pin count; suggested pinouts do not count as assigned. Lookup is batched to avoid a query per device. Retains Part number and Function. Dialog table is sortable.
- **Group members**: Removed Manufacturer column, displays Part number and Function, with sortable headers.
- **Editor**: Properties section is above Pins in a normal vertical layout; the adjustable horizontal splitter between these sections was removed. Main window horizontal splitters remain resizable.
- **Appearance**: Adopted all six palettes from the ICOCR pre-tracking Qt baseline: Dark, Graphite, Slate, Modern light, Windows classic and Warm light. Existing ICDB Light remains Modern light; legacy `dark` setting maps to Graphite. Optional pinout inversion in dark themes is retained.
- The existing SQLite format, accepted-group write behavior and publication controls remain unchanged. Matching and Import remain excluded.

## Validation

Python compilation, a temporary SQLite query check for multiple accepted pinouts and ZIP integrity checks passed. Windows GUI execution was not available for testing.

**Data caution:** Accepted-group edits still commit immediately. Test against a backup DATA folder.
