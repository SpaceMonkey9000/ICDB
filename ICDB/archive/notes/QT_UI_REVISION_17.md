# Revision 17 — startup crash and compact change review

- Fix initialization-order crash: first PinoutLibraryPage selection no longer
  tries to save a draft before MainWindow.library_page has been assigned.
  `save_draft` itself also guards against early initialization calls.
- View Changes now shows only actual changes to each pin (name, role,
  description, additions/removals and reordering) instead of a unified diff
  containing unchanged context pins. Summarizes the unchanged pin count.
- No changes to transactional SQLite save, staged session or recovery format.
- Added tests for a single modified pin within a 32-pin device, additions,
  removals and reordered pins.
