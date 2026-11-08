# ICDB 0.8.3-RC1 deployment changes

The database browser already used the same DATA defaults and db/components.sqlite
layout as ICOCR. No standalone ICDB settings JSON existed to consolidate.

Both programs now share the same path resolver. New folder selections write
%LOCALAPPDATA%\ICSuite\data_location.json; the old IC_Tools location remains a read-only
fallback. ICLENS_DATA remains the highest-priority explicit override. Existing root
components.sqlite files remain supported. Saved folder paths must be absolute; UTF-8
BOMs from Windows text editors are accepted.

Pinout/library settings remain in SQLite. Application updates do not replace the
catalogue. Use the separate ICSuite DATA installer for a prepared catalogue, generated
SVGs, models and default rules. Database replacement is optional and creates a backup.
Both included application versions must be installed before switching away from the
legacy saved location; older ICOCR versions do not read the new ICSuite preference.

Source execution defaults to sibling DATA. Installed executables default to
%LOCALAPPDATA%\ICSuite\DATA. Choosing a folder requires restarting both applications
and does not move existing data.
