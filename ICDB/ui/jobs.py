"""Background database jobs on their own SQLite connection."""
from PySide6.QtCore import QThread, Signal
from builder import connect
from pinouts import Pinouts
from pin_library import Library
from component_json import export_batch
from import_batch import preview_files


class DatabaseJob(QThread):
    """Run potentially long imports/rebuilds with a private SQLite connection."""
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)  # done, total (queued to the UI thread)

    def __init__(self, path, data, operation, payload=None):
        super().__init__()
        self.path, self.data = path, data
        self.operation, self.payload = operation, payload

    def run(self):
        db = None
        try:
            if self.operation in ('import_preview', 'json_export'):
                db = connect(self.path)
                library = Library(Pinouts(db, self.data))
                if self.operation == 'import_preview':
                    result = preview_files(library, self.payload, self.progress.emit)
                else:
                    result = export_batch(library, *self.payload)
                self.succeeded.emit(result)
            elif self.operation in ('rebuild', 'publish'):
                db = connect(self.path)
                # payload: None for everything, or {'definition_ids': [...]} after Save.
                ids = (self.payload or {}).get('definition_ids')
                result = Library(Pinouts(db, self.data)).publish(
                    force=self.operation == 'rebuild', definition_ids=ids,
                    progress=lambda done, total: self.progress.emit(done, total))
                self.succeeded.emit(result)
            else:
                raise ValueError(f'Unknown database operation: {self.operation}')
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')
        finally:
            if db is not None:
                db.close()
