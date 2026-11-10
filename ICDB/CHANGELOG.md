# ICDB release notes

All ICDB changes in one file, newest first. Earlier versions were released as separate RELEASE_x.md files.

## ICDB 0.8.5-RC1

- Database base version now comes from the DATA installer build stamp, e.g. 20261110, followed by -rN after saved changes. Legacy installed databases can recover their original release from the installer's active-database state; unknown provenance displays Unversioned.

## ICDB 0.8.4-RC1

- Persistent database version in the bottom status bar across every tab, separate from the application version. Databases without metadata start at 1.0; SQLite content triggers append an increasing -rN suffix when records change, including worker/import writes. Rollbacks and unchanged updates preserve the previous version.
- Double-click the component pinout preview or Pinout column to open a larger, resizable viewer with package selection and automatic diagram scaling.
- Matching and ICOCR publication retain their existing behavior.

## ICDB 0.8.2-RC1 (beta release candidate)

First public beta release candidate. Functionally identical to 0.8.2; packaging only:

- Version is now 0.8.2-RC1 (window titles, self-test report and Windows file version).
- Development files removed: unit tests, validation reports, release audits and version-specific example renders.
- Per-version release notes merged into this file.
- Can be built into a Windows installer and portable zip with the ICSuite build kit.

## ICDB 0.8.2

DFN diagrams rotated 90° clockwise: pin 1 is at the upper left, with pins down the left side and up the right side. Labels stay horizontal. Saved pin mappings are unchanged. The renderer version is bumped so published SVGs regenerate on the next publish/update.

## ICDB 0.8.1

Bug-fix release from the 0.8.0 code review. Diagrams and the renderer are unchanged (renderer version stays 0.8.0), so there is no need to rebuild SVGs. No schema change. On first start, stored package labels merged by 0.8.0 (for example `SOT-235`) are corrected to `SOT-23-5`.

### Fixes

1. **Undo could re-accept a conflicting pinout** (`pin_library.py`). Undoing a reject now re-checks the part/package. If a different pinout was accepted since then (for example by another user), the undo is refused, nothing changes, and the operation leaves the undo history. The message names both pinouts.
2. **Batch review pre-checked unrelated parts** (`pinout_matcher.py`). "Shared number only" rows (LM358 → MAX358) are now CAUTION rows, so they never start checked. Between known second-source prefixes (LM/KA, NE/SA...) the caution says so. Exact names from a different manufacturer are a CAUTION instead of a block, matching library matching. The second-source prefix list is now shared by both matchers.
   - Batch review keeps its *Shared number only* queue, so these rows are still reviewable there. Library matching is unchanged: these rows stay Blocked.
3. **Rule results are checked; failed rules are dropped** (`rule_api.py`, `pinout_matcher.py`, `library_matcher.py`). A rule that returns the wrong shape (for example `'block'` instead of `('block', text)`) is treated like one that raises. Batch review now drops a failing rule and recomputes the scan without it, reporting it once, as library matching already did.
4. **Typed cell edits were discarded when busy** (`browser.py`). If a pinout operation or image scan is running, the editor stays open with your text and the status line says to press Enter again. A row deleted by another user now shows a message instead of silently closing the editor.
5. **Package names** (`pinouts.py`). SOT-23, SC-70, SC-74, SC-88, TO-92 and SOT-323/353/363/563 keep their pin count separate. Other `FAMILYnn-count` names written with separators are split on the last separator. `migrate_package_labels` fixes stored `icpin_pinouts`, `pinout_links` and `pinout_match_decisions` labels once. Batch decisions recorded against an old label reopen for review.
   - Pin numbers use `isdecimal()` instead of `isdigit()`, so a value like `²` is kept as text instead of raising an error (master import, pin grid, exposed pad, rules, comparison).
6. **Site match rules need trust** (`rule_api.py`, `workbench.py`, `matcher_ui.py`). Python files in `DATA/match_rules` run only after someone on this computer trusts that exact file content (SHA-256). **Run matching** and the batch review scan ask once per new or changed file:
   - *Yes* trusts the file.
   - *No* runs without it and doesn't ask again for that version.
   - *Cancel* stops.

   Decisions are stored in `%LOCALAPPDATA%\IC_Tools\trusted_match_rules.json`, outside the shared folder. Shipped rules no longer modify `sys.path`, and the loader provides `_shipped_helpers` directly.

### Not in this release

These are planned for 0.9:

- Publish holding the database lock while rendering.
- Treeview sort speed.
- `shared_data` temp-file race.
- Bundle SHA dedupe.
- UNC path support for master import.
- CSV formula escaping.
- SVG garbage collection.

## ICDB 0.8.0

QFN perimeter pads now match the DFN rendering: a single clipped-tip outline with no internal U-shaped lines. The shared renderer updates both desktop previews and exported SVGs.

Numbering, labels, package geometry and configured exposed pads are unchanged. QFP and DFN rendering is unchanged. No database migration is required.

Use **Rebuild SVGs** or **Publish to ICOCR** to refresh existing diagrams.

## ICDB 0.7.9

MSOP support and optional exposed-pad editing, matching and publication.

The Pinout library editor now provides an Exposed pad checkbox. Enabling it reveals identifier, connection/name, role and description fields. Disabling it hides the fields and removes the pad from the diagram. Pad details are separate from the normal lead table and count.

MSOP, SSOP and TSSOP remain separate physical package types. SOIC, MSOP, SSOP, TSSOP, QFP, QFN, DFN and PowerSO20 can draw the optional underside pad. Existing TO/SOT tabs are unchanged.

Definitions without a pad retain their existing signatures. Enabling a pad or changing its identifier, connection, role or description changes definition identity. Package labels include `-EP`; ordinary and EP versions can be maintained separately. The editor's existing Save as new protection prevents converting a linked package group into a different physical variant. Sharing a connection edit within an accepted group retains the existing confirmation and Publish workflow.

