# ICDB PySide6 — UI Revision 6

Based on Revision 5. No database schema, import, matching, or pinout publication logic changes.

## Changes

- Pinout Library table now sorts by clicking Title, Package, or Devices column headers. Devices uses numeric sorting, not lexicographic string sorting. Sorting and selected definition are preserved when results are refreshed.
- Library search box and pinout filter are inside the left **LIBRARY** section.
- Combined the previous Properties and Pins tabs into a permanently visible **Editor** tab, with resizable **Properties above Pins**. **Groups** remains a separate tab. Vertical divider position is remembered.
- All current Qt tables (Components, Pinout Library, pins, accepted devices, and Add devices dialog) fill unused horizontal space with their last column. Other columns remain manually resizable.
- SVG rasterization was previously at the SVG's natural dimensions. The renderer now supersamples small SVGs up to six times their native resolution (longest dimension limited to 2400 pixels), with antialiasing. This reduces pixelation in normal zoom usage. At extreme magnification the raster preview is still limited by its backing resolution. Original SVG files are unchanged.

## Known limitations

- Real Qt GUI testing was not possible in the development environment (PySide6 is not installed). Python syntax and static invariants were checked.
- Pinout preview uses QImage/QPixmap rather than continuous vector rendering. A future SVG-backed QGraphicsItem would provide unlimited sharp zoom but requires implementing the optional dark-mode inversion in a vector-safe manner.
- Group membership operations retain existing immediate-write behaviour. General Revert does not undo them.
