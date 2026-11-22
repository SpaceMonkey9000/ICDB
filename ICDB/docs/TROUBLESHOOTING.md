# ICDB troubleshooting

## ICDB does not start

**"Create ICDB database?"** ICDB could not find `db\components.sqlite` or the
legacy `components.sqlite` in the selected DATA folder. Choose **Yes** to create
an empty database at the displayed path. Choose **No** to exit. To open an
existing database in a different folder, start ICDB with
`run_qt_windows.bat --data "D:\ICSuite\DATA"`.

**"DATA folder setting file is unreadable" or "Invalid absolute DATA folder setting".** The
saved DATA location is damaged or not a full path. Delete the file named in the
message, or fix it so it reads `{"data_folder": "D:\\ICSuite\\DATA"}`, then restart.

**"Close ICOCR, ICDB and any DATA updater, then retry".** A DATA updater holds the
folder. Wait for it to finish, or close it.

**From source: "Run setup_qt_windows.bat first".** The `.venv-qt` environment is
missing. Run `setup_qt_windows.bat` with Python 3.11 (64-bit) installed.

## ICDB uses a different DATA folder than ICOCR

Both programs read the same saved setting, so a folder chosen in either one applies
to both after a restart. The order is: `ICLENS_DATA`, then
`%LOCALAPPDATA%\ICSuite\data_location.json`, then the older
`%LOCALAPPDATA%\IC_Tools\data_location.json`, then the default. Check whether
`ICLENS_DATA` is set for only one of them.

## Save fails

Save writes everything in one transaction. If it fails, nothing is written and your
staged changes are kept. The message says why. Common reasons:

- Another ICDB window, or another user, changed the same pinout or group since you
  loaded it. Revert, then make the change again.
- A component would get two different pinouts for the same package.
- The pin table is invalid, for example a duplicate pin number.

## A recovery draft was not restored

A draft is only restored if the pinouts and groups it touches are unchanged in the
database. Otherwise ICDB keeps the draft file and shows its path. Open it in a text
editor to see what was staged, then make the changes again.

## ICOCR does not show a changed pinout

1. Make sure the change is saved (no **Unsaved changes** label).
2. Run **Settings → Tools → Publish pinouts**. New pinouts with devices publish
   automatically after Save; edits to existing ones need Publish.
3. In ICOCR, use **Settings → Tools → Reload database**.

If a publish fails, the earlier diagrams and links stay in place. Fix the reported
problem and publish again.

## Import refuses a file

- The file must be UTF-8 with the header `part_number,description` (or
  `part_number,function`).
- Save or revert staged changes first.
- A file that changed after the preview is refused; choose it again.

## Reporting a problem

Include the version from the window title, the database version from the status
bar, what you did and the full error message. ICDB does not write a log file yet.