Explicit pad metadata survives project/catalog JSON, CSV and bundle import. Pinout comparison, conflict review and matching rules include the extra terminal. Imported unsupported footprint descriptions are not guessed into a supported package; configure the separate pad explicitly in the editor when the manufacturer pin table is known.

No database migration is required. Existing definitions open with pad disabled. Publish to ICOCR or Rebuild SVGs updates generated references with renderer 0.7.9. ICOCR continues to receive standard SVG assets and existing asset/link records; the external lead count excludes EP.

## ICDB 0.7.8

Adds the requested package families to the existing pinout workflow. Diagram styling follows the existing black outlines, white fill, bold signal labels, lead-bend lines and internal terminal numbers. The supplied reference images informed TSOP orientation, PLCC J-lead appearance and PowerSO20 body recesses.

| Package | Supported numbered terminals | Top-view orientation |
|---|---|---|
| SSOP | 4–64, even | Pin 1 upper left; down left, up right |
| TSOP-I | 8–86, even | Wide body; pin 1 upper left; down left, up right |
| TSOP-II | 8–86, even | Horizontal body; pin 1 lower left; along bottom, back along top |
| PLCC | 20, 28, 32, 44, 52, 68, 84 | Pin 1 at top centre; counter-clockwise |
| PowerSO20 | 20 | Pin 1 upper left; down left, up right |

Count ranges are editor limits, not a claim that every count is a manufactured standard. PLCC32 is drawn as 7 top / 9 left / 7 bottom / 9 right; the other listed PLCC sizes use equal sides. Manufacturer PLCC32 numbering was checked against Microchip AT27C256R, document 0014, page 2: https://www.microchip.com/content/dam/mchp/documents/OTH/ProductDocuments/DataSheets/doc0014.pdf .

### Imports and compatibility

- The editor, preview, SVG publication, image-reference choices and ICPin bundle reader recognize the new families.
- KiCad explicit footprints and footprint filters accept SSOP, TSOP-I, TSOP-II, PLCC and PowerSO-20/PowerSO20. Explicit footprint counts must agree with the parsed pin table.
- Normalized pinouts_master imports accept the same families and corresponding footprint-style names. Generic TSOP without a type is not converted to either physical layout.
- Project JSON fields and database schema remain unchanged. Existing pin tables, decisions and diagrams remain in place. No user database is included or altered by this source release.
- Application and renderer versions are 0.7.8. Use Publish or Rebuild SVGs to regenerate accepted diagrams with the current renderer.

### Thermal slug and pad scope

PowerSO20 rendering represents the supplied top-view outline and its 20 leads. An unnumbered underside slug is not a pin 21. Its electrical connection is device-specific and must be recorded in the appropriate pin description/source evidence. Separate numbered exposed-pad definitions and other package-family exposed-pad enhancements remain outside this release; the importer continues to reject unsupported exposed-pad footprints rather than drop terminals.

## ICDB 0.7.7

The Components tab now includes a resizable pinout preview at the bottom right. Selecting a component displays its default image reference or accepted library definition; a selector exposes additional packages and references. Missing files and unlinked devices display a clear message.

Existing component metadata is edited inline. Double-click Part, Function or Manufacturer / group. Enter saves; Escape cancels; Tab and Shift+Tab save and move through editable fields. Validation rejects blank part numbers and duplicate part/manufacturer combinations. Component IDs, source evidence and pinout associations are retained.

The existing DATA folder remains compatible. Extract this release to a separate application folder and select the same DATA folder when needed. Run run_ICDB_windows.bat.

## ICDB 0.7.6

- Redrawn SOT-223 to match the supplied SOT223.jpg reference, using existing monochrome SVG styling.
- Wide rectangular body, square tab and lead bend details; no dimension lines.
- Supports existing 3-pin and 4-pin definitions without changing electrical mappings.
- Renderer version incremented so Publish regenerates cached diagrams.
- Components: replaced Manufacturer / source group with Pinout, showing accepted base definitions and packages (including unpublished links).
- Components: added Search datasheet for the selected catalogue device.
- Removed the forced Windows DPI-awareness override inherited from 0.7.5; startup now uses the default Windows/Python scaling behavior.
- Edit / link pinout now stays in Pinout library, opens the accepted base definition and ignores unaccepted matching candidates. Multiple accepted packages are shown in the library for selection.

## ICDB 0.7.5

Bug-fix and rules release, based on the 0.7.4 code review. No database schema change except additive columns; existing data upgrades in place.

### Publishing and matching
- Publish and Rebuild SVGs no longer abort when one accepted link is blocked, has a changed component identity, or cannot be rendered. That link keeps its previous output and is listed under "skipped"; everything else publishes.
- The SVG cache key now follows `pinout.VERSION`, so a renderer change is picked up by a normal Publish (bump `VERSION` whenever drawings change). Expect one full re-render after upgrading.
- Saving a pinout that has accepted links is refused if it cannot be rendered (for example pin number `EP`).
- Source identities now include the import namespace. Two imports with the same internal ID (ICPin project files, master DB row IDs) no longer overwrite each other's suggestions.
- Pin numbers such as `EP`, `A1` and `TAB` no longer crash matching.
- A broken or failing rule is skipped and reported after Run matching instead of stopping the scan.
- Prefix/suffix suggestions keep their strength. "Shared number only" (LM358 → MAX358) is now rule `prefix-shared-number-v1`, starts Blocked, and is a caution only between known second-source prefixes. Links accepted under the old rule stay accepted.
- Links you accepted before a new rule existed are never blocked by it: the rule's verdict is shown as a caution and the link keeps publishing. **After upgrading, run matching and check Show → With cautions.** Structural blocks (conflicting sources, unrenderable pins) still apply.
- Exact names from a different manufacturer are a caution instead of a block.

