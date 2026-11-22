"""The application-wide staged session: Save, Revert, View changes and crash recovery."""
import copy
import json
import os
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QVBoxLayout, QLabel, QPlainTextEdit, QMessageBox, QDialog, QDialogButtonBox,
)
from builder import import_file
from import_batch import PUBLISH_ACTIONS, plan_file
from component_json import check_preview, plan_batch
from qt_component_csv import preview_component_csv
from pin_library import package_label, signature, validate_data
from library_queries import group_members
from qt_draft_store import write_draft, read_draft, delete_draft, draft_is_current
from qt_component_draft import ComponentDraft
from qt_pin_changes import summarize_pin_changes


class SessionMixin:
    """Staged changes, the single Save transaction and recovery drafts. Mixed into MainWindow."""

    def component_changed(self):
        self.update_draft_ui()
        if self.component_stage.changed:
            self.component_draft_timer.start()
            self.message('Component changes staged — Save or Revert to finish.')
        else:
            self.component_draft_timer.stop()
            if self.save_component_draft():
                self.message('No staged component changes.')

    def stage_import(self, kind, payload, rows):
        if self.component_stage.pending_import:
            raise ValueError('Save or Revert the staged import before staging another batch.')
        self.component_stage.pending_import = {'kind': kind, 'payload': payload, 'rows': rows}
        self.component_changed()

    def apply_import_locked(self):
        staged = self.component_stage.pending_import
        if not staged:
            return False
        if staged['kind'] == 'files':
            publish = False
            for entry in staged['payload']:
                result = plan_file(self.library, entry, replay=True)
                publish |= any(row[2] in PUBLISH_ACTIONS for row in result['rows'])
            return publish
        if staged['kind'] == 'json':
            rows = plan_batch(self.library, staged['payload'], apply=True)
            check_preview(rows, staged['rows'])
            return any(action in ('New assignment', 'Set default preference') for _, _, action, _ in rows)
        path, digest = staged['payload']
        preview = preview_component_csv(self.db, path)
        check_preview(preview['rows'], staged['rows'])
        if preview['sha256'] != digest or preview['already_imported']:
            raise ValueError('CSV file or import history changed since preview.')
        import_file(self.db, path, expected_sha256=digest, locked=True)
        return False

    @staticmethod
    def _preserve_draft_file(path):
        """Move a kept recovery draft aside so this session can journal to its path.
        The newest preserved copy is offered at the next start (see _recovery_file)."""
        backup = path.with_name(path.stem + f'.preserved-{int(time.time()*1000)}.json')
        os.replace(path, backup)
        return backup

    @staticmethod
    def _recovery_file(path):
        """The draft to offer at start: the current journal, else the newest kept copy."""
        if path.exists():
            return path
        kept = sorted(path.parent.glob(path.stem + '.preserved-*.json'),
                      key=lambda item: item.name, reverse=True) if path.parent.is_dir() else []
        return kept[0] if kept else None

    def save_component_draft(self):
        try:
            if not self.component_stage.changed:
                self.clear_component_draft()
                return True
            if self._protect_component_draft and self.component_draft_path.exists():
                # A draft the user chose to keep must not be overwritten by this session.
                self._preserve_draft_file(self.component_draft_path)
            self._protect_component_draft = False
            write_draft(self.component_draft_path, {'new': True, 'definition_id': None,
                        'raw': self.component_stage.payload(), 'base_members': [],
                        'draft_members': [], 'kind': 'components'})
            return True
        except Exception as exc:
            self.message(f'Component recovery draft could not be saved: {exc}')
            return False

    def clear_component_draft(self):
        """Remove this session's component journal; never a draft the user kept."""
        if self._component_recovery_pending or self._protect_component_draft:
            return
        try:
            delete_draft(self.component_draft_path)
        except OSError as exc:
            self.message(f'Could not remove component recovery draft: {exc}')

    def offer_recovery(self):
        if getattr(self, '_closed', False):
            return  # queued at start-up, but the window closed (and its database) first
        try:
            self.offer_session_recovery()
        finally:
            self._startup_recovery_pending = False
            self._component_recovery_pending = False
            if self.requested_alias:
                QTimer.singleShot(0, lambda: self.stage_alias(*self.requested_alias))
            elif self.requested_part:
                QTimer.singleShot(0, self.navigate_requested_part)
            elif self.requested_add_part:
                QTimer.singleShot(0, self.navigate_requested_add)

    def _check_pinout_journal(self, journal):
        """Return (drafts, deletions) or raise ValueError if the database moved on."""
        drafts = journal.get('drafts') if journal.get('kind') == 'pinout_session' else {
            ('new:legacy' if journal['new'] else str(journal['definition_id'])): journal}
        deletions = journal.get('deletions', {}) if journal.get('kind') == 'pinout_session' else {}
        for key, deletion in deletions.items():
            row, _ = self.library.get(int(deletion['definition_id']))
            members = {r['component_id'] for r in group_members(self.db, int(deletion['definition_id']))}
            if row['revision'] != deletion['revision'] or members != set(deletion['members']):
                raise ValueError(f'{key}: pinout to delete changed externally')
        for key, draft in drafts.items():
            if not isinstance(draft, dict) or 'raw' not in draft:
                raise ValueError(f'{key}: unreadable draft entry')
            if draft['new']:
                valid = draft_is_current(draft, None, set())
            else:
                row, _ = self.library.get(int(draft['definition_id']))
                members = {r['component_id'] for r in group_members(self.db, int(draft['definition_id']))}
                valid = draft_is_current(draft, row['revision'], members)
            if not valid:
                raise ValueError(f'{key}: saved database revision or membership changed')
        return drafts, deletions

    def offer_session_recovery(self):
        """One decision for both journals. Restoring pinout drafts without the unsaved
        components their groups refer to (or the reverse) used to leave Save failing."""
        pinout_file = self._recovery_file(self.draft_path)
        component_file = self._recovery_file(self.component_draft_path)
        if pinout_file is None and component_file is None:
            return
        problems = []
        pinout = component = None  # restorable content
        pinout_found = component_found = False
        if pinout_file is not None:
            try:
                journal = read_draft(pinout_file)
                if journal is not None:
                    pinout_found = True
                    pinout = self._check_pinout_journal(journal)
            except Exception as exc:
                pinout_found = True
                problems.append(f'Pinout drafts cannot be restored: {exc}')
        if component_file is not None:
            try:
                draft = read_draft(component_file)
                if draft is not None:
                    component_found = True
                    recovered = ComponentDraft()
                    recovered.restore(self.db, draft['raw'])
                    component = recovered
            except Exception as exc:
                component_found = True
                problems.append(f'Component changes cannot be restored (the database changed): {exc}')
        if not (pinout_found or component_found):
            return
        found = []
        if pinout is not None:
            drafts, deletions = pinout
            found.append(f'{len(drafts)} pinout draft(s) and {len(deletions)} staged pinout deletion(s)')
        if component is not None:
            count = (len(component.added) + len(component.edits) + len(component.deleted)
                     + len(component.aliases) + (1 if component.pending_import else 0))
            found.append(f'{count} component change(s)' + (' including a staged import'
                                                           if component.pending_import else ''))
        files = [path for path in (pinout_file, component_file) if path is not None]
        details = list(problems)
        if problems:
            details.append('Drafts that cannot be restored are kept unless you choose Discard:\n'
                           + '\n'.join(map(str, files)))
        choice = self._ask_recovery(found, details)
        if choice == 'restore' and found:
            self._restore_recovered(pinout, pinout_file, component, component_file)
        elif choice == 'discard':
            for path in files:
                delete_draft(path)
        else:
            # Keep: neither file may be overwritten or deleted by this session.
            self._protect_existing_draft = pinout_file == self.draft_path
            self._protect_component_draft = component_file == self.component_draft_path

    def _ask_recovery(self, found, details):
        """Return 'restore', 'discard' or 'keep'."""
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Recover unsaved work')
        dialog.setText('Unsaved work from a previous session was found'
                       + (': ' + ' and '.join(found) + '.' if found else '.'))
        if details:
            dialog.setInformativeText('\n\n'.join(details))
        restore = dialog.addButton('Restore', QMessageBox.ButtonRole.AcceptRole) if found else None
        discard = dialog.addButton('Discard', QMessageBox.ButtonRole.DestructiveRole)
        dialog.addButton('Keep for later', QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        clicked = dialog.clickedButton()
        if restore is not None and clicked == restore:
            return 'restore'
        return 'discard' if clicked == discard else 'keep'

    def _restore_recovered(self, pinout, pinout_file, component, component_file):
        # Components first, so pinout groups can refer to restored unsaved components.
        if component is not None:
            self.component_stage = component
            if component.pending_import:
                self.import_page.restore_staged_import(component.pending_import)
            if component_file != self.component_draft_path:
                delete_draft(component_file)  # its content now lives in this session
            self._component_recovery_pending = False
            self.save_component_draft()
        elif component_file is not None:
            self._protect_component_draft = component_file == self.component_draft_path
        if pinout is not None:
            drafts, deletions = pinout
            page = self.library_page
            page.load_session(drafts, deletions)
            current = page.definition_id
            if current is not None and str(current) in drafts:
                page.restore_draft(page.pending_pinouts.pop(str(current)))
            if pinout_file != self.draft_path:
                delete_draft(pinout_file)
            self.save_draft()
            page.refresh()
        elif pinout_file is not None:
            self._protect_existing_draft = pinout_file == self.draft_path
        self.components.refresh()
        self.library_page.refresh_members()
        self._prune_orphan_group_members()
        self.update_draft_ui()

    def _prune_orphan_group_members(self):
        removed = self.library_page.prune_missing_members()
        if removed:
            QMessageBox.information(self, 'Recovered pinout groups',
                f'{removed} group assignment(s) referred to unsaved components that were not restored '
                'and have been removed from the staged pinout groups.')

    def pending_summary(self, capitalize=True):
        """'2 pinout draft(s), 1 pinout deletion(s) and component changes', listing only what exists."""
        parts = []
        drafts = len(self._all_pinout_drafts())
        deletions = len(self.library_page.pending_deletions)
        if drafts:
            parts.append(f'{drafts} pinout draft(s)')
        if deletions:
            parts.append(f'{deletions} pinout deletion(s)')
        if self.component_stage.changed:
            parts.append('component changes')
        if not parts:
            return 'No changes' if capitalize else 'no changes'
        text = ', '.join(parts[:-1]) + (' and ' if len(parts) > 1 else '') + parts[-1]
        return text[0].upper() + text[1:] if capitalize else text

    def _all_pinout_drafts(self):
        return self.library_page.session_payload()['drafts']

    def _pinout_data_from_draft(self, draft):
        raw = draft['raw']
        if draft['new']:
            data = {'device': '', 'package': '', 'count': 1, 'pins': []}
        else:
            _, data = self.library.get(int(draft['definition_id']))
            data = copy.deepcopy(data)
        data['device'] = str(raw['title']).strip()
        data['package'] = str(raw['package']).strip()
        data['source'] = str(raw['source']).strip()
        data['count'] = len(raw['pins'])
        if raw['pad_enabled']:
            data['exposed_pad'] = {'enabled': True, 'number': str(raw['pad_number']).strip(),
                                   'name': str(raw['pad_name']).strip(), 'role': raw['pad_role'],
                                   'description': ''}
        else:
            data.pop('exposed_pad', None)
        data['pins'] = []
        for line in raw['pins']:
            number = str(line[0]).strip()
            data['pins'].append({'number': int(number) if number.isdecimal() else number,
                                 'name': str(line[1]), 'role': str(line[2]),
                                 'description': str(line[3])})
        validate_data(data)
        return data

    def changes_text(self):
        lines = []
        stage = self.component_stage
        for alias in stage.aliases:
            action = 'Delete' if alias.get('remove') else 'Edit' if alias.get('before') else 'Add'
            # The identity was captured when the alias was staged; show the part as it is now.
            cid = alias['component_id']
            if cid in stage.added:
                part = stage.added[cid]['part_number'] + ' (new)'
            elif cid in stage.edits:
                part = stage.edits[cid]['after']['part_number']
            else:
                part = alias['identity'][0]
            lines.append(f"{action} alias {alias['marking']} → {part}")
        if stage.pending_import:
            batch = stage.pending_import
            lines.append(f'{batch["kind"].upper()} IMPORT')
            for row in batch['rows']:
                lines.append('  ' + ' | '.join(str(value) for value in row))
        for cid, row in sorted(stage.added.items()):
            lines += [f'COMPONENT + {row.get("part_number", "")} (new)',
                      f'  Description/function: {row.get("function", "")}']
        for cid, row in sorted(stage.edits.items()):
            lines.append(f'COMPONENT ~ #{cid} {row["before"].get("part_number", "")}')
            for key, old in row['before'].items():
                new = row['after'].get(key)
                if new != old:
                    lines.append(f'  {key}: {old!r} -> {new!r}')
        for cid, row in sorted(stage.deleted.items()):
            lines.append(f'COMPONENT - #{cid} {row.get("part_number", "")}')
        for key, deletion in sorted(self.library_page.pending_deletions.items()):
            lines.append(f'PINOUT - {deletion["name"]} ({deletion["package"]}) (delete on Save)')
        for key, draft in self._all_pinout_drafts().items():
            raw = draft['raw']
            lines += ['', f'PINOUT {"+" if draft["new"] else "~"} {raw["title"]} ({raw["package"]})']
            if draft['new']:
                lines.append(f'  New pinout, {len(raw["pins"])} pins')
            else:
                try:
                    _, base = self.library.get(int(draft['definition_id']))
                    for field, rawkey in [('device','title'),('package','package'),('source','source')]:
                        if str(base.get(field,'')) != str(raw[rawkey]):
                            lines.append(f'  {field}: {base.get(field, "")!r} -> {raw[rawkey]!r}')
                    # Pin-level summary shows changed fields only. Unified
                    # diff previously displayed most/all pins for one edit.
                    lines.extend('  ' + entry for entry in
                                 summarize_pin_changes(base.get('pins', []), raw['pins']))
                    oldpad = base.get('exposed_pad') or {}
                    newpad = {'enabled': raw['pad_enabled'], 'number': raw['pad_number'],
                              'name': raw['pad_name'], 'role': raw['pad_role']}
                    if bool(oldpad) != bool(raw['pad_enabled']) or (raw['pad_enabled'] and any(
                        str(oldpad.get(k,'')) != str(newpad[k]) for k in ('number','name','role'))):
                        lines.append(f'  Exposed pad: {oldpad} -> {newpad}')
                except Exception as exc:
                    lines.append(f'  Saved state unavailable: {exc}')
            added = set(draft['draft_members']) - set(draft['base_members'])
            removed = set(draft['base_members']) - set(draft['draft_members'])
            def member_label(cid):
                cid = int(cid)
                if cid < 0 and cid in stage.added:
                    return f"{stage.added[cid].get('part_number', '')} (new)"
                item = self.db.execute('SELECT part_number FROM components WHERE id=?', (cid,)).fetchone()
                return f'{item[0] if item else "Unknown"} (#{cid})'
            if added:
                lines.append('  Group additions: ' + ', '.join(member_label(cid) for cid in sorted(added)))
            if removed:
                lines.append('  Group removals: ' + ', '.join(member_label(cid) for cid in sorted(removed)))
        return '\n'.join(lines) if lines else 'No staged changes.'

    def review_changes(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Review staged changes')
        dialog.resize(940, 640)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('These changes are staged and have not been committed to ICDB.'))
        view = QPlainTextEdit(dialog)
        view.setReadOnly(True)
        view.setPlainText(self.changes_text())
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def confirm_save(self):
        while True:
            dlg = QMessageBox(self)
            dlg.setWindowTitle('Save staged changes')
            dlg.setText(f'Save {self.pending_summary(capitalize=False)}?')
            dlg.setInformativeText('All changes will be committed as one SQLite transaction.')
            save_btn = dlg.addButton('Save', QMessageBox.ButtonRole.AcceptRole)
            review_btn = dlg.addButton('View changes', QMessageBox.ButtonRole.ActionRole)
            dlg.addButton('Cancel', QMessageBox.ButtonRole.RejectRole)
            dlg.exec()
            if dlg.clickedButton() == review_btn:
                self.review_changes()
                continue
            return dlg.clickedButton() == save_btn

    def revert_all(self):
        if not (self.component_stage.changed or self.library_page.has_pending()):
            return
        if QMessageBox.question(self, 'Revert changes',
            f'Discard all staged changes ({self.pending_summary(capitalize=False)})?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        page = self.library_page
        page.pending_pinouts.clear()
        page.pending_deletions.clear()
        page.changed = False
        page.draft_timer.stop()
        self.clear_draft()
        page._new = False
        page._active_draft_key = None
        if page.definition_id is not None:
            try:
                page._reload_current()
            except Exception as exc:  # e.g. the pinout was deleted by another ICDB instance
                page.definition_id = None
                page.clear()
                self.message(f'Pinout could not be reloaded: {exc}')
        else:
            page.clear()
        if self.component_stage.pending_import:
            self.import_page.finish_staged_import(saved=False)
        self.component_stage.clear()
        self.component_draft_timer.stop()
        self.clear_component_draft()
        self.components.refresh()
        self.library_page.refresh()
        self.library_page.refresh_members()
        self.update_draft_ui()

    def _confirm_matching_pinouts(self, prepared, deletions):
        reuse = {}
        edited = {draft['definition_id']: signature(data) for _, draft, data in prepared if not draft['new']}
        for key, draft, data in prepared:
            if not draft['new'] or not (set(draft['draft_members']) - self.component_stage.deleted.keys()):
                continue
            pin_signature = signature(data)
            existing = self.db.execute('''SELECT id, json_extract(project_json, '$.device') FROM pl_definitions
                                          WHERE signature=?''', (pin_signature,)).fetchone()
            if existing is None:
                continue
            ident, title = existing
            if str(ident) in deletions or edited.get(ident, pin_signature) != pin_signature:
                raise ValueError(f'Matching pinout #{ident} is staged for a configuration change or deletion.')
            if QMessageBox.question(self, 'Matching pinout',
                    f'Assign the devices on “{data["device"]}” to the existing pinout '
                    f'“{title or "Untitled"}” ({package_label(data)}, #{ident})?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
                return None
            reuse[key] = (ident, pin_signature)
        return reuse

    def save_all(self, *, confirmed=False):
        page = self.library_page
        selected_component = self.components.selected_id()
        drafts = self._all_pinout_drafts()
        deletions = copy.deepcopy(page.pending_deletions)
        if not (drafts or deletions or self.component_stage.changed):
            return True
        if not confirmed and not self.confirm_save():
            return False
        try:
            # Prepare/validate every pinout before beginning the transaction.
            prepared = [(key, draft, self._pinout_data_from_draft(draft))
                        for key, draft in drafts.items()]
            reuse = self._confirm_matching_pinouts(prepared, deletions)
            if reuse is None:
                return False
            self.db.execute('BEGIN IMMEDIATE')
            created_ids = self.component_stage.apply_locked(self.db)
            # Deleting a component removes its group memberships (foreign-key cascade).
            deleted = set(self.component_stage.deleted)
            new_ids = {}
            reused_groups = []
            for key, draft, data in prepared:
                try:
                    requested = set(map(int, draft['draft_members']))
                    missing = [cid for cid in requested if cid < 0 and cid not in created_ids]
                    if missing:
                        raise ValueError(f'{len(missing)} staged group member(s) refer to unsaved '
                                         'components that no longer exist. Remove them from the group.')
                    resolved = {created_ids.get(cid, cid) for cid in requested} - deleted
                    if key in reuse:
                        ident, pin_signature = reuse[key]
                        reused_groups.append((ident, pin_signature, resolved))
                        new_ids[key] = ident
                    elif draft['new']:
                        ident = self.library.save(data, None, locked=True)
                        if resolved:
                            row, _ = self.library.get(ident)
                            self.library.save_with_members(data, ident, row['revision'], set(),
                                                           resolved, locked=True)
                        new_ids[key] = ident
                    else:
                        self.library.save_with_members(data, int(draft['definition_id']),
                            draft['base_revision'], set(map(int,draft['base_members'])) - deleted,
                            resolved, locked=True)
                except ValueError as exc:
                    # Name the pinout: the user may have several drafts open.
                    raise ValueError(f'Pinout “{data["device"]}” ({package_label(data)}): {exc}') from exc
            for ident, pin_signature, members in reused_groups:
                row = self.db.execute('SELECT signature FROM pl_definitions WHERE id=?', (ident,)).fetchone()
                if row is None or row[0] != pin_signature:
                    raise ValueError(f'Matching pinout #{ident} changed. Review the pinout before saving again.')
                self.library.add_group_members(ident, members, locked=True)
            # Delete only after membership changes, inside the same SQLite transaction.
            for key, deletion in deletions.items():
                self.library.delete_definition(int(deletion['definition_id']), locked=True,
                    expected_members=None if key in drafts else deletion['members'],
                    expected_revision=None if key in drafts else deletion['revision'])
            publish_import = self.apply_import_locked()
            self.component_stage.apply_aliases_locked(self.db, created_ids)
            # Pinouts whose published SVGs or labels this Save can change: saved drafts
            # that have devices, and the pinouts of renamed components (labels carry
            # the part number). Only these are published afterwards.
            targets = {new_ids.get(key) or int(draft['definition_id'])
                       for key, draft, _ in prepared if draft['draft_members']}
            renamed = [cid for cid, state in self.component_stage.edits.items()
                       if state['after']['part_number'] != state['before']['part_number']]
            if renamed:
                targets |= {row[0] for row in self.db.execute(
                    'SELECT DISTINCT definition_id FROM pl_assignments WHERE component_id IN '
                    '(SELECT value FROM json_each(?))', (json.dumps(renamed),))}
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            QMessageBox.critical(self, 'Save changes', f'No changes were committed.\n\n{exc}')
            return False
        page.preview_timer.stop()
        page.draft_timer.stop()
        page.pending_pinouts.clear()
        page.pending_deletions.clear()
        page.changed = False
        self.clear_draft()
        if self.component_stage.pending_import:
            self.import_page.finish_staged_import(saved=True)
        self.component_stage.clear()
        self.component_draft_timer.stop()
        self.clear_component_draft()
        self.components.refresh(created_ids.get(selected_component, selected_component))
        # Re-open the saved pinout from disk, after the transaction finishes.
        if page._new and page._active_draft_key in new_ids:
            page.definition_id = new_ids[page._active_draft_key]
            page._active_draft_key = str(page.definition_id)
            page._new = False
        if page.definition_id is not None:
            try:
                page._reload_current()
            except Exception:
                page.definition_id = None
                page.clear()
        else:
            page._new = False
            page.clear()
        page.refresh()
        self.update_draft_ui()
        result = f'Saved {len(drafts) - len(reuse)} pinout(s), deleted {len(deletions)} pinout(s), and saved staged components.'
        if reuse:
            result += f' Reused existing pinouts for {len(reuse)} draft(s).'
        self.message(result)
        if targets or publish_import:
            # Runs on a separate SQLite connection after the transaction and cannot roll
            # back Save. A JSON import can touch any pinout, so it publishes everything.
            # Queue it so all draft state is cleared before run_job checks for edits.
            self._queue_publish(None if publish_import else targets)
            QTimer.singleShot(0, self._publish_after_new_pinout)
        return True

    def _queue_publish(self, definition_ids):
        """Add pinouts to the next automatic publish; None means all of them."""
        pending = getattr(self, '_publish_targets', set())
        if definition_ids is None or pending is None:
            self._publish_targets = None
        else:
            self._publish_targets = set(pending) | set(definition_ids)

    def _publish_after_new_pinout(self):
        """Publish the pinouts the last Save changed, without a separate user action."""
        def completed(result):
            self.refresh()
            self.library_page.refresh_members()
            skipped = result.get('skipped', [])
            updated, unchanged = result.get('updated', 0), result.get('unchanged', 0)
            self.set_unpublished(bool(skipped))
            self.message(f'Published to ICOCR: {updated} link(s) updated, {unchanged} unchanged'
                         + (f', {len(skipped)} skipped' if skipped else ''))
            if skipped:
                QMessageBox.warning(self, 'Automatic SVG publication',
                    f'Database changes were saved. {len(skipped)} pinout link(s) could not '
                    'be published. Review Settings > Tools > Publish to ICOCR for details.\n\n'
                    + '\n'.join(map(str, skipped[:10])))

        def failed(message):
            # The SQLite save has already committed; publication is a separate job.
            self.set_unpublished(True)
            self.message('Database saved; automatic SVG publication failed')

        if self.job is not None:
            # Another job holds the worker: publish when it finishes (see _job_finished).
            self._publish_retry = True
            self.set_unpublished(True)
            self.message('Database saved; SVG publication waits for the running operation')
            return
        if self.library_page.has_pending() or self.component_stage.changed:
            # New edits were staged meanwhile; publishing now is refused. Leave the
            # Publish to ICOCR button showing instead of a "deferred" that never ran.
            self.set_unpublished(True)
            self.message('Database saved; use Publish to ICOCR after saving your new changes')
            return
        targets, self._publish_targets = getattr(self, '_publish_targets', None), set()
        if targets is not None and not targets:
            return
        payload = None if targets is None else {'definition_ids': sorted(targets)}
        if not self.run_job('publish', payload, completed, on_error=failed):
            self._queue_publish(targets)
            self.set_unpublished(True)
            self.message('Database saved; SVG publication not started')

    def save_draft(self):
        page = getattr(self, 'library_page', None)
        if page is None:
            return False
        payload = page.session_payload()
        if not payload['drafts'] and not payload['deletions']:
            return False
        try:
            if self._protect_existing_draft and self.draft_path.exists():
                self._preserve_draft_file(self.draft_path)
            self._protect_existing_draft = False
            write_draft(self.draft_path, payload)
            return True
        except Exception as exc:
            self.message(f'Could not save pinout session: {exc}')
            return False

    def clear_draft(self):
        if self._startup_recovery_pending or self._protect_existing_draft:
            return  # Initial selection / user-kept draft must not be discarded.
        try:
            delete_draft(self.draft_path)
        except OSError as exc:
            self.statusBar().showMessage(f'Could not remove recovery draft: {exc}')
