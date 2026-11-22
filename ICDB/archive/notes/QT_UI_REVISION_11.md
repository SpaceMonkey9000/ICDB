# ICDB Qt Revision 11: Simple Component CSV Import

- Import tab accepts only UTF-8 CSV with `part_number,description` headers (or old `part_number,function` headers). Comma and semicolon delimiters are supported.
- Preview shows new, existing and repeated entries before importing.
- Existing part numbers are skipped, without modifying their descriptions.
- Import uses original `builder.import_file`, preserving source evidence and transactional writes.
- Old pinout import formats and source-conflict workflows are removed from the Qt interface, but retained in backend files.
- Export and update synchronization are intentionally not implemented. These require stable origin metadata, explicit conflict policies and a portable exchange format.
- No database schema changes.