### Rules
- Logic family: chargers and op-amps (TP4056, TC4054, UPC4558 …) are no longer treated as 4000-series CMOS.
- CAN caution: the English word "can" no longer triggers it; LIN transceivers get their own caution; more CAN parts recognised.
- Variant guard: string pin numbers, more supply/pad names, and a caution when only one suffixed variant is in the library.
- New: `15_cmos_cross_family`, `50_package_suffix_guard`, `55_power_pin_sanity`, `60_three_pin_caution`, `70_second_source`, `80_already_accepted`, `90_definition_quality`. See `match_rules/README.md`.

### Shared DATA folder
- Accept, group, undo, import, link and save take the database write lock before validating, so two users cannot accept conflicting pinouts.
- Background work waits up to 30 s for a busy database; the main window waits up to 8 s, then reports that the database is busy.
- Undo only reverses your own decisions (per user and computer, also after a restart), says what it will undo, and can no longer get stuck. Undo of "Add devices" removes the added links.
- Legacy migration tolerates bad rows (unknown roles, orphan links), records them in the import history and no longer blocks startup.

### Import
- CSV: UTF-16 ("Unicode Text") files, Excel `sep=;` lines and mis-decoded BOMs are handled; the Windows-1252 note is shown in the report.
- CSV exports include the catalog ID in file names and a column, so re-imports keep separate namespaces. Old `pinouts.csv` files import as before.
- KiCad symbols with pads such as `EP`/`A1` are kept as unresolved records instead of being dropped.
- Master DB titles are stable between imports.
- Search ignores case for non-ASCII letters (ö/Ö, µ) and treats `%` and `_` literally.
- `data_location.json` saved with a BOM is accepted.

### Rendering
- SOT-223 tab label no longer clipped when pins are stored out of order; less empty space below.
- QFP numbers ≥ 100 no longer overlap the outline.
- Whitespace in names is collapsed, so SVG and preview agree; labels get 10 % width margin.

### Interface
- Closing while Image references is scanning no longer leaves a half-closed app.
- Background polling survives errors; errors in buttons are shown in a dialog.
- Pin grid: the role dropdown works, Tab between cells keeps the editor open, Escape returns focus to the table, Linux wheel scrolling commits the edit.
- Ctrl+A followed by a column sort keeps the full selection.
- Returning to the Components tab keeps selection and scroll position and only reloads when the database changed.
- Run/Publish ask before closing Image references and explain when they cannot.
- Natural sort no longer crashes on `²` and sorts decimals by value.
- High-DPI awareness on Windows; windows fit smaller screens.
- One version string (`version.py`).

### Not changed (deferred)
- KiCad and master import roles for hidden/passive GND pins (would change signatures of existing sources and cause re-import conflicts).
- Exposed-pad drawing, new packages, overbars, cleanup of old SVG revisions.
- Search uses Unicode case folding in Python, which is slower than SQLite's own LIKE on very large catalogues (about 0.1 s at 50,000 components).
- Matching is about 1.3× slower than 0.7.4 because of the extra rules (about 6 s for 50,000 components and 5,000 pinouts).

## ICDB 0.7.4

- CSV import now offers replacement or skipping of duplicate part numbers. Replacement updates functions in place, preserves component identity and pinout links, and uses the last CSV occurrence. Previously imported files can be reapplied explicitly. All manufacturer variants of an exact part number receive the supplied function.
- Added **Rebuild SVGs** to the Pinout library. Forces current-renderer output for every accepted link and publishes it to ICOCR, with background execution and a render count. Previous output survives rendering failure. Manual images and older generated revisions remain intact.
- CLI CSV replacement: `python builder.py --db PATH import --replace-duplicates FILE.csv`.

## ICDB 0.7.3

Batch acceptance checks the entire selection before changing any links. A conflict window lists every affected component, package, proposed pinout, existing accepted pinout/link IDs, and the reason. It also detects different pinouts for the same part/package within the selected batch.

Use Accept remaining links to accept the entries that passed validation and leave problem entries unchanged. The remaining selection is validated again before saving. Existing accepted links are never silently replaced. Close leaves the whole batch unchanged.

Pin data comparisons remain strict: differing pin names, roles or descriptions may trigger a conflict even where you determine the devices are equivalent. Compare the definitions and reject the incorrect link before choosing its replacement. Acceptance is transactional; no partial batch changes occur on failure.

Includes the Function columns and search from 0.7.2. Use the existing DATA folder and custom rule modules.

## ICDB 0.7.2

- Matching displays each component's function description instead of its manufacturer column.
- Accepted devices in this pinout group displays Function instead of Manufacturer.
- Matching search adds Function; All fields also searches descriptions. Wildcards still work.
- Selection details show the full function description. Both Function columns remain sortable and resizable.
- Manufacturer filters, datasheet queries and conflict checks retain manufacturer information.
- Descriptions support manual review; automated matching and acceptance rules are unchanged.

Extract the whole application folder and keep using your existing DATA folder. Existing custom rules in DATA/match_rules continue to load. The separately supplied prefix module is not bundled here.

## ICDB 0.7.1

UI and workflow fixes requested after testing 0.7.0. Existing 0.7.0 data is used in place; there is no database format replacement.

### Pinout library

