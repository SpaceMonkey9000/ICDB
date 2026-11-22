"""Runs one background database job at a time and reports its result."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QMessageBox,
)
from shared_data import database_file
from ui.jobs import DatabaseJob


class JobRunnerMixin:
    """Background job handling. Mixed into MainWindow."""

    JOB_LABELS = {'import_preview': 'Reading import files',
                  'json_export': 'Exporting JSON', 'publish': 'Publishing pinouts', 'rebuild': 'Rebuilding SVGs'}

    def can_run_database_job(self, operation, payload=None):
        csv_only = operation == 'import_preview' and all((entry['kind'] if isinstance(entry, dict) else Path(entry).suffix.lower()) == '.csv'
                       for entry in payload)
        if not csv_only and (self.library_page.has_pending() or self.component_stage.changed):
            QMessageBox.warning(self, 'Unsaved changes',
                'Save or Revert staged edits before running a database operation.')
            return False
        if self.job is not None:
            QMessageBox.information(self, 'Operation in progress', 'Finish the current operation first.')
            return False
        return True

    def run_job(self, operation, payload, callback, on_error=None):
        """Start a worker job. Returns False when it was refused (nothing started)."""
        if not self.can_run_database_job(operation, payload):
            return False
        self.job_done = callback
        self.job_error = on_error
        self.job = DatabaseJob(str(database_file(self.data)), self.data, operation, payload)
        self.job.progress.connect(self._job_progress)
        self.job.succeeded.connect(self._job_succeeded)
        self.job.failed.connect(self._job_failed)
        self.job.finished.connect(self._job_finished)
        self.statusBar().showMessage(self.JOB_LABELS.get(operation, operation) + '…')
        # Block edits while a worker holds (or may take) the database write lock.
        self.tabs.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        self.job.start()
        return True

    def _job_progress(self, done, total):
        if self.job is not None and total:
            label = self.JOB_LABELS.get(self.job.operation, self.job.operation)
            self.statusBar().showMessage(f'{label} {done:,} / {total:,}…')

    def _job_succeeded(self, result):
        try:
            self.statusBar().showMessage('Operation complete')
            self.job_done(result)
        except Exception as exc:
            QMessageBox.critical(self, 'Operation result', str(exc))

    def _job_failed(self, message):
        self.statusBar().showMessage('Operation failed')
        if self.job_error is not None:
            try:
                self.job_error(message)
            except Exception:
                pass
        QMessageBox.critical(self, 'Database operation failed', message)

    def _job_finished(self):
        job, self.job = self.job, None
        self.job_done = None
        self.job_error = None
        if job is not None:
            # finished is emitted just before the thread exits; wait before releasing it.
            job.wait()
            job.deleteLater()
        QApplication.restoreOverrideCursor()
        self.tabs.setEnabled(True)
        if getattr(self, '_publish_retry', False):
            self._publish_retry = False
            QTimer.singleShot(0, self._publish_after_new_pinout)

    def publish_complete(self, result, title):
        self.refresh()
        self.library_page.refresh_members()
        lines = []
        if 'rendered' in result:  # only reported by a forced rebuild
            lines.append(f"Rendered: {result['rendered']}")
        lines += [f"Updated links: {result.get('updated', 0)}",
                  f"Unchanged: {result.get('unchanged', 0)}",
                  f"Removed: {result.get('removed', 0)}"]
        skipped = result.get('skipped', [])
        self._publish_targets = set()  # a full publish covers anything still queued
        self.set_unpublished(bool(skipped))
        self.message(', '.join(lines) + (f', {len(skipped)} skipped' if skipped else ''))
        summary = '\n'.join(lines)
        if skipped:
            summary += f'\n\nSkipped ({len(skipped)}):\n' + '\n'.join(map(str, skipped[:40]))
            if len(skipped) > 40:
                summary += f'\n… and {len(skipped) - 40} more'
            QMessageBox.warning(self, title, summary)
        else:
            QMessageBox.information(self, title, summary)
