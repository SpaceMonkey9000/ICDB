# Open from ICOCR

ICDB now accepts: `python icdb_qt.py --data <shared DATA folder> --open-part <exact part number>`.

- Case-insensitive exact part-number lookup; no fuzzy search.
- Opens Components tab and selects the matching database row.
- Rejects missing/ambiguous results with a dialog and does not create records.
- Navigation runs after both recovery prompts complete, preserving staged drafts.
- Existing standalone invocation is unchanged.
- Multiple ICDB instances may be opened; single-instance IPC is not implemented.
