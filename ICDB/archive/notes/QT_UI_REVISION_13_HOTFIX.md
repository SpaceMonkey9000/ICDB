# Revision 13 hotfix: floating Save/Revert windows

The Pinout Library created obsolete Save and Revert QPushButtons without parents or placement in any layout. `_set_mode()` called `setVisible(True)` on those widgets, causing separate top-level windows on Windows. Removed those unused controls and their visibility calls. The global Save and Revert controls beside Settings remain unchanged and connected to the same editor operations.
