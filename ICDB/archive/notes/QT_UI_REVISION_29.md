# ICDB UI Revision 29 — simplified SVG maintenance controls

Based on Revision 28. Settings → Tools now has two explicit actions:

- **Publish pinouts**: incrementally updates eligible accepted SVGs and component links for ICOCR, preserving unchanged files.
- **Rebuild all SVGs**: forces SVG regeneration for all eligible accepted pinouts and refreshes links.

Removed the Force regeneration checkbox and its persisted preference control. Both actions retain explicit confirmation, unsaved-change protection, background execution, and publication results. New assigned pinouts still publish automatically after Save. No backend or schema changes.
