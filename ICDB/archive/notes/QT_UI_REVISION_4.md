# ICDB PySide6 — Pinout Library workspace revision

This version replaces the permanently visible Pinout Library editor with a browse-first three-column layout.

- Library list on left, with search and filtering.
- Zoomable/pannable pinout preview always visible in the middle.
- Read-only selected definition and accepted devices on right.
- Edit toggles right panel to Pins, Groups, and Properties tabs.
- New creates an unsaved pinout and opens Properties.
- Save commits pin definition changes using the original Library backend. Cancel restores the stored definition.
- Group membership changes remain immediate database writes, as in the original application. These cannot be undone by Cancel; the group Undo action is retained.
- Publish accepted pinouts is now under Settings > Tools. It remains a separate, confirmation-protected operation.
- A 250 ms debounced preview updates while editing.
- The three column widths are resizable and remembered.
- Matching and Import are excluded. No database schema changes.

## Validation
Python AST parsing and compilation passed. Qt GUI operation has not been tested in this environment (PySide6 not installed). Test only on a copy of the shared DATA database.
