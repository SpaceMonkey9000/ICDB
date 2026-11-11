# ICDB 0.8.6 (beta)

Integrated ICDB and ICPin with editable pinout groups, inline pin editing, continuous lists and expanded matching filters. One desktop application holds component records, editable pin definitions, source mappings, matching decisions and ICOCR image references.

## Start on Windows

**Installer or portable build (recommended):** run `ICDB_0.8.6_Setup.exe`, or extract `ICDB_0.8.6_Portable.zip` and start `ICDB.exe`. No Python installation is needed.

**From source:**

1. Extract `ICDB_0.8.6.zip` into its own folder.
2. Use Python 3.10+ and install dependencies: `py -3 -m pip install -r requirements.txt`
3. Run `run_ICDB_windows.bat`.

Then check the DATA path on the Components tab. **Choose DATA folder** selects an existing shared folder; restart after changing it. It does not copy or move data.

The tables live inside `components.sqlite`. The application makes a database backup under `DATA/backups` before its first 0.7 migration. Existing components and manual images are retained. New source imports do not generate images.

This is a beta release. Please report problems together with the version shown in the window title.

The Components tab shows catalogue devices with Part, Function, Manufacturer and Pinout columns. Double-click a part, function or manufacturer cell to edit it; F2/Enter also starts editing. The Edit selected cell and Check duplicates buttons, review-entry checkbox, Image references tool button and Evidence column have been removed. Source details remain below the list. Matching and Import retain their existing behavior in this release.

## Database version and enlarged pinouts

The bottom status bar shows the database's own version on every tab, independently of the application version in the title. The DATA builder stamps its installer version (by default the build date, e.g. **20261110**) inside the packaged database. Saved content changes append an increasing suffix: **20261110-r1**, **20261110-r2**, etc. The metadata travels with `components.sqlite` and survives restarts. Each newly built DATA release starts at revision zero; only the staged database is reset, never the source database.

For legacy databases without embedded version metadata, ICDB uses the installer's `data-pack-installed.json` **database_version** when available. It does not use `last_pack_version`, the current date or file timestamps, because those may belong to an asset-only update or a copied file. Without reliable provenance the base displays **Unversioned** until it is packaged by the updated builder.

The suffix counts changed content records, including components, descriptions, pinout definitions, imported source records, matching decisions and published image references. One import or action can change multiple records and increase the suffix by more than one. Reads, searches, unchanged updates, scan caches, UI settings and undo history do not increment it. Failed/rolled-back transactions do not retain their increments. Tracking applies to existing tables after ICDB initializes their schema; it does not reconstruct earlier edit history.

Double-click the pinout preview or a cell in the Components **Pinout** column to open a larger window. Resize or maximize it to scale the diagram; choose another linked package from the dropdown. Press Escape to close it. The window shows a snapshot of the linked pinouts when opened; reopen it after editing a definition.

## First workflow

1. **Components:** use the existing component database, or import a part-number/description CSV. Add and edit components here.
2. **Import → Choose pinout source:** choose a normalized master/grouped database, KiCad libraries, ICPin catalog/project, ICPin bundle or pin-table CSV. Inspect the preview, then click **Import previewed data**.
3. **Matching → Run matching:** generate candidates. Exact names, logic families, KiCad patterns and broader prefix/suffix candidates are considered. Every new match requires a review decision.
4. Inspect a row's reason, numbered pins and correctly titled preview. Select multiple rows with Ctrl/Shift; Ctrl+A selects the entire filtered list, including rows still being loaded. **Accept selected**, **Reject selected**, or **Reset selected**. **Compare selected** shows differences between up to six pin definitions.
5. **Publish to ICOCR:** generate only accepted links. Each diagram uses its linked component's name. Unchanged images are reused. ICOCR still receives the existing asset/link tables and relative SVG paths under `DATA/pinouts`.

Accepted records are not automatically published. Editing pin data also requires Publish to update ICOCR.

## Release notes

All changes, newest first, are in `CHANGELOG.md`.

## CSV duplicate replacement and SVG rebuilding

**Components → Import CSV** offers Yes (replace duplicates), No (skip duplicates, the default), or Cancel. Replacement updates the function for an exact part number match, ignoring case and outer spaces. Suffixes are retained. Since this CSV has only part number and function, all manufacturer variants of that part receive the supplied function. Component IDs, manufacturer fields and accepted pinout links remain intact. The last occurrence in the CSV wins in replacement mode; skip mode retains the first. The result report lists duplicates and function differences. Explicit replacement also permits reapplying a previously imported file. Original source evidence is retained.

**Pinout library → Rebuild SVGs** regenerates every accepted component/pinout diagram using the current renderer, including unchanged diagrams. It also publishes the rebuilt output to ICOCR. Save pending pin edits first. The action runs in the background and reports how many diagrams were rendered and links updated. Unaccepted definitions are not exported; manually attached images are retained. The rebuild uses the normal atomic publication workflow, so a rendering failure preserves the previous published links and SVGs. Older generated SVG revisions remain on disk.

## Edit or create a pinout

The Pinout library shows definitions, packages and accepted-link counts. Select a definition to edit its title, package, source and pin table. Double-click a pin cell (or press F2/Enter on a selected row) to edit inline. Tab/Shift+Tab moves between cells, Enter commits, and Escape cancels the cell edit. Drag column borders to resize them; drag the horizontal dividers to adjust the table, preview and member-list heights. Use **Paste table** or Ctrl+V in the table to replace the pin rows from tab-separated text in this order:

