# Revision 25 — Automatic publication of new pinouts

- After a successful atomic Save containing a new pinout assigned to one or more devices, ICDB queues incremental publication to ICOCR in a background worker.
- Publication creates the generated SVG file and pinout link used by ICOCR, without forcing regeneration of unchanged diagrams.
- Publication starts **after** SQLite commit and recovery-draft cleanup. If the Save fails or is reverted, it never runs.
- A new definition without any assigned device is not published (there is no component to link).
- A publication problem is reported separately: the database save remains committed, and Settings → Tools → Publish accepted pinouts to ICOCR can retry it.
- Existing settings for forced SVG rebuilding and explicit publication remain available.
- No ICOCR code changes are required. ICOCR must reload its ICDB data before recognizing the new pinout link.

Tests: `test_auto_publish_pinout.py` includes a full SQLite publish/render/link test plus Qt-path tests (Qt tests skipped when PySide6 is unavailable).
