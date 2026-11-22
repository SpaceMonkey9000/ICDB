# ICDB user guide

## Saving works across all tabs

Changes on the Components and Pinout library tabs are **staged**. They stay in memory
until you press **Save** at the top right of the window.

- **Save** writes every staged component edit, new or deleted component, pinout
  definition, group change and pinout deletion in one database transaction. If any
  part fails, nothing is written.
- **Revert** discards everything staged, after asking.
- **View changes** lists what Save would write, pin by pin.
- **Unsaved changes** appears above the tabs while anything is staged.

Staged work is copied to a recovery draft about half a second after each edit. If
ICDB closes unexpectedly, the next start shows one prompt for component and pinout
changes: **Restore**, **Discard** or **Keep for later**. A restored draft is staged
again; press Save to write it. A draft is not restored if the database changed in the
meantime; it is kept and its path shown. A kept draft is never overwritten: if you
make new changes, it is set aside and offered again at the next start.

Problems that Save would refuse are reported when you make the change: a device that
already has a pinout in the same package is not added to another one, and a warning
appears on the right of the status bar when you change the package or pin count of a
pinout that has devices. Hover over it for details.

Closing ICDB with staged changes offers Save, View changes, Keep Draft, Discard or
Cancel.

The CSV import and publishing are separate operations and are refused while changes
are staged.

## Components

The left side lists the catalogue with Part number, Function and Pinouts columns.

- **Search** finds part numbers, functions and manufacturers.
- **Add device** stages a new component. **Edit device** changes its part number,
  function or manufacturer. **Delete device** stages a deletion.
- Double-click a Part number or Function cell, or press F2, to edit it.
- A part number and manufacturer that already exist, saved or staged, are refused
  as you enter them; the dialog stays open so you can correct them.

The right side shows the selected component:

- **Pinout** chooses between the pinouts linked to it. Wheel zooms the diagram, drag
  pans, double-click fits.
- **Search datasheet** opens a web search for the part number.
- **Edit pinout** opens the linked definition in the Pinout library.
- **Assign pinout** links the component to an existing definition. Pick it from the
  searchable list; the link is staged in that definition's group.
- **New pinout** starts a new definition with the component already in its group.
- **Aliases** lists the selected component's markings, package restrictions,
  and sources. Use **Add alias**, **Edit alias**, or **Delete alias** to stage a
  change. **Save** commits it and **Revert** discards it.

## Pinout library

The library has three resizable areas: the list on the left, the editor in the
middle, and the preview and Groups panel on the right. Drag the divider below
the preview to resize it.

**Library list.** Search by title, package or a linked part number. The filter shows
**All pinouts**, **Assigned groups** or **Without assigned parts**. Click a column
heading to sort. **New pinout** opens an empty definition. It is staged once you edit
it or add devices; staged new pinouts appear in the list in italics, marked *new,
unsaved*, and edited ones are marked *edited*. **Delete pinout** stages a deletion; if
devices are assigned, it offers to remove them as well. For a new pinout the button
reads **Discard new pinout**. A definition that an imported source refers to cannot be
deleted.

**Pinout editor.** Title, package, pin count, source and an optional exposed pad, above
the pin table.

- Double-click a pin cell, or select it and start typing, to edit it. Tab and
  Shift+Tab move between cells.
- The role column is a list: Signal, Power, Ground, Input, Output, I/O or NC. Click a
  role cell to open it.
- **Add pin** and **Remove pin** change the rows. Lowering the pin count asks first
  if it would remove rows that hold data. Up to 4096 pins are allowed.
- **Paste** replaces the rows with copied text, one pin per
  line: number, name, role, description. Tabs, semicolons or commas separate the
  columns; a header row is ignored. Number and name are enough; the role defaults to
  Signal.
- **Duplicate pinout** stages a copy under a new title. A new pinout whose pins are
  identical to an existing one can reuse that definition at **Save** when devices
  are assigned. **Cancel** keeps the draft open.
