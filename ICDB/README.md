# ICDB 0.8.6-beta.1

ICDB is the component and pinout database for ICOCR. It holds the component catalogue
(part number, function, manufacturer), pinout definitions with their pin tables, and
the groups of components that share each pinout. It publishes pinout diagrams (SVG)
that ICOCR shows next to a recognised marking.

This is a beta. Please report problems together with the version in the window title
and the database version shown in the status bar.

## Install and start (Windows)

**Installer or portable build:** run the installer, or extract the portable zip and
start `ICDB.exe`. No Python is needed.

**From source:**

1. Install Python 3.11 (64-bit) with the Python Launcher.
2. Run `setup_qt_windows.bat` once. It creates `.venv-qt` and installs the
   requirements.
3. Start ICDB with `run_qt_windows.bat`.

ICDB opens an existing database; it never creates an empty one. If no database is
found, it says where it looked. Point it at your shared DATA folder (see below), or
install a DATA pack first.

## Using ICDB

ICDB has three tabs: **Components**, **Pinout library** and **Import**. Edits on the
first two are staged: nothing is written to the database until you press **Save** at
the top right. **Revert** discards everything staged, and **View changes** lists it.
See [docs/USER_GUIDE.md](docs/USER_GUIDE.md) for each tab.

New pinouts assigned to devices are published to ICOCR automatically after Save.
**Settings → Tools** has **Publish pinouts** and **Rebuild all SVGs** for everything
else.

## Where things are kept

| What | Where |
| --- | --- |
| Shared DATA folder | `ICLENS_DATA` if set; else the folder saved in Settings → Data; else `%LOCALAPPDATA%\ICSuite\DATA` (installed) or a `DATA` folder next to the ICDB folder (source) |
| Database | `DATA\db\components.sqlite` (or `DATA\components.sqlite` in older layouts) |
| Published pinout diagrams | `DATA\pinouts` |
| Database backups before migrations | `DATA\backups` |
| Unsaved-work recovery drafts | Your user application data folder; the path is shown if a draft cannot be restored |
| Window and theme settings | Qt settings for `ICSuite / ICDB-PySide6` |

While ICDB runs it holds a shared lock on the DATA folder. ICDB and ICOCR can run
together; a DATA updater cannot run until both are closed.

Start with another DATA folder for one session only:

```bat
run_qt_windows.bat --data "D:\ICSuite\DATA"
```

## Database version

The status bar shows the database's own version, separate from the application
version. A DATA pack stamps its build date (for example `20261110`), and every saved
content change adds a revision suffix (`20261110-r1`, `-r2`, …). A database without a
known origin shows **Unversioned**. Details are in
[docs/DEVELOPER.md](docs/DEVELOPER.md#database-version).

## Command line

| Option | Effect |
| --- | --- |
| `--data PATH` | Use this DATA folder for this session without saving it |
| `--open-part PART` | Select an exact part number (used by ICOCR **Open in ICDB**) |
| `--add-part PART` | Stage a new component (used by ICOCR **Add to ICDB**) |
| `--self-test [--report FILE]` | Open the window against temporary data, close it and report success as JSON |

## Documentation

- [docs/USER_GUIDE.md](docs/USER_GUIDE.md): the tabs, editing, saving and publishing
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md): start-up, DATA, recovery and publishing problems
- [docs/DEVELOPER.md](docs/DEVELOPER.md): code layout, tests, the DATA contract with ICOCR and design decisions
- [CHANGELOG.md](CHANGELOG.md): changes per release

## Known issues in this beta

- ICDB does not write a log file. Errors are shown in dialogs only.
- Recovery drafts are stored under the program's name, so drafts made from source
  are not found by the installed exe and the other way round.