- Added an Accepted groups view and a full, selectable member table.
- Add existing catalogue devices directly to a group; remove selected members; undo the decision. Accepted counts update immediately.
- New group additions are atomic: if one assignment conflicts with another accepted pinout for that package, the batch is rolled back.
- Pinout, Package and Accepted headings sort ascending/descending, with natural name and numeric count ordering.
- Replaced the pin text box with an inline-editable table. Pin number, name, role and description have resizable columns. Roles have a dropdown; Tab/Shift+Tab moves between cells, Enter commits, Escape cancels.
- Added pin-row add/remove, clipboard paste/copy and draggable table/preview/member dividers.
- Removed paging; all matching library records appear in one continuous scrollable list.

### Matching

- Removed paging and the 500-row limit.
- All main table columns are sortable across the full filtered result.
- Added `*` / `?` wildcard search and selectable Component / Pinout / Manufacturer / All fields search scope.
- Added rule, package, manufacturer and review/publication filters alongside status.
- Added Search datasheet, opening an exact-part-number/manufacturer Google search in the default browser. The button does not auto-verify or approve a match.
- Ctrl+A applies to the entire filtered result even while remaining rows are loading.

### Large lists

The list queries return compact summary columns; complete pin tables are retrieved when a pinout is selected. Tree rows are inserted in small scheduled batches. There is no pagination or silent result truncation.

A synthetic desktop run displayed **80,000 pinouts and 15,000 matches** in **2.79 seconds** in this Linux test environment. A UI heartbeat continued during loading. This is a responsiveness check, not a timing guarantee for the user's Windows PC or live dataset.

### Use

Extract this folder and run `run_ICDB_windows.bat`, using your existing DATA folder. Save pin changes and use **Publish to ICOCR** after group changes. Requirements are unchanged.

## ICDB 0.7.0 — first integrated pinout release

Based on the supplied ICDB 0.6.0 and ICPin 0.3.0 sources. This implementation was designed from the current conversation, independently of the discarded ICWorkbench note.

### Delivered

- Four workspaces: Components, Pinout library, Matching and Import.
- Persistent pin definitions and source records in the component database; no catalog-to-bundle handoff for normal work.
- Direct master/grouped DB, KiCad, catalog/project JSON, bundle and pin-table CSV imports.
- Strict definition deduplication with separate source aliases/provenance.
- Import preview, repeat-import protection, retained incoming conflicts and conflict comparison/resolution.
- Integrated pin-table editor with live package preview and shared-definition impact notice.
- Indexed candidate generation using existing exact, prefix/suffix, logic-family, KiCad and caution/guard rules.
- Persistent accept/reject decisions, manual assignment, batch selection, undo and pin comparison.
- Per-component diagram titles, multiple package links, accepted-only publishing and unchanged-render caching.
- Immutable generated file revisions with one database publication transaction; failures preserve the previous output.
- Additive upgrade with a database backup and preservation of existing component/manual-image data.
- Background jobs and paged pinout/review tables.

### First-release limits

- The supplied archives contain source/examples, not the live component or master databases. Full real-data migration and matching coverage remain to be tested with those databases.
- Windows launch/runtime and live ICOCR integration were not executed here. The existing consumer-facing database tables and SVG conventions are retained and exercised in tests.
- Package drawing coverage is inherited from ICPin. Unsupported usable pin data is retained where the importer supports it; it cannot be published until a supported, valid package definition is supplied. The CSV parser remains limited to supported packages.
- Imports that change an existing source require explicit conflict review; choosing an alternative preserves both definitions.
- The main component catalogue still uses its established editing layout; the new pinout and matching workspaces are the first integrated UI.
- Historical generated SVGs and legacy audit tables are retained. Automatic pruning, a dedicated datasheet-verification workflow, and broader manufacturer naming rules are future work.

## ICDB 0.6.0 — Pluggable matching rules

Matching rules can now be added as Python files without a new ICDB release.
See `match_rules/README.md`. Shipped rules:

- **Logic family** — 74xx / 54xx / 4000-series parts with the same function
  number as a device on a diagram (74xx14, 4060, 74xx1G14).
- **KiCad pattern** — x-wildcard symbol names (STM32F405RGTx).
- **Variant guard** — blocks non-exact suggestions when suffix variants of the
  part have supply/ground/NC pins in different places (TJA1051 pin 5, op-amp
  R-versions with V+/V- swapped). Shows the differing pins.
- **CAN caution** — CAN bus transceivers start unchecked, carry a CAUTION reason
  and are listed in the new **Caution** queue.

Batch review: new queues **Caution** and **Rule suggestions**. Caution rows are
never pre-checked, so "Apply checked visible exact" cannot accept them.
Problems loading a rule are shown in the status line; matching continues.

Broad built-in suggestions (suffix/prefix/shared number) are no longer repeated
for a diagram when a rule or an exact name on that diagram already covers the
same part.

Use ICPin 0.3.0 `master_to_bundle.py` to import pinouts_master.db: it produces
five bundles that fit ICDB's bundle limits.

Extract into a new application folder and keep your DATA folder. No database
migration; no new dependency.

## ICDB 0.5.2

Added TO-247, TO-263, TO-263AB and SOT-223 support, with compatible package/count validation and matching.
TO-220, TO-252, TO-263 and TO-263AB accept 3/5/7 pins; TO-247 accepts 3/4; SOT-223 accepts 3/4 (pin 4 is the tab).

ICPin uses the normalized pinouts_master.db importer and retains datasheet links. Legacy components database import has been removed. Existing catalogs remain readable.

## ICDB 0.5.1

### Database editing

- Select one catalogue record and click Edit device…, or double-click its row.
- Edit part number, function / description and manufacturer / group.
- Save updates the existing record in place; Cancel makes no changes.
- Record ID, original source-evidence rows and pinout links remain intact.
- Part numbers are trimmed and uppercased, consistent with Add device.
- Empty part numbers and duplicate part/manufacturer identities are rejected.
- The inferred family hint is recalculated when the part number changes.
- The catalogue and any open pinout manager refresh after saving. Search is
  retained unless it would hide the edited record.
