# Revision 21 — Assign a library pinout to a component opened from ICOCR

- In **Components**, below Source Evidence, click **Assign pinout**.
- Search native pinout definitions by title, package, or associated part numbers.
- Select a definition and confirm. ICDB opens that definition's **Groups** editor and stages the selected device as an accepted member.
- A component created through **ICOCR History → Add to ICDB** can be assigned before it is saved; its temporary component ID is resolved during the unified Save transaction.
- **View changes** displays the group addition. **Save** commits it; **Revert** discards it. Switching between pinouts preserves pending drafts.
- Existing assignments are not duplicated. Conflicting same-package assignments are rejected by the existing transaction validation on Save.
- This action links **existing native pinout definitions**. To create an entirely new definition, use **Pinout library → New** first; the current editor requires saving a new definition before assigning group members.
- Does not publish SVGs to ICOCR automatically: **Settings → Tools → Publish** or **Rebuild SVGs** remains a separate operation.
- No changes to ICOCR's source are required for the Open in ICDB handoff.

## Verification

- Source compiles; 23 headless tests passed and 10 Qt tests were skipped in the build environment (PySide6 not available).
- Added three offscreen Qt integration tests for saved devices, newly staged devices, and picker cancellation; these require Windows or a Python environment with PySide6.