- **Use existing definition** appears when you started from a component's **New
  pinout** and want to link an existing definition instead.

You can switch between pinouts while editing; each keeps its staged changes.

**Groups panel.** The components that share this pinout.

- **Add devices** opens a searchable picker that also lists components added but not
  yet saved, marked *New — unsaved*. It shows each component's current pinout.
- **Remove devices** stages their removal.
- **Undo draft** reverses the last staged group change.

**Preview.** Updates as you edit. Wheel zooms, drag pans, double-click fits.

## Import

Imports new components from a CSV file with the columns `part_number,description`
(older files with `part_number,function` also work). Commas or semicolons separate
the columns; the file must be UTF-8.

1. **Choose files…** selects one or more CSV and ICDB JSON files in the same
   picker. The preview shows the source file for each row. Files are processed
   in the order returned by the picker, with earlier files available to later files.
2. Select unwanted preview rows and click **Delete** to exclude them. ICDB
   recalculates the preview before staging.
3. **Stage import** queues the selection for **Save**. CSV skips existing part
   numbers. JSON previews parts, pinouts, and assignments and reports conflicts.
   After saving, **Delete** clears selected rows from the review list.

If a CSV changes after preview, Save refuses the batch. Revert and select the
files again.

### JSON export

- **Import → Export all JSON…** exports all parts and structured pinout definitions.
- **Components → Export selected** exports the selected rows and their linked
  pinout definitions. Use Ctrl or Shift to select multiple rows.
- **Save** commits staged imports and edits in one SQLite transaction. **Revert**
  discards the staged import. ICDB saves compatible assignments and publishes
  their generated SVGs after Save. Review conflicts in the import preview.
- JSON exports preserve assignments and default pinouts. Legacy JSON imports
  carry forward links explicitly marked Accepted. Export again from the source
  database to recover assignments from a legacy file without link statuses.

ICDB saves a database backup in the shared DATA folder under `backups` before
converting the old review table. The migration preserves published assignments
and their defaults. Use the backup with earlier ICDB builds.

JSON files use `"format": "icdb-data"` and `"version": 3`. Both the `parts` and
`pinouts` arrays are optional. A part has a `part_number`, `manufacturer` and
`description`. A pinout has a stable, globally unique `id`, a `project` with
`device`, `package`, `count`, and `pins`, and an optional `devices` list of
part numbers, manufacturers, and an optional `is_default` flag. Each pin has a `number` and `name`, with optional
`role` and `description`. Use `project.source` for the datasheet reference.
Store an exposed pad as `project.exposed_pad`, with its own number and name. The
normal lead count excludes the exposed pad. A device link without a manufacturer
requires a unique part-number match. An explicit empty manufacturer matches a
component whose manufacturer field is blank.

## Settings

- **Appearance:** Light or Dark graphite. **Invert pinout images in dark mode** shows
  diagrams with inverted colours; the files are not changed.
- **Data:** the shared DATA folder. A change applies after restarting ICDB and ICOCR,
  and existing files are not moved.
- **Tools:** **Publish pinouts** updates the diagrams and links ICOCR uses, for
  pinouts that changed since the last publish. **Rebuild all SVGs** redraws every
  diagram, for example after a renderer update. Both run in the background and report
  what they did. A failed publish leaves the previous diagrams and links in place.

## Working with ICOCR

In ICOCR's History tab, **Open in ICDB** opens ICDB with the matched part selected, and
**Add to ICDB** opens ICDB with a new component staged. Neither writes anything until
you press Save in ICDB.

ICOCR reads published pinouts only. After Save, the pinouts you changed are published
automatically, with progress in the status bar; other pinouts are not checked. If that cannot happen (another operation is running, new changes were
staged, or publishing failed), **Publish to ICOCR** appears at the top right until the
pinouts are published. Then use **Reload database** in ICOCR.