- Source-review entries remain original import evidence; edit the associated
  catalogue device instead.

### Multi-group pinout review

- Pinout groups supports Ctrl-click and Shift-click selection.
- Accept checked and Reject checked act on checked visible candidates in all
  selected groups. Unselected groups, hidden candidates and unchecked rows are
  excluded. Non-actionable rows cannot be accepted.
- The diagram and candidate list follow the focused selected group.
- Check visible group / Clear group still apply to the displayed group only.
- Candidate exclusions are retained when switching groups and across rescans.
- Multi-group acceptance is saved as one operation, undoable with Undo batch.
- Ctrl+Enter uses the same multi-group acceptance.
- Apply checked visible exact retains its existing all-visible-exact scope.
- Defer group, Resume deferred and Bulk assign act on the displayed group.

### Upgrade

Extract into a new ICDB_0_5_1 application folder. Close the previous release,
start run_ICDB_windows.bat, and select the same shared DATA folder if needed.
No database replacement or schema migration is required. Dependencies are
unchanged. No user database or generated data is included in this archive.

## ICDB 0.5.0 — ICPin package support and faster batch review

### Changes

- Import ICPin 0.1.9 bundles containing QFP, QFN, DFN, TO-220, TO-252 and SOT-89, alongside DIP, SOIC and TSSOP.
- Match ICPin's package-specific pin-count rules: QFP/QFN 4–256 in multiples of four; DIP/SOIC/TSSOP/DFN 4–64 even; TO-220 3 or 5; TO-252 and SOT-89 3.
- Preserve numeric package-family names such as TO-220-3, TO-252-3 and SOT-89-3 during import, association and matching.
- Add the missing package choices to the pinout association editor.
- Batch-review candidate checkboxes start checked. Uncheck any candidates you do not want to include before choosing **Accept checked + next**.
- Explicitly unchecked candidates remain unchecked through filtering, navigation, rescans and reopening the review window. New candidates start checked. Linked, blocked and unmatched rows remain unavailable for selection.
- **Apply checked visible exact** also respects unchecked candidates. Acceptance still requires an action and revalidates the affected diagrams.

### Upgrade

Extract this release into a new application folder, retain your existing shared DATA folder, and run `run_ICDB_windows.bat`. Dependencies are unchanged. No replacement database is included. ICPin itself is unchanged.

On the first opening after upgrading from 0.4.9, candidates use the new checked-by-default behavior. The old session did not record explicit unchecked choices, so its previous unchecked rows cannot be distinguished from untouched rows. Filters, deferred groups and manual assignments are retained.

## ICDB 0.4.9 — Batch pinout review

### Upgrade

Extract this release into a new application folder. Keep using the existing
shared DATA folder and start `run_ICDB_windows.bat`. No new dependency or
replacement database is required. The new review-session and explicit-mapping
tables are created automatically. Existing links, defaults, batch ownership
and 0.4.8 rejection decisions are preserved.

### Workflow

Open **Pinout manager → Batch pinout review**.

1. Start with **Exact** and use **Apply visible exact**, or review **Pending**.
2. Select a pinout group on the left. The middle shows its diagram. The right
   lists the source identities and proposed target devices.
3. Check the target rows to approve. **Check visible group** checks only the
   actionable rows currently visible in that group.
4. **Accept checked + next** commits those rows as one undoable batch and moves
   to the next visible group. Unchecked candidates remain pending.
5. Use **Defer group** for work to return to later. The **Deferred** queue lists
   those groups; **Resume deferred** returns the current group to normal review.

Checks persist between groups and sessions, but Accept/Reject operates only on
checked rows currently visible in the current group. **Apply visible exact**
operates across all visible groups and obeys all filters. It never includes a
family or numeric-only suggestion.

### Review controls

- Three panes: pinout groups, source/optional existing diagram, candidate rows.
- Groups share the same imported catalogue, diagram ID and package. Separate
  source identities remain visible; conflicts are never hidden by grouping.
- Queues: Pending, Exact, Verified mappings, Suffix variants, Family suggestions,
  Shared number only, Unmatched, Conflicts, Deferred, Linked, Rejected and All.
- Filters: import catalogue ID, manufacturer, package, pin count, matching rule,
  existing-reference presence and free text. Batch IDs identify ICPin catalogues;
  repeated imports of the same catalogue remain the same batch filter.
- Shared-number suggestions are excluded from normal review by default. The
  dedicated Shared number only queue and All expose them explicitly.
- Changed source/target characters are highlighted in the details pane.
- **Compare existing reference** displays the selected target's current references
  beside/below the source preview. Choose a reference from the list. Package and
  label are shown; a reference in another package does not establish compatibility.
- Double-click the source diagram to enlarge it.
- Space toggles selected candidate rows; Ctrl+Enter accepts checked rows;
  Ctrl+R rejects; Ctrl+D defers; Alt+Left/Right moves between groups.
- Filters, current group/candidate, checked rows, deferrals and pending manual
  targets are saved in the active database. Changed evidence reopens a deferred
  group. Stored manual targets include identity checks against reused database IDs.

### Bulk manual targets

**Bulk assign** accepts pasted exact part numbers separated by whitespace,
commas, semicolons or newlines. Resolve first, select identities, then add them
for review. Missing names are reported and duplicate manufacturer identities
are marked ambiguous rather than silently selected. No association is written
until checked candidates are accepted in the main workspace. Manufacturer,
diagram integrity and pin-assignment conflict checks still apply.

### Reusable verified mappings