```text
1	OUT1	Output	First output
2	IN1-	Input	Inverting input
```

Use actual tab characters when pasting. Two columns (number and name) are enough; role defaults to Signal. Supported roles: Signal, Power, Ground, Input, Output, I/O, NC. CSV and semicolon-separated rows are also understood. An optional number/pin/pin_number header is ignored.

The preview updates after a cell edit is committed or metadata is changed. **Save** updates the shared definition and reports how many accepted links use it. **Save as new** creates/reuses a separate definition. Linked package/count changes require Save as new. A new definition initially contains NC placeholders; enter the real pin table before linking it.

To assign a pinout manually, select components on the Components tab, switch to Pinout library, select the saved definition, and click **Link selected components**. Review and accept those links in Matching. This explicit choice can resolve an ambiguous automatic suggestion; it does not claim electrical interchangeability.

The library dropdown offers **All pinouts**, **Accepted groups**, and **Without accepted parts**. When accepted groups already exist at startup, they are shown by default. The **Accepted** column counts the devices linked to each group. Library search also finds groups by their accepted device names.

The lower **Accepted devices in this pinout group** table lists every accepted member. **Add devices...** opens a searchable catalogue picker with multiple selection; **Add selected** accepts those links directly. **Remove selected** rejects those links and preserves their history. **Undo** reverses the last group/review decision. The next **Publish to ICOCR** applies membership changes to the exported references. Save outstanding pin edits before adding devices. To add a brand-new component to the catalogue, use **Components → Add device** first.

**Components → Edit / link pinout** opens the linked definition, or the matching list if several package choices exist.

## Imports and source changes

- Master/grouped SQLite input uses `definitions`, `devices`, `device_definitions`, `packages`, `pin_maps`, `pins` and `source_records`. The original decoded application's database is not this normalized format.
- Select several `.kicad_sym` files together when symbols inherit across libraries.
- ICPin JSON catalogs and projects are read directly. Bundle imports read catalog data without expanding SVGs.
- Pin-table CSV uses the ICPin headings: `pinout_id,package,pin_count,pin_number,pin_name,pin_role,description`. A second, optional mapping CSV uses `device,manufacturer,package,pinout_id,source_url,source_page,notes`.
- Identical package/pin data shares a definition; each source and its component names are retained.
- Reimporting unchanged sources does not duplicate them or overwrite manual edits.
- A changed source is held as a conflict. **Resolve source conflicts** compares current/incoming pins. **Keep current** dismisses that exact incoming revision. **Import as alternative** adds the incoming data separately, preserving existing links for explicit review.
- The import history records skipped and retained records. Unsupported master/JSON packages, and KiCad package records whose pins can be parsed, are stored for later work. The inherited CSV parser still requires a supported package. Unparseable records are reported.
- Master and CSV source namespaces use the filename. Preserve filenames between revisions of one source; use different filenames for unrelated databases with overlapping internal IDs.

## Review and output

Both Pinout library and Matching now show a single continuous list, with no page controls or result cap. Tk rows are inserted in short chunks so the interface can continue processing events. Click column headings to sort the whole filtered result; click again to reverse the order. Sorting uses natural part-number order and numeric accepted counts.

Matching search defaults to **Component**. Select **Pinout**, **Manufacturer** or **All fields** to change the search scope. Plain text is a substring search; `*` matches any characters and `?` matches one character. For example, `LM*` finds names starting with LM; `LM?58` finds LM258/LM358. Literal `%` and `_` are not treated as wildcards.

Filter by status, rule, package, manufacturer, cautions, conflicts, whether the component has an accepted pinout, or whether the match has been published. Filters combine with one another; choose Status **All** when you want to inspect conflicts across all statuses. **Reset** clears the filters. **Search datasheet** opens a Google search in your default browser using the selected component's exact part number plus manufacturer and `datasheet pdf`. It does not mark anything as verified.

Long import, matching and publishing operations run outside the Tk event thread.

Manufacturer conflicts, unsupported rendering and conflicting source assignments block automatic candidates. The retained logic-family, KiCad-pattern, variant-guard and CAN-caution rules assist review. Supply/ground synonyms are not used to automatically merge definitions.

Rejections survive unchanged scans and reimports. Changed evidence can reopen a rejection. Undo restores the last review decision; publish afterward if output was already changed. A changed component identity requires accepting its link again before publishing.

Publishing writes complete SVG revisions before committing link changes. A rendering failure leaves the prior published links intact. Unchanged accepted diagrams skip rendering. Rejecting a previously published link removes that managed association on the next publish. Historical SVG revisions remain on disk for recovery; automatic garbage collection is not included.

The legacy **Image references** tool is no longer exposed in the main window. Existing manual photos/scans and image associations remain intact. Generated pinouts are edited and linked through the native library/matching workflow.

## Upgrade scope

Existing imported pin definitions and accepted generated links are migrated additively. Existing rejected pairs are carried into the native review model. Legacy tables and their detailed decision/verification audit are retained; native matching does not translate every legacy verified-rule reuse into automatic approval. Existing manual image associations remain intact.

The older modules remain in the package for migration. Launch the application with `launch.py` or the batch file to use the integrated interface.

## Self-test

`ICDB.exe --self-test --report report.json` (or `python launch.py --self-test --report report.json` from source) opens the complete application against temporary data and reports startup success.
