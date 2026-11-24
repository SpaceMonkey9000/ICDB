# Native SVG viewer prototype

Changes from the uploaded ICDB source:

- `ui/pinout_view.py`: display generated SVG bytes with `QGraphicsSvgItem` and `QSvgRenderer` rather than rasterizing them into `QImage` first. Disable the SVG item's raster cache so high-zoom content is rendered as vectors. Retain raster images for reference photos and retain fit/wheel/double-click navigation. SVG dark-mode inversion uses an in-memory color transformation; stored SVGs are unchanged.
- `ui/components_page.py`, `ui/pinout_library/page.py`: pass SVG bytes to the vector viewer.
- `pinout.py`: monochrome technical drawing treatment; Segoe UI typography with Arial fallback, semibold labels, heavier package edges, muted lead bend lines, and light-grey fills on selected body outlines. Geometry and pins are unchanged. Renderer version bumped from 0.8.3 to 0.8.4 so published SVG caches can be rebuilt.
- `icdb_qt.py`: set the Qt application and main window icon using the existing `ICDB.ico` file.

## Test/build

Install dependencies on Windows with `pip install -r requirements-qt.txt` and run `python icdb_qt.py` using the existing project setup.

The title-bar icon is loaded from `ICDB.ico` beside `icdb_qt.py` in source mode. For PyInstaller builds, **both** `--icon ICDB.ico` (EXE icon) and `--add-data "ICDB.ico;."` (Qt runtime resource) are required. For an existing spec file, add `('ICDB.ico', '.')` to `datas` and set the EXE `icon` option. The project ZIP does not contain a PyInstaller spec or packaging command, so the build configuration has not been changed here.

`python -m compileall` and the DFN SVG test passed in the edit environment. Generated SVGs for SOIC-8, TSSOP-16, QFN-16, QFP-32, and DFN-8 parsed as XML. PySide6 is not installed here; actual display, zoom, title-bar behavior, and Windows packaging must be verified in a Qt runtime.

## Scope

This is the first viewer/styling implementation only. Real font-metric layout, adaptive strokes at very small zoom, and separate technical/compact/overlay profiles are not implemented. Existing SVGs in the published library require regeneration to receive the updated style.