Enable **Save accepted pairs as verified mappings** when accepting a reviewed
group. Each saved pair records the source identity/manufacturer, target
identity/manufacturer, package, pin-assignment signature, source URL/page and
originating batch. Identical future imports can reuse that explicit pair as a
reviewable suggestion. These are user-reviewed mappings, not automatic
validation against a datasheet. No suffix-stripping or inferred family rule is
created. Different pin assignments, packages or identities do not inherit it.

**Verified mappings** opens the stored list. Disable selected entries to stop
reuse without removing existing associations. Undoing the originating acceptance
batch also disables mappings created/reactivated by that batch. A later batch
that reuses an already-active mapping does not take ownership of it.

## ICDB 0.4.8

Date: 13 October 2026

### Purpose

Bug-fix release from the October 2026 code review (IDs refer to that review).
No new features and no new dependencies.

### Fixes

- **DB-B1 Undo of matcher batches.** "Set default" and undo itself no longer
  release a batch's ownership of its links, so undo removes what the batch
  added. Changing a matcher-created link's package, pin count or label still
  releases it, so real manual edits survive undo. Existing databases get the
  corrected trigger automatically when they are opened.
- **DB-B2 Unsaved typing lost.** The 30 s background scan only refreshes the
  pinout manager when it actually imported something, and refreshing keeps
  unsaved caption/source text and the current preview of the selected image.
- **DB-B3 Repeated issue windows.** Files that fail to import are remembered
  (with size and modification time) and skipped by background scans until they
  change. The "Pinout import issues" window opens only for Scan now / Import
  images; Scan now retries remembered failures.
- **DB-B4 Wrong raw source lines.** CSV imports containing characters such as
  U+2028 or form feeds inside a cell now store the correct original line for
  every part.
- **DB-B5 Startup errors.** `run_ICDB_windows.bat` now starts `launch.py`, so a
  bad `data_location.json` or a DATA folder held by another program is shown
  in a dialog. A malformed `data_location.json` gives a clear message naming
  the file.
- **DB-B6 Orphan image files.** Reimporting an ICPin bundle deletes the
  superseded generated SVG once nothing refers to it. Importing an image
  registers it before writing the file, so a failed import leaves no file.
