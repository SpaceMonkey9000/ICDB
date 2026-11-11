"""Standalone database browser/importer; independent of IC Lens."""
from pathlib import Path
import json
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from builder import UI_BUSY_TIMEOUT_SECONDS, connect, import_file, summary, export, check_duplicates, search_pattern, add_device, update_device, delete_devices
from table_sort import enable_sorting, sort_table
ROOT=Path(__file__).resolve().parent
from shared_data import data_directory, choose_directory, database_file
from version import APP_VERSION, fit_window
DATA=data_directory(ROOT)
class Browser:
    def __init__(self,root,parent=None):
        self.root=root
        self.cell_editor=None;self.edit_cell=None
        DATA.mkdir(parents=True,exist_ok=True)
        for name in ('pinouts','models'):(DATA/name).mkdir(exist_ok=True)
        database = database_file(DATA)
        database.parent.mkdir(parents=True, exist_ok=True)
        self.db=connect(database,UI_BUSY_TIMEOUT_SECONDS);root.title('ICDB '+APP_VERSION);fit_window(root,1180,760)
        self.seen=self.shown=self.shown_review=None
        import os
        if os.name == 'nt': root.iconbitmap(str(ROOT/'ICDB.ico'))
        from pinouts import Pinouts
        self.pinouts=Pinouts(self.db,DATA);self.manager=None;self.native_busy=False
        root=parent if parent is not None else root
        location=ttk.Frame(root,padding=(10,6));location.pack(fill='x')
        ttk.Button(location,text='Choose DATA folder…',command=lambda:choose_directory(root,DATA)).pack(side='left')
        ttk.Label(location,text='DATA: '+str(DATA),wraplength=850).pack(side='left',padx=10)
        bar=ttk.Frame(root,padding=10);bar.pack(fill='x')
        ttk.Label(bar,text='Find part, function or group:').pack(side='left')
        self.search=tk.StringVar();entry=ttk.Entry(bar,textvariable=self.search,width=35);entry.pack(side='left',padx=5);entry.bind('<Return>',lambda e:self.refresh())
        ttk.Button(bar,text='Search',command=self.refresh).pack(side='left')
        ttk.Button(bar,text='Import CSV',command=self.import_source).pack(side='left',padx=5)
        ttk.Button(bar,text='Export tables',command=self.export).pack(side='left')
        editbar=ttk.Frame(root,padding=(10,0));editbar.pack(fill='x')
        ttk.Button(editbar,text='Add device…',command=self.add_device).pack(side='left')
        ttk.Button(editbar,text='Delete selected devices…',command=self.delete_devices).pack(side='left',padx=5)
        ttk.Label(editbar,text='Search: * = any characters; ? = one character').pack(side='left',padx=12)
        ttk.Button(editbar,text='Edit / link pinout',command=lambda:getattr(self,'workbench',None) and self.workbench.edit_component_pinout()).pack(side='left',padx=5)
        ttk.Button(editbar,text='Search datasheet',command=self.search_datasheet).pack(side='left',padx=5)
        self.review=tk.BooleanVar(value=False)
        body=ttk.Panedwindow(root,orient='vertical');body.pack(fill='both',expand=True,padx=10,pady=6)
        frame=ttk.Frame(body);body.add(frame,weight=3)
        self.tree=ttk.Treeview(frame,columns=('part','function','manufacturer','pinout'),show='headings')
        for c,title,width in [('part','Part / proposed text',240),('function','Function',300),('manufacturer','Manufacturer / group',160),('pinout','Pinout',280)]:
            self.tree.heading(c,text=title);self.tree.column(c,width=width)
        enable_sorting(self.tree)
        scroll=ttk.Scrollbar(frame,orient='vertical',command=lambda *args:self.scroll_table('y',*args));self.tree.configure(yscrollcommand=scroll.set)
        horizontal=ttk.Scrollbar(frame,orient='horizontal',command=lambda *args:self.scroll_table('x',*args))
        self.tree.configure(xscrollcommand=horizontal.set);horizontal.pack(side='bottom',fill='x')
        scroll.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True);self.tree.bind('<<TreeviewSelect>>',self.details)
        bottom=ttk.Panedwindow(body,orient='horizontal');body.add(bottom,weight=2)
        evidence=ttk.LabelFrame(bottom,text='Source evidence');bottom.add(evidence,weight=1)
        self.text=tk.Text(evidence,height=13,wrap='word');self.text.pack(fill='both',expand=True)
        from component_preview import ComponentPreview
        self.pinout_preview=ComponentPreview(bottom,self);bottom.add(self.pinout_preview,weight=1)
        self.tree.bind('<Double-1>',self.edit_clicked)
        self.tree.bind('<F2>',lambda e:self.edit_device())
        self.tree.bind('<Return>',lambda e:self.edit_device())
        self.tree.bind('<Button-1>',self.finish_before_navigation,add='+')
        self.tree.bind('<Configure>',lambda e:self.commit_cell(),add='+')
        for sequence in ('<MouseWheel>','<Button-4>','<Button-5>'):
            self.tree.bind(sequence,self.finish_before_navigation,add='+')
        self.status=tk.StringVar();ttk.Label(root,textvariable=self.status,padding=10).pack(fill='x')
        if parent is None:
            from database_version import DatabaseVersionLabel
            DatabaseVersionLabel(root,self.db).pack(fill='x')
        self.refresh();self.root.protocol('WM_DELETE_WINDOW',self.close)
    def snapshot(self):
        # data_version changes on commits by other connections; total_changes counts this connection's writes.
        return self.db.execute('PRAGMA data_version').fetchone()[0],self.db.total_changes
    def content(self):
        return tuple(self.db.execute("SELECT (SELECT count(*) FROM components),(SELECT max(id) FROM components),"
            "(SELECT total(length(part_number))+total(length(function))+total(length(manufacturer)) FROM components),"
            "(SELECT count(*) FROM entries),(SELECT max(id) FROM entries),(SELECT total(length(status)) FROM entries)").fetchone())
    def refresh_if_changed(self):
        """Reload only when catalogue data changed; tab switches keep selection and scroll otherwise."""
        snap=self.snapshot()
        if snap==self.seen:return False
        self.refresh();return True
    def refresh(self):
        self.cancel_cell()
        review=self.review.get();keep=self.tree.selection() if review==self.shown_review else ();y=self.tree.yview()[0]
        self.tree.delete(*self.tree.get_children());term=search_pattern(self.search.get())
        if self.review.get():
            rows=self.db.execute("SELECT id,part_number,function,component_id,status FROM entries WHERE status!='source_listed' AND (part_number LIKE ? ESCAPE '\\' OR source_group LIKE ? ESCAPE '\\' OR raw LIKE ? ESCAPE '\\' OR function LIKE ? ESCAPE '\\') ORDER BY source_id,line",(term,term,term,term))
        else:
            rows=self.db.execute("SELECT id,part_number,function,id,CASE WHEN EXISTS(SELECT 1 FROM entries WHERE component_id=components.id) THEN 'Source-listed; unverified' ELSE 'Manual; unverified' END FROM components WHERE part_number LIKE ? ESCAPE '\\' OR manufacturer LIKE ? ESCAPE '\\' OR function LIKE ? ESCAPE '\\' ORDER BY part_number",(term,term,term))
        pinouts=self.component_pinouts()
        manufacturers={r[0]:r[1] for r in self.db.execute("SELECT id,manufacturer FROM components")}
        count=0
        for row in rows:
            self.tree.insert('', 'end',iid=str(row[0]),values=(row[1],row[2],manufacturers.get(row[3],''),pinouts.get(row[3],'')));count+=1
        sort_table(self.tree)
        s=summary(self.db);self.status.set(f"{s['components']:,} catalogue records • {count} displayed • {len(s['count_mismatches'])} source-section count mismatches; see exports/summary.json")
        self.text.delete('1.0','end');self.text.insert('end','Select a record for source evidence. A support-list entry does not confirm chip identity, equivalence, or a complete ordering number.')
        keep=[i for i in keep if self.tree.exists(i)]
        if keep:self.tree.selection_set(keep)
        self.details()
        self.tree.update_idletasks();self.tree.yview_moveto(y)
        self.shown_review=review;self.seen=self.snapshot();self.shown=self.content()
    def component_pinouts(self):
        """Accepted base definitions, including unpublished links and all packages."""
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pl_matches'").fetchone():
            return {}
        result={}
        for row in self.db.execute("SELECT m.component_id,d.project_json FROM pl_matches m JOIN pl_definitions d ON d.id=m.definition_id WHERE m.status='Accepted' ORDER BY m.component_id,d.id"):
            data=json.loads(row[1])
            label=f"{data['device']} ({data['package']}, {data['count']} pins" + (" + EP)" if data.get("exposed_pad") else ")")
            values=result.setdefault(row[0],[])
            if label not in values:values.append(label)
        return {cid:'; '.join(values) for cid,values in result.items()}

    def search_datasheet(self):
        ids=self.selected_components()
        if len(ids)!=1:
            messagebox.showinfo('Datasheet search','Select one catalogue device to search.',parent=self.root);return
        row=self.db.execute('SELECT part_number,manufacturer FROM components WHERE id=?',(ids[0],)).fetchone()
        if row is None:return
        from workbench import datasheet_search_url
        try:
            if not webbrowser.open(datasheet_search_url(row['part_number'],row['manufacturer'])):
                messagebox.showinfo('Datasheet search','The browser could not be opened. Check your default browser settings.',parent=self.root)
        except Exception as exc:messagebox.showerror('Datasheet search',str(exc),parent=self.root)

    def details(self,event=None):
        selected=self.tree.selection()
        if not selected:
            self.pinout_preview.show(None);return
        ident=int(selected[0])
        component_id=ident
        if self.review.get():
            entry=self.db.execute('SELECT component_id FROM entries WHERE id=?',(ident,)).fetchone()
            component_id=entry[0] if entry else None
        self.pinout_preview.show(component_id)
        self.text.delete('1.0','end')
        if self.review.get():query='e.id=?'
        else:
            row=self.db.execute('SELECT * FROM components WHERE id=?',(ident,)).fetchone();self.text.insert('end',f"{row['part_number']}\nFunction: {row['function'] or 'not stated'}\n{row['family_hint']}\n\n");query='e.component_id=?'
        if not self.review.get():
            refs=self.pinouts.links(component_id=ident)
            if refs:
                self.text.insert('end','PINOUT REFERENCES\n')
                for ref in refs:
                    self.text.insert('end',f"{'★ ' if ref['is_default'] else ''}{ref['package'] or 'General'} | {ref['pin_count'] or '?'} pins | {ref['label'] or ref['original_name']}\n")
                self.text.insert('end','\n')
        for row in self.db.execute('SELECT e.*,s.name FROM entries e JOIN sources s ON s.id=e.source_id WHERE '+query+' ORDER BY e.id',(ident,)):
            self.text.insert('end',f"{row['name']} line {row['line']} • {row['status']}\nOriginal: {row['raw']}\nFunction: {row['function'] or 'not stated'}\nPackage/interface: {row['package_or_interface'] or 'not stated'}\nQualifiers: {row['qualifiers'] or 'none'}\nNotes: {row['reason'] or 'Source claim only; not independently verified'}\n\n")
    def add_device(self):
        self.device_dialog()

    def finish_before_navigation(self,event=None):
        if not self.commit_cell():return 'break'

    def scroll_table(self,axis,*args):
        if self.commit_cell():getattr(self.tree,axis+'view')(*args)

    def edit_clicked(self,event):
        if self.tree.identify_region(event.x,event.y)!='cell':return
        row=self.tree.identify_row(event.y);col=self.tree.identify_column(event.x)
        if row and col:
            self.tree.selection_set(row)
            column=self.tree['columns'][int(col[1:])-1]
            if column=='pinout':
                self.details()
                self.pinout_preview.open_large()
            else:self.start_cell(row,column)
        return 'break'

    def edit_device(self):
        ids=self.selected_components()
        if len(ids)==1:self.start_cell(str(ids[0]),'part')
        return 'break'

    def can_edit(self):
        return not (self.review.get() or self.native_busy or
                    (self.manager and not self.manager.closed and self.manager.busy))

    def start_cell(self,row,column):
        if column not in ('part','function','manufacturer') or not self.can_edit():return
        if not self.commit_cell():return
        self.tree.see(row);box=self.tree.bbox(row,column)
        if not box:return
        self.edit_cell=(row,column)
        widget=ttk.Entry(self.tree);self.cell_editor=widget
        widget.insert(0,self.tree.set(row,column));widget.select_range(0,'end')
        widget.place(x=box[0],y=box[1],width=box[2],height=box[3]);widget.focus_set()
        widget.bind('<Return>',lambda e:self.finish_cell())
        widget.bind('<Escape>',lambda e:self.cancel_cell())
        widget.bind('<Tab>',lambda e:self.next_cell(1))
        widget.bind('<Shift-Tab>',lambda e:self.next_cell(-1))
        widget.bind('<FocusOut>',lambda e:self.root.after_idle(self.cell_focus_left,widget))

    def cell_focus_left(self,widget):
        if self.cell_editor is widget and self.root.focus_get() is not widget:self.commit_cell()

    def commit_cell(self):
        if self.cell_editor is None:return True
        widget=self.cell_editor;row,column=self.edit_cell
        value=widget.get()
        record=self.db.execute('SELECT * FROM components WHERE id=?',(int(row),)).fetchone()
        if record is None:
            self.cancel_cell();self.status.set('Edit not saved: this device was deleted (possibly by another user). Refresh the list.')
            return True
        key={'part':'part_number','function':'function','manufacturer':'manufacturer'}[column]
        if value==record[key]:self.cancel_cell();return True
        if not self.can_edit():
            # Never discard typed text: keep the editor open until the running operation finishes.
            self.status.set('Not saved yet: a pinout operation is running. Press Enter again when it finishes, or Escape to discard.')
            return False
        values={k:record[k] for k in ('part_number','function','manufacturer')};values[key]=value
        try:update_device(self.db,int(row),values['part_number'],values['function'],values['manufacturer'])
        except Exception as exc:
            self.status.set('Edit rejected: '+str(exc));widget.focus_set();return False
        self.cancel_cell()
        saved=self.db.execute('SELECT * FROM components WHERE id=?',(int(row),)).fetchone()
        self.tree.set(row,column,saved[key]);self.seen=self.snapshot();self.shown=self.content()
        self.details();self.status.set('Saved '+saved['part_number']+'. Enter / Tab saves; Escape cancels.')
        if self.manager and not self.manager.closed:self.manager.use_selection();self.manager.changed()
        return True

    def finish_cell(self):
        if self.commit_cell():self.tree.focus_set()
        return 'break'

    def cancel_cell(self):
        widget=self.cell_editor;self.cell_editor=None;self.edit_cell=None
        if widget is not None:widget.destroy()
        return 'break'

    def next_cell(self,delta):
        if self.edit_cell is None:return 'break'
        row,column=self.edit_cell;rows=list(self.tree.get_children());columns=('part','function','manufacturer')
        index=rows.index(row)*len(columns)+columns.index(column)+delta
        if self.commit_cell() and 0<=index<len(rows)*len(columns):
            self.tree.selection_set(rows[index//len(columns)])
            self.start_cell(rows[index//len(columns)],columns[index%len(columns)])
        return 'break'

    def device_dialog(self,cid=None):
        if getattr(self,'native_busy',False):
            messagebox.showinfo("Operation running","Wait for the current pinout operation to finish.",parent=self.root);return
        if self.manager and not self.manager.closed and self.manager.busy:
            messagebox.showinfo('Device editor','Finish the current pinout operation first.',parent=self.root);return
        record=self.db.execute('SELECT * FROM components WHERE id=?',(cid,)).fetchone() if cid is not None else None
        if cid is not None and record is None:return
        title='Edit device' if record else 'Add device'
        win=tk.Toplevel(self.root);win.title(title);win.transient(self.root)
        variables=[]
        for i,label in enumerate(('Part number','Function / description','Manufacturer / group')):
            ttk.Label(win,text=label).grid(row=i,column=0,padx=10,pady=6)
            var=tk.StringVar(value=record[('part_number','function','manufacturer')[i]] if record else '');variables.append(var)
            entry=ttk.Entry(win,textvariable=var,width=48);entry.grid(row=i,column=1,padx=10)
            if i==0:entry.focus_set()
        def save():
            try:
                values=[var.get() for var in variables]
                saved_id=update_device(self.db,cid,*values) if record else add_device(self.db,*values)
            except Exception as exc:
                messagebox.showerror(title,str(exc),parent=win);return
            self.review.set(False)
            if not record:self.search.set('')
            self.refresh()
            if not self.tree.exists(str(saved_id)):
                self.search.set('');self.refresh()
            self.tree.selection_set(str(saved_id));self.tree.focus(str(saved_id));self.tree.see(str(saved_id));self.details()
            if self.manager and not self.manager.closed:
                self.manager.use_selection();self.manager.changed()
            win.destroy()
        buttons=ttk.Frame(win);buttons.grid(row=3,column=1,pady=10,sticky='e')
        ttk.Button(buttons,text='Cancel',command=win.destroy).pack(side='left',padx=5)
        ttk.Button(buttons,text='Save changes' if record else 'Add device',command=save).pack(side='left')
        win.bind('<Escape>',lambda event:win.destroy())
        win.grab_set()

    def delete_devices(self):
        if getattr(self,'native_busy',False):
            messagebox.showinfo("Operation running","Wait for the current pinout operation to finish.",parent=self.root);return
        ids=self.selected_components()
        if not ids:
            messagebox.showinfo('Delete devices','Select devices in the catalogue first (not review entries).',parent=self.root);return
        names=[self.tree.set(str(cid),'part') for cid in ids]
        if not messagebox.askyesno('Delete devices',
            f'Delete {len(ids)} selected device(s)?\n\n'+', '.join(names[:15])+('…' if len(names)>15 else '')+
            '\n\nTheir source-evidence entries and pinout associations will also be removed. Shared image files are retained. This cannot be undone.',
            parent=self.root,default='no'):return
        try:delete_devices(self.db,ids)
        except Exception as exc:
            messagebox.showerror('Delete devices',str(exc),parent=self.root);return
        self.refresh()
        if self.manager and not self.manager.closed:
            self.manager.use_selection();self.manager.refresh_assets();self.manager.refresh_links()

    def selected_components(self):
        return [] if self.review.get() else list(map(int,self.tree.selection()))

    def open_pinouts(self):
        if getattr(self,'native_busy',False):
            messagebox.showinfo("Operation running","Wait for the current pinout operation to finish.",parent=self.root);return
        from pinout_ui import PinoutManager
        if self.manager and not self.manager.closed:
            self.manager.use_selection();self.manager.window.lift()
        else:self.manager=PinoutManager(self)

    def show_report(self, title, body):
        window=tk.Toplevel(self.root);window.title(title);window.geometry('900x600')
        frame=ttk.Frame(window,padding=10);frame.pack(fill='both',expand=True)
        text=tk.Text(frame,wrap='word')
        scroll=ttk.Scrollbar(frame,orient='vertical',command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');text.pack(fill='both',expand=True)
        text.insert('1.0',body);text.configure(state='disabled')
        ttk.Button(window,text='Close',command=window.destroy).pack(pady=8)

    def check_duplicates(self):
        try:
            report=check_duplicates(self.db)
            lines=[f"{len(report['component_groups'])} repeated part-number groups",
                   f"{len(report['repeated_source_groups'])} repeated source-evidence groups",
                   'Case and surrounding whitespace are ignored. No records have been changed.', '']
            for group in report['component_groups']:
                lines.append(f"{group['part_number']}: {group['classification']}")
                for row in group['records']:
                    lines.append(f"  ID {row['id']} | {row['manufacturer'] or '(unspecified manufacturer)'} | {row['function']}")
                lines.append('')
            for rows in report['repeated_source_groups']:
                lines.append(f"{rows[0]['part_number']}: repeated source evidence (may be intentional)")
                for row in rows:
                    lines.append(f"  Entry {row['id']} | {row['source']} line {row['line']} | {row['function']}")
                lines.append('')
            self.show_report('Database duplicate check', '\n'.join(lines))
        except Exception as exc:messagebox.showerror('Duplicate check failed',str(exc),parent=self.root)

    def import_source(self):
        if getattr(self,'native_busy',False):
            messagebox.showinfo("Operation running","Wait for the current pinout operation to finish.",parent=self.root);return
        path=filedialog.askopenfilename(parent=self.root,title='Choose CSV: part number, function',filetypes=[('CSV files','*.csv'),('All files','*.*')])
        if not path:return
        replace = messagebox.askyesnocancel('CSV duplicate entries',
            'Replace existing functions with the functions from this CSV?\n\n'
            'Yes: replace duplicates; the last CSV row wins. All manufacturer variants of the same part are updated.\n'
            'No: skip duplicates and keep existing functions.\n'
            'Component IDs, manufacturers and pinout links are preserved.',
            parent=self.root,default='no')
        if replace is None:return
        try:
            result=import_file(self.db,path,replace_duplicates=replace);self.refresh()
            if result.get('already_imported'):
                messagebox.showinfo('Import','This exact file has already been imported. No changes made.',parent=self.root)
                return
            lines=[f"Imported: {result['entries']} new parts",
                   f"Replaced: {result['replaced_duplicates']} component records",
                   f"Skipped: {result['skipped_duplicates']} duplicate rows",
                   f"Different functions: {result['function_conflicts']}",
                   ('Functions replaced in place; the last CSV occurrence is used.' if replace else
                    'Existing records are retained. For new parts, the first CSV occurrence is used.'), '']
            for row in result['duplicates']:
                location=(f"CSV line {row['first_csv_line']}" if row['location']=='CSV'
                          else 'database IDs '+', '.join(map(str,row['component_ids'])))
                lines.append(f"Line {row['line']}: {row['part_number']} already in {location}")
                if row['function_conflict']:
                    lines.append(f"  Different function: {row['incoming_function']}")
                    lines.append('  Compared with: '+' | '.join(row['existing_functions']))
            self.show_report('CSV import results', '\n'.join(lines))
            try:export(self.db,DATA/'exports')
            except Exception as exc:messagebox.showwarning('Export failed',f'Import completed, but automatic export failed: {exc}',parent=self.root)
        except Exception as exc:messagebox.showerror('Import failed',str(exc),parent=self.root)
    def export(self):
        path=filedialog.askdirectory(parent=self.root,title='Export folder')
        if not path:return
        try:export(self.db,path)
        except Exception as exc:
            messagebox.showerror('Export failed',str(exc),parent=self.root);return
        messagebox.showinfo('Export','Tables and summary written to '+path,parent=self.root)
    def close(self):
        if not self.commit_cell():return
        if self.manager and not self.manager.closed:
            self.manager.close()
            if not self.manager.closed:
                messagebox.showinfo('Image references busy','The Image references window is still working or has a review window open. Finish it, then close ICDB again.',parent=self.root);return
        self.db.close();self.root.destroy()
if __name__=='__main__':
    from data_lock import DataLease
    with DataLease(DATA):
        root=tk.Tk();Browser(root);root.mainloop()