- **DB-B7 Import retry.** After a failed bundle import (for example "catalogue
  changed after preview") the preview is refreshed and Import is enabled again.
- **DB-B8 Bundle pin fields.** Bundles with non-text pin role/description or
  project device/source are rejected at preview; the matcher also tolerates a
  missing role.
- **DB-B9 Reused device ids.** Deleting a device also deletes its match
  decisions, so they cannot apply to a later device that reuses the id.
- **DB-B10 Export errors.** A failed Export tables now shows an error dialog.
- **DB-B11 Blank part numbers.** A device with no part number (from outside
  edits) no longer crashes filename suggestions, bundle preview or matching.
- **DB-O1 Background scan cost.** The scan skips the generated `pinouts/icpin`
  folder without walking it, and reuses one worker connection per pinout
  manager window instead of reconnecting and re-running migrations every 30 s.
- **Cleanup.** Unused imports removed (DB-C1); `launch.py --self-test` works
  outside Windows (DB-C3); `builder.py` command-line entry moved to the end of
  the file with normal imports (DB-C4).

### Upgrade

Extract into a new application folder and keep your existing shared DATA
folder. Run `run_ICDB_windows.bat`. Dependencies are unchanged. The database
update is automatic on first start (one trigger replaced, one table added);
existing devices, images, links and defaults are retained.

Batches whose ownership was already lost under 0.4.7 cannot be recovered; their
links stay until removed manually. Undo works normally for batches accepted from
0.4.8 on, and for older batches whose ownership was still intact.

## ICDB 0.4.7

Date: 13 October 2026

### Purpose

Imported pinouts previously matched exact part numbers and one specific 4000
family rule. LM2902 suffixes and L2902 variants were therefore absent from the
suggestions. This release adds general name-based review candidates without
creating automatic electrical-equivalence or family-alias permissions.

### Workflow

1. Extract into a new application folder. Keep the existing shared DATA folder.
2. Open Pinout manager → Match imported pinouts and choose Rescan.
3. Filter/find the source part. Inspect Match, Reason, package and the diagram.
4. Ctrl/Shift-select desired candidates and Accept selected, or Reject selected.
5. Use the existing accepted-batch history to undo additions when needed.

All broad suggestions start unselected. Apply exact matches uses only visible
unambiguous exact rows. Accepting one candidate does not authorize future variants.

### Matching rules

- Exact names and existing generic-4xxx rules retain their identities and priority.
- New rule `prefix-suffix-v1` parses every numeric run, retaining leading zeros,
  alphabetic prefixes, internal letters/separators, and suffixes.
- Suffix variants have identical numeric runs, prefixes and internal text; only
  the tail differs. Example: LM2902 → LM2902N, ABC123 → ABC123/N.
- Nearby prefix variants have identical numeric runs/internal text and prefixes
  that differ by one insertion/deletion/substitution or where one ends with the
  other. Suffixes may differ too. Example: LM2902 → L2902KV.
- Other names sharing the complete numeric-run sequence appear last as Shared
  number only. This includes LTC2902/NJM2902/PCM2902 from an LM2902 source and
  internal-family changes such as 74HC14 → 74HCT14. These are weak suggestions,
  not verified equivalent parts.
- Prefix/shared-number suggestions require at least three digits in total to
  limit noise from short codes such as R1/C1. Same-base suffix suggestions can
  use shorter numeric identifiers.
- Every numeric run must match exactly: LM29020, LM02902 and LM2902-1 are excluded
  from LM2902 suggestions. 74HC140 is excluded from 74HC14. Numeric suffixes are
  deliberately not discarded.
- Supported broad-name characters: ASCII letters/digits, underscore, dot, slash,
  plus and hyphen. Internal spaces or other characters fall back to exact/manual
  matching. No separator is silently deleted.
- Ranking expresses name similarity only. Default sorting is tier, source,
  target, manufacturer and package, with deterministic identity tie-breakers.

The existing 4000 rule can match MC1/HD1 prefixes separately from this generic
numeric parser. A target proposed by exact, 4000 or saved manual rules is not
also listed under the broad rule. Existing rejection/manual-decision keys and
unchanged evidence remain usable. The legacy 4000 regression tests explicitly
check that rule; unrelated names may now appear separately at the lowest tier.

### Preserved behavior

Manufacturer conflicts, missing/modified SVGs, conflicting generated pin data,
package/count conflicts and stale reviewed rows retain their existing checks.
Batch writes remain transactional. Reimport does not duplicate associations.
Existing references/defaults are retained. Undo removes only still-owned batch
additions and keeps manually changed/recreated links.

No schema or bundle-format change is required. No user database or full KiCad
library is included. Existing source recovery supports rescanning old imports;
missing retained bundles still require reimport. Package labels describe the
reference choice, not recognition of a physical package.

No ICOCR, ICPin, OCR-processing, source-storage or SVG-renderer changes are part
of this release. Compact ICOCR source display remains planned for ICOCR 0.8.8.

## ICDB 0.4.6 — Reviewed imported-pinout matching

### Use

1. Extract this release into a new application folder. Keep the existing shared DATA folder and select it in ICDB. No replacement database is included.
2. Open **Pinout manager → Match imported pinouts**.
3. Existing 0.4.5 imports recover their original device records from retained ICPin bundles. If a retained bundle is missing, the status identifies the catalog and requests reimport of the original bundle.
4. Review the source, proposed database target, diagram, package, pin count, rule, source notes and link status. Use Ctrl/Shift to select a batch. No family candidate is selected automatically.
5. **Accept selected** adds only selected associations. **Reject selected** retains decisions across rescans/reimports with unchanged evidence. Select the Rejected filter to revisit a decision.
6. **Apply exact matches** applies only currently visible, unambiguous exact candidates. The search and status filters constrain this action.
7. **Choose manual target** adds a specific database target for review; it does not immediately link it or establish a broad alias rule.
8. Use **Rescan** after database or bundle changes. Choose an accepted batch in the history and use **Undo selected batch** to remove only its still-owned additions.

### Matching rules

The initial rule is versioned `4000-prefix-v1`. Generic four-digit 4xxx source names propose database names with CD, HEF, HCF, MC1 or HD1 prefixes and alphabetic suffixes. Full target names and suffixes remain visible. Numeric coincidence alone is insufficient: AD4001, 27C4001, LM4001 and TC4001BP are not included by this rule. No expanded family rules or bulk alias permissions are inferred from acceptance.

Exact matching ignores only letter case and outer whitespace. Manufacturer conflict, changed/missing diagram, source/package mismatch, or conflicting known generated pin assignments blocks application. Target physical packages generally are not recorded in ICDB; the package shown is a reference choice, not physical package identification.

Unresolved ICPin records remain visible with a missing-diagram explanation. No NC pins or physical package counts are inferred or changed by this update.

### Persistence and undo

New additive tables retain source records and notes, decisions with target IDs and evidence/rule revisions, and accepted-operation ownership. Scans and writes run in background workers against the active database. Reviewed rows are revalidated under an immediate SQLite transaction; any stale row or failure rolls back the whole batch.

Existing assets, associations and defaults remain intact. A new link becomes default only when a device has no references. Reimports and repeated matching do not duplicate links. Manual accepted/rejected targets remain available across rescans. Changed evidence returns rejected candidates for review.

Editing or deleting a matcher-created link invalidates that link's undo ownership, including changes made through other database writers. Undo retains older, manual, edited and subsequently recreated links. If undo removes a newly created default and other references remain, one remaining reference becomes default.

The same pinout_assets/pinout_links interface is retained for ICOCR. ICOCR package selection is unchanged. No ICOCR source or recognition changes are included.

## ICDB 0.4.5 — ICPin batch import

In the pinout manager, choose **Import ICPin bundle** and select the
`.icpin.zip` exported by ICPin 0.1.5. Review the Pinouts and Device matches tabs,
then click **Import ready items**. Import runs in the background.

### Matching and reimport rules

- Part numbers match exactly apart from outer whitespace and letter case.
  Suffixes, punctuation and internal spaces are retained. No family guessing.
- A supplied manufacturer must match. A single matching part with a blank ICDB
  manufacturer can be proposed; the preview explicitly labels this case.
- Unknown / Unspecified (KiCad) manufacturers require one unique part match.
  Ambiguities, manufacturer mismatches, duplicates and missing parts are listed
  and skipped. No components are created automatically.
- Ready associations are added. Already linked associations, existing labels,
  manually chosen defaults and manual images are retained. The first reference
  for a device becomes its default only if it has no previous references.
- Edited SVGs update their stable asset IDs, so every device sharing that mapping
  sees the new revision. Existing associations are never removed by reimport.
- Package/count changes under an existing pinout ID are conflicts: add a new
  mapping in ICPin. Conflicting pinouts and their new associations are skipped.
- A changed catalogue between preview and import requires reopening the preview.

Pinouts without a matching device can still be imported for later manual linking.
Fix skipped device rows in ICPin and export/reimport, or attach the imported
image to catalogue devices using the existing ICDB controls.

### Storage and editing

The same DATA folder and database are used. Two additive tables record generated
pinout identities and their source bundles. SVGs and source revisions are kept
in DATA/pinouts/icpin. Folder discovery excludes this subtree so older generated
revisions do not reappear as manually imported images.

Original bundles (including editable catalog data and source notes) are retained
under DATA/pinouts/icpin/<catalog ID>/sources. Open your original exported bundle
in ICPin to edit. Keep using that catalog identity on subsequent exports.
The source SVG remains vector data; PNG is not an export format.

### Upgrade

Extract into a new folder and select the existing shared DATA folder. Use
requirements.txt as with 0.4.4. No new dependency is added in this release.
ICOCR 0.8.7 needs no update; its existing package/reference selector reads the
new associations. Package recognition and additional package renderers are
outside this release.

## ICDB 0.4.4 — Stage 1

- Import and preview static SVG pinouts alongside JPG, PNG, BMP and WebP.
- Folder scans discover SVG files; original SVG bytes remain in DATA/pinouts.
- Import/scan workers use the database already opened by ICDB. Both legacy
  DATA/components.sqlite and DATA/db/components.sqlite are supported.
- Existing asset deduplication, device associations, packages and defaults remain intact.

### Upgrade and use

Extract into a new folder and keep your existing DATA folder. Select that same
DATA folder in both ICDB and ICOCR. Do not replace your database.
Run `py -3 -m pip install -r requirements.txt`, then `run_ICDB_windows.bat`.
Python 3.10+ is required for the SVG dependency.

In the pinout manager, import an ICPin SVG and link it to a component with its
package and pin count. ICOCR 0.8.7 reads that association from the shared database.
No bundle export is required for this shared-DATA workflow.

SVG previews use resvg_py 0.5.0 and are rasterised only for the Tk display,
with a maximum 2400-pixel long edge. The stored SVG remains unchanged.
Supported SVGs are static, self-contained vectors with inline attributes/styles;
external resources, scripts, embedded images and style blocks are rejected.

## ICDB 0.4.3

Supports DATA/db/components.sqlite and legacy DATA/components.sqlite. Removes the dependency on an absent seed database: an empty installation starts a valid empty database. Preserves the independently supplied database and pinout files. Adds the provided icon, a frozen entry point/self-test and shared DATA lease. Windows packaging and data-update tooling are in the parent build kit.

## ICDB 0.4.2 — with ICOCR 0.8.4.7 UI update

### ICDB
- Edit all selected pinout associations in one dialog. Common values are populated; mixed fields stay unchanged unless checked or typed into. Clear a checked field to clear its value.
- Double-click a device association to open the editor. If the row is already part of a multiple selection, the editor applies to that selection.
- Set default applies to every selected device in one transaction. Selecting multiple associations for the same device is rejected: only one default per device is supported.
- Unlink selected removes every selected association while retaining shared images.
- Click any table heading to toggle ascending/descending sorting. Text is case-insensitive; numeric portions sort naturally (8, 16, 100). Sort is retained when refreshing tables.
- Search supports * (zero or more characters) and ? (one character), case-insensitively. Examples: 74HC*, *240*, 74HC??. Without wildcards, search remains a substring search. % and _ are literal characters.
- All matching records are displayed and sortable; the previous 500-result truncation is removed.
- Add device accepts part number, function/description and manufacturer/group. Empty part numbers and case-insensitive duplicates for the same manufacturer are rejected.
- Delete selected devices requires confirmation with No as the default. Removes selected catalogue records, their evidence entries and pinout links. Source archives and shared image files remain. Review entries cannot be deleted through this action.
- Batch association edits are atomic: a duplicate package association or invalid pin count leaves the whole selection unchanged.

### ICOCR
- Database and Documentation are combined into Database & Documentation.
- Log clicked readings is in that Settings tab; its explanatory help paragraph is removed.
- Open image folder sits next to Capture image and opens DATA/captures, creating the folder if needed.
- Pinout refresh and index status are moved to the combined database tab.

## ICDB 0.4.1

- Shared DATA folder selection used by both ICDB and ICOCR.
- Database at DATA/components.sqlite; images at DATA/pinouts.
- Automatic discovery now scans only DATA/pinouts, registering local files in place.
- Removed watched-folder selection and legacy mapping/reference-bundle UI controls.
- Existing catalogue and image associations are retained when copied together.
- Fresh catalogues are seeded only when DATA has no database.
- Manual catalogue entry editing is still planned; this release focuses on shared storage.

## ICDB 0.4

- New Pinout manager with image preview, shared caption/source, and device links.
- One image can serve many devices and packages; a device can have several images.
- Bulk assignment from Ctrl/Shift selections in the main catalogue.
- Package, optional pin count and label, default selection and safe unlinking.
- Background folder discovery with reviewed exact filename suggestions.
- Explicit legacy ICOCR JSON mapping import and portable reference bundle export.
- Images copied once by content hash; original catalogue/evidence preserved.
- Pillow added for image decoding; launcher now uses the default Python 3.
- Corrected a stale supplied test to assert ICDB 0.3's existing duplicate-skipping
  policy. CSV import behavior itself has not changed.

ICOCR integration is deferred to 0.8.4.5 after interface feedback. The new bundle
is not a drop-in replacement for ICOCR 0.8.4.4's diagram cache or configuration.
No ICOCR or ICBENCH code is part of this release.

### Reference contract for subsequent integration

SQLite uses pinout_assets and pinout_links with indexed foreign keys. A partial
unique index enforces one default per component. The export manifest has
schema_version=1, assets (ID/hash/relative path/original name/caption/source) and
links (component ID, part number, manufacturer, asset ID, package, pin_count,
label, is_default). The reader should match explicit catalogue identity, never
infer equivalence from an asset filename. Part numbers and manufacturer fields
are included because numeric component IDs are local to this catalogue.

Next ICOCR stage: resolve these links, load only the chosen image, display a
package/reference dropdown, remember session choices, and retain existing folder
discovery as a source of candidate references. Decide final integration details
after testing ICDB's interface.
