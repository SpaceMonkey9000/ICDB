"""ICDB 0.7 desktop: components, editable pinouts, matching and direct import."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
import csv
import io
import json
import traceback
import webbrowser
from urllib.parse import urlencode
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from browser import Browser, DATA
from builder import connect
from pinouts import Pinouts
from pin_library import BatchDecisionError, Library, project, render_issue, package_label, encoded, digest, comparison_pins
from exposed_pad_editor import ExposedPadEditor
from pinout import diagram, PACKAGES, ROLES
from library_import import load_files
from library_matcher import scan
import rule_api
from continuous_table import ContinuousTable
from pin_grid import PinGrid
from table_sort import enable_sorting, sort_table
from library_queries import definition_rows, match_rows, group_members, available_components
from version import APP_VERSION, fit_window


def datasheet_search_url(part, manufacturer=''):
    query = '"'+part.strip()+'" '+manufacturer.strip()+' datasheet pdf'
    return 'https://www.google.com/search?'+urlencode({'q':query.strip()})


class Workbench:
    def __init__(self, root):
        self.root = root; self.busy = False; self.dirty = False; self.loading = False
        self.definition_id = None; self.batch = None; self.tables = []; self.closed = False
        self.scene = None; self.match_scene = None; self.future = None; self.preview_job = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.tabs = ttk.Notebook(root); self.tabs.pack(fill='both',expand=True)
        self.parts_tab = ttk.Frame(self.tabs); self.library_tab = ttk.Frame(self.tabs)
        self.match_tab = ttk.Frame(self.tabs); self.import_tab = ttk.Frame(self.tabs)
        for frame,title in [(self.parts_tab,'Components'),(self.library_tab,'Pinout library'),
                            (self.match_tab,'Matching'),(self.import_tab,'Import')]: self.tabs.add(frame,text=title)
        self.browser = Browser(root,self.parts_tab)
        self.library = Library(self.browser.pinouts)
        root.title('ICDB '+APP_VERSION);fit_window(root,1360,900,960,600)
        # Handler errors get a dialog, not just a console line (tests may install their own hook first).
        if 'report_callback_exception' not in vars(root):root.report_callback_exception=self.report_error
        self.browser.workbench = self
        self.build_library(); self.build_matching(); self.build_import()
        self.status = tk.StringVar(value='Ready')
        footer = ttk.Frame(root)
        footer.pack(side='bottom',fill='x',before=self.tabs)
        from database_version import DatabaseVersionLabel
        DatabaseVersionLabel(footer,self.browser.db).pack(side='right')
        ttk.Label(footer,textvariable=self.status,padding=(10,5)).pack(side='left',fill='x',expand=True)
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.refresh_library(); self.refresh_matches()
        self.tabs.bind('<<NotebookTabChanged>>',self.tab_changed)

    def available(self):
        if self.busy:
            messagebox.showinfo('Operation running','Wait for the current operation to finish.',parent=self.root)
            return False
        return True

    def report_error(self,kind,exc,tb):
        traceback.print_exception(kind,exc,tb)
        try:
            self.status.set('Error: '+str(exc))
            messagebox.showerror('Unexpected error',f'{kind.__name__}: {exc}\n\nThe operation did not finish. Details were printed to the console.',parent=self.root)
        except Exception:pass

    def tab_changed(self,event=None):
        if self.busy: return
        if self.tabs.select()==str(self.parts_tab): self.browser.refresh_if_changed()

    def close_manager(self,purpose):
        """Close the Image references window; explain when it refuses (scan/import or review in progress)."""
        manager=self.browser.manager
        if not manager or manager.closed:return True
        manager.close()
        if manager.closed:return True
        messagebox.showinfo('Image references busy','The Image references window is still importing or scanning, or has a review window open.\n\n'
                            f'Finish or close it, then {purpose} again.',parent=self.root)
        return False

    def run(self, label, action, done=None):
        if self.closed or not self.available(): return
        manager=self.browser.manager
        if manager and not manager.closed:
            if not messagebox.askyesno(label,f'{label} closes the Image references window. Continue?',parent=self.root): return
            if not self.close_manager('start '+label.lower()): return
        dbpath = self.browser.db.execute('PRAGMA database_list').fetchone()[2]
        def worker():
            db = connect(dbpath)
            try: return action(Library(Pinouts(db,DATA)))
            finally: db.close()
        try: future = self.executor.submit(worker)
        except RuntimeError as exc:
            self.status.set(label+' failed');messagebox.showerror(label,str(exc),parent=self.root);return
        self.future = future; self.busy = True; self.browser.native_busy = True; self.status.set(label+'…')
        def poll():
            if not future.done(): self.root.after(80,poll);return
            self.busy = False; self.browser.native_busy = False
            try: result = future.result()
            except Exception as exc:
                self.status.set(label+' failed');messagebox.showerror(label,str(exc),parent=self.root);return
            self.status.set(label+' complete')
            try:
                if done: done(result)
            except Exception as exc:
                # The database change succeeded; only showing its result failed.
                traceback.print_exc();self.status.set(label+' complete, but its result could not be shown: '+str(exc))
                messagebox.showwarning(label,f'{label} completed, but showing its result failed:\n{exc}',parent=self.root)
            finally:
                self.refresh_library();self.refresh_matches()
        self.root.after(80,poll)

    def table(self,parent,columns):
        frame = ttk.Frame(parent);frame.pack(fill='both',expand=True)
        tree = ttk.Treeview(frame,columns=[x[0] for x in columns],show='headings',selectmode='extended')
        for name,title,width in columns:
            tree.heading(name,text=title);tree.column(name,width=width,minwidth=55)
        scroll = ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
        horizontal = ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
        tree.configure(yscrollcommand=scroll.set,xscrollcommand=horizontal.set)
        scroll.pack(side='right',fill='y');horizontal.pack(side='bottom',fill='x');tree.pack(fill='both',expand=True)
        enable_sorting(tree)
        return tree

    def build_library(self):
        top = ttk.Frame(self.library_tab,padding=8);top.pack(fill='x')
        self.find = tk.StringVar();entry=ttk.Entry(top,textvariable=self.find,width=24);entry.pack(side='left')
        entry.bind('<Return>',lambda e:self.search_library())
        ttk.Button(top,text='Search',command=self.search_library).pack(side='left',padx=4)
        initial='Accepted groups' if self.browser.db.execute("SELECT 1 FROM pl_matches WHERE status='Accepted' LIMIT 1").fetchone() else 'All pinouts'
        self.library_group=tk.StringVar(value=initial)
        selector=ttk.Combobox(top,textvariable=self.library_group,values=['All pinouts','Accepted groups','Without accepted parts'],state='readonly',width=22)
        selector.pack(side='left',padx=4);selector.bind('<<ComboboxSelected>>',lambda e:self.refresh_library())
        ttk.Button(top,text='New pinout',command=self.new_definition).pack(side='left',padx=4)
        ttk.Button(top,text='Link selected components',command=self.manual_link).pack(side='left',padx=4)
        ttk.Button(top,text='Rebuild SVGs',command=self.rebuild_svgs).pack(side='left',padx=4)
        self.library_count = tk.StringVar();ttk.Label(top,textvariable=self.library_count).pack(side='right',padx=8)
        panes = ttk.Panedwindow(self.library_tab,orient='horizontal');panes.pack(fill='both',expand=True,padx=8)
        left = ttk.Frame(panes);right = ttk.Frame(panes);panes.add(left,weight=2);panes.add(right,weight=3)
        self.definitions = self.table(left,[('title','Pinout',210),('package','Package',110),('uses','Accepted',75)])
        self.definition_list=ContinuousTable(self.definitions,lambda n,t:self.library_count.set(f'{t:,} pinouts'+(f' · loading {n:,}' if n<t else '')))
        self.tables.append(self.definition_list)
        self.definitions.bind('<<TreeviewSelect>>',self.select_definition)
        form = ttk.Frame(right);form.pack(fill='x');self.fields = {}
        for i,(key,label) in enumerate([('device','Title'),('package','Package'),('count','Pin count'),('source','Source / datasheet')]):
            ttk.Label(form,text=label).grid(row=i,column=0,sticky='w',padx=5,pady=3)
            value = tk.StringVar();self.fields[key] = value
            field = ttk.Combobox(form,textvariable=value,values=PACKAGES) if key=='package' else ttk.Entry(form,textvariable=value)
            field.grid(row=i,column=1,sticky='ew',padx=5,pady=3);value.trace_add('write',self.edited)
        form.columnconfigure(1,weight=1)
        self.pad_editor = ExposedPadEditor(right, self.edited)
        self.pad_editor.pack(fill='x', pady=(3,0))
        bar = ttk.Frame(right);bar.pack(fill='x',pady=5)
        ttk.Button(bar,text='Save',command=self.save).pack(side='left',padx=5)
        ttk.Button(bar,text='Save as new',command=lambda:self.save(True)).pack(side='left')
        self.save_state = tk.StringVar();ttk.Label(bar,textvariable=self.save_state).pack(side='left',padx=6)
        sections=ttk.Panedwindow(right,orient='vertical');sections.pack(fill='both',expand=True)
        grid_frame=ttk.Frame(sections,height=190);preview_frame=ttk.Frame(sections,height=220)
        member_frame=ttk.LabelFrame(sections,text='Accepted devices in this pinout group',height=180)
        sections.add(grid_frame,weight=2);sections.add(preview_frame,weight=3);sections.add(member_frame,weight=2)
        buttons=ttk.Frame(grid_frame);buttons.pack(fill='x')
        ttk.Label(buttons,text='Double-click a cell to edit').pack(side='left',padx=5)
        self.pin_grid=PinGrid(grid_frame,self.edited)
        ttk.Button(buttons,text='Add pin',command=self.add_pin).pack(side='left',padx=3)
        ttk.Button(buttons,text='Remove pins',command=self.remove_pins).pack(side='left')
        ttk.Button(buttons,text='Paste table',command=self.paste_pins).pack(side='left',padx=3)
        self.pin_grid.pack(fill='both',expand=True)
        self.canvas = tk.Canvas(preview_frame,bg='white',height=210,highlightthickness=0);self.canvas.pack(fill='both',expand=True,padx=5,pady=5)
        self.canvas.bind('<Configure>',lambda e:self.draw())
        member_bar=ttk.Frame(member_frame);member_bar.pack(fill='x',padx=4,pady=3)
        ttk.Button(member_bar,text='Add devices...',command=self.add_members_dialog).pack(side='left')
        ttk.Button(member_bar,text='Remove selected',command=self.remove_members).pack(side='left',padx=4)
        ttk.Button(member_bar,text='Undo',command=self.undo).pack(side='left')
        self.member_count=tk.StringVar();ttk.Label(member_bar,textvariable=self.member_count).pack(side='right',padx=4)
        self.members=self.table(member_frame,[('part','Device',170),('function','Function',350)])
        self.members.configure(height=5)
        self.member_list=ContinuousTable(self.members,lambda n,t:self.member_count.set(f'{t:,} devices'))
        self.tables.append(self.member_list)
        self.source_info=tk.StringVar();ttk.Label(right,textvariable=self.source_info,wraplength=700).pack(side='bottom',fill='x',padx=5,pady=3,before=sections)

    def add_pin(self):
        self.pin_grid.add();self.fields['count'].set(str(len(self.pin_grid.tree.get_children())))

    def remove_pins(self):
        self.pin_grid.remove();self.fields['count'].set(str(len(self.pin_grid.tree.get_children())))

    def paste_pins(self):
        self.pin_grid.paste();self.fields['count'].set(str(len(self.pin_grid.tree.get_children())))

    def edited(self,*args):
        if self.loading:return
        self.dirty=True;self.save_state.set('Unsaved changes')
        if self.preview_job:self.root.after_cancel(self.preview_job)
        self.preview_job=self.root.after(350,self.preview)

    def discard(self):
        self.pin_grid.commit()
        return not self.dirty or messagebox.askyesno('Unsaved pinout','Discard unsaved pinout changes?',parent=self.root,default='no')

    def search_library(self):self.refresh_library()

    def refresh_library(self):
        self.pin_grid.commit()
        rows=definition_rows(self.browser.db,self.find.get(),self.library_group.get())
        selected=[self.definition_id] if self.definition_id else []
        self.definition_list.replace([(r['id'],(r['title'],r['package'],r['uses'])) for r in rows],selected)
        if self.definition_id:
            if not self.dirty:self.load_definition(self.definition_id)
            else:self.refresh_members()

    def select_definition(self,event=None):
        if self.loading:return
        ids=self.definitions.selection()
        if self.busy:
            # The editor cannot change mid-operation: put the highlight back on the pinout being edited.
            current=str(self.definition_id) if self.definition_id else None
            if ids and ids[0]!=current:
                if current and self.definitions.exists(current):self.definitions.selection_set(current)
                else:self.definitions.selection_remove(*ids)
                self.status.set('Wait for the current operation to finish before switching pinouts.')
            return
        if not ids:return
        ident=int(ids[0])
        if ident==self.definition_id:return
        if not self.discard():
            if self.definition_id and self.definitions.exists(str(self.definition_id)):
                self.definitions.selection_set(str(self.definition_id))
            return
        self.load_definition(ident)

    def load_definition(self,ident):
        _,data=self.library.get(ident);self.definition_id=ident;self.fill_editor(data);self.refresh_members()
        sources=self.browser.db.execute('SELECT count(*) FROM pl_sources WHERE definition_id=?',(ident,)).fetchone()[0]
        issue=render_issue(data)
        self.source_info.set(f'Pinout #{ident} · {sources} sources'+(' · '+issue if issue else ''))

    def refresh_members(self):
        rows=group_members(self.browser.db,self.definition_id) if self.definition_id else []
        self.member_list.replace([(r['id'],(r['part_number'],r['function'] or '')) for r in rows])

    def fill_editor(self,data):
        self.loading=True
        for key,value in self.fields.items():value.set(str(data.get(key,'')))
        self.pin_grid.fill(data['pins'])
        self.pad_editor.fill(data)
        self.loading=False;self.dirty=False;self.save_state.set('Saved' if self.definition_id else 'New pinout');self.preview()

    def new_definition(self):
        if not self.available() or not self.discard():return
        self.definition_id=None;self.definitions.selection_remove(*self.definitions.selection())
        self.fill_editor(dict(device='New device',package='SOIC',count=8,source='',pins=[dict(number=n,name='NC',role='NC') for n in range(1,9)]))
        self.dirty=True;self.save_state.set('Unsaved new pinout');self.refresh_members();self.source_info.set('Enter the actual pin names before accepting a link.')

    def editor_data(self,commit=True):
        if commit:self.pin_grid.commit()
        data={k:v.get().strip() for k,v in self.fields.items()};data['count']=int(data['count']);data['verified']=False
        data['pins']=self.pin_grid.pins(commit)
        pad = self.pad_editor.value()
        if pad is not None: data['exposed_pad'] = pad
        return data

    def preview(self):
        if self.preview_job:
            self.root.after_cancel(self.preview_job)
        self.preview_job=None
        try:
            # Never commit here: a delayed preview must not close the cell editor the user just moved to.
            data=self.editor_data(False);self.scene=diagram(project(data));self.draw()
        except Exception as exc:
            self.scene=None;self.canvas.delete('all');self.canvas.create_text(15,20,text=str(exc),anchor='nw',width=max(200,self.canvas.winfo_width()-30),fill='#8b3d16')

    def draw(self):
        if self.scene:self.scene.draw_canvas(self.canvas)

    def save(self,as_new=False):
        if not self.available():return
        try:
            data=self.editor_data()
            if self.definition_id and not as_new:
                count=self.browser.db.execute("SELECT count(*) FROM pl_matches WHERE definition_id=? AND status='Accepted'",(self.definition_id,)).fetchone()[0]
                if count and not messagebox.askyesno('Shared pinout',f'This changes the shared definition used by {count} accepted links. Save it?\n\nPublish to update ICOCR.',parent=self.root):return
            self.definition_id=self.library.save(data,None if as_new else self.definition_id)
            self.load_definition(self.definition_id);self.refresh_library();self.refresh_matches()
            self.status.set('Pinout saved. Run matching or publish accepted links when ready.')
        except Exception as exc:messagebox.showerror('Save pinout',str(exc),parent=self.root)

    def add_members_dialog(self):
        if not self.available():return
        self.pin_grid.commit()
        if not self.definition_id or self.dirty:
            messagebox.showinfo('Add devices','Save the pinout before changing its group.',parent=self.root);return
        ident=self.definition_id
        win=tk.Toplevel(self.root);win.title('Add devices to pinout group');win.geometry('850x620');win.transient(self.root)
        top=ttk.Frame(win,padding=8);top.pack(fill='x');find=tk.StringVar()
        entry=ttk.Entry(top,textvariable=find,width=34);entry.pack(side='left')
        ttk.Label(top,text='* = any characters; ? = one character').pack(side='left',padx=8)
        body=ttk.Frame(win);body.pack(fill='both',expand=True,padx=8)
        tree=self.table(body,[('part','Device',210),('manufacturer','Manufacturer',180),('function','Function',310)])
        count=tk.StringVar();loader=ContinuousTable(tree,lambda n,t:count.set(f'{t:,} available devices'))
        def search():
            rows=available_components(self.browser.db,ident,find.get())
            loader.replace([(r['id'],(r['part_number'],r['manufacturer'],r['function'])) for r in rows],[])
        ttk.Button(top,text='Search',command=search).pack(side='right');entry.bind('<Return>',lambda e:search())
        bottom=ttk.Frame(win,padding=8);bottom.pack(fill='x')
        ttk.Label(bottom,textvariable=count).pack(side='left')
        def add():
            ids=loader.selected()
            if not ids:return
            try:
                added=self.library.add_group_members(ident,ids)
                self.refresh_library();self.refresh_matches();search()
                self.status.set(f'{added} devices added to the accepted group. Publish to update ICOCR.')
            except Exception as exc:messagebox.showerror('Add devices',str(exc),parent=win)
        ttk.Button(bottom,text='Add selected',command=add).pack(side='right',padx=5)
        ttk.Button(bottom,text='Close',command=win.destroy).pack(side='right')
        search();entry.focus_set();win.grab_set()

    def remove_members(self):
        if not self.available() or not self.definition_id:return
        ids=self.member_list.selected()
        if not ids:return
        try:
            removed=self.library.remove_group_members(self.definition_id,ids)
            self.refresh_library();self.refresh_matches()
            self.status.set(f'{removed} devices removed from the group. Undo is available; publish to update ICOCR.')
        except Exception as exc:messagebox.showerror('Remove devices',str(exc),parent=self.root)

    def manual_link(self):
        if not self.available():return
        ids=self.browser.selected_components()
        if not ids or not self.definition_id:
            messagebox.showinfo('Link components','Select components on the Components tab, then select a saved pinout here.',parent=self.root);return
        self.library.manual_link(self.definition_id,ids);self.refresh_matches();self.tabs.select(self.match_tab)

    def edit_component_pinout(self):
        if not self.available():return
        ids=self.browser.selected_components()
        if len(ids)!=1:
            messagebox.showinfo('Edit pinout','Select one component first.',parent=self.root);return
        rows=self.browser.db.execute("SELECT definition_id FROM pl_matches WHERE component_id=? AND status='Accepted' ORDER BY id",(ids[0],)).fetchall()
        if not self.discard():return
        self.tabs.select(self.library_tab)
        self.find.set(self.browser.tree.set(str(ids[0]),'part') if len(rows)>1 else '')
        self.library_group.set('Accepted groups' if rows else 'All pinouts')
        if rows:
            self.load_definition(rows[0][0])
            self.refresh_library()
            self.status.set('Editing the accepted base pinout.' if len(rows)==1 else
                            'Multiple accepted pinouts: select the required package in the library list.')
        else:
            self.refresh_library()
            self.status.set('No accepted pinout. Select a pinout and click Link selected components, or create a new pinout.')

    def build_matching(self):
        top=ttk.Frame(self.match_tab,padding=8);top.pack(fill='x')
        ttk.Button(top,text='Run matching',command=self.run_matching).pack(side='left')
        self.match_find=tk.StringVar();entry=ttk.Entry(top,textvariable=self.match_find,width=25);entry.pack(side='left',padx=5)
        entry.bind('<Return>',lambda e:self.refresh_matches())
        ttk.Button(top,text='Search',command=self.refresh_matches).pack(side='left')
        self.match_scope=tk.StringVar(value='Component')
        scope=ttk.Combobox(top,textvariable=self.match_scope,values=['Component','Function','Pinout','Manufacturer','All fields'],state='readonly',width=13)
        scope.pack(side='left',padx=4);scope.bind('<<ComboboxSelected>>',lambda e:self.refresh_matches())
        ttk.Label(top,text='* = any characters; ? = one character').pack(side='left',padx=8)
        ttk.Button(top,text='Publish to ICOCR',command=self.publish).pack(side='right')
        filters=ttk.Frame(self.match_tab,padding=(8,0));filters.pack(fill='x')
        self.match_state=tk.StringVar(value='Suggested');self.match_rule=tk.StringVar(value='All rules')
        self.match_package=tk.StringVar(value='All packages');self.match_manufacturer=tk.StringVar(value='All manufacturers')
        self.match_view=tk.StringVar(value='All matches');self.filter_boxes={}
        for label,var,values,width in [('Status',self.match_state,['Suggested','Accepted','Rejected','Blocked','All'],11),
            ('Rule',self.match_rule,['All rules'],20),('Package',self.match_package,['All packages'],13),
            ('Manufacturer',self.match_manufacturer,['All manufacturers'],18),
            ('Show',self.match_view,['All matches','Ready to accept','With cautions','With conflicts','Without accepted pinout','With accepted pinout','Published','Not published'],22)]:
            ttk.Label(filters,text=label).pack(side='left',padx=(5,2))
            box=ttk.Combobox(filters,textvariable=var,values=values,state='readonly',width=width);box.pack(side='left');self.filter_boxes[label]=box
            box.bind('<<ComboboxSelected>>',lambda e:self.refresh_matches())
        ttk.Button(filters,text='Reset',command=self.reset_match_filters).pack(side='left',padx=5)
        actions=ttk.Frame(self.match_tab,padding=(8,6));actions.pack(fill='x')
        for title,state in [('Accept selected','Accepted'),('Reject selected','Rejected'),('Reset selected','Suggested')]:
            ttk.Button(actions,text=title,command=lambda s=state:self.decide(s)).pack(side='left',padx=2)
        ttk.Button(actions,text='Undo',command=self.undo).pack(side='left',padx=5)
        ttk.Button(actions,text='Edit pinout',command=self.edit_match).pack(side='left')
        ttk.Button(actions,text='Compare selected',command=self.compare_matches).pack(side='left',padx=5)
        ttk.Button(actions,text='Search datasheet',command=self.search_datasheet).pack(side='left',padx=5)
        self.match_count=tk.StringVar();ttk.Label(actions,textvariable=self.match_count).pack(side='right',padx=5)
        pane=ttk.Panedwindow(self.match_tab,orient='vertical');pane.pack(fill='both',expand=True,padx=8,pady=5)
        upper=ttk.Frame(pane);lower=ttk.Frame(pane);pane.add(upper,weight=3);pane.add(lower,weight=2)
        self.matches=self.table(upper,[('part','Component',170),('function','Function',320),('pinout','Pinout',190),('package','Package',110),('status','Status',90),('rule','Rule',160)])
        self.match_list=ContinuousTable(self.matches,lambda n,t:self.match_count.set(f'{t:,} matches'+(f' · loading {n:,}' if n<t else '')))
        self.tables.append(self.match_list)
        self.matches.bind('<<TreeviewSelect>>',self.match_details)
        self.matches.bind('<Double-1>',self.match_double_click)
        self.match_info=tk.Text(lower,width=65,height=10,wrap='word',state='disabled');self.match_info.pack(side='left',fill='both',expand=True)
        self.match_canvas=tk.Canvas(lower,bg='white',width=500,height=230,highlightthickness=0);self.match_canvas.pack(side='right',fill='both',expand=True)
        self.match_canvas.bind('<Configure>',lambda e:self.match_scene.draw_canvas(self.match_canvas) if self.match_scene else None)

    def match_double_click(self,event):
        if self.matches.identify_region(event.x,event.y)=='cell':self.edit_match()

    def select_all(self,tree):tree.selection_set(tree.get_children());return 'break'

    def search_matches(self):self.refresh_matches()

    def reset_match_filters(self):
        for var,value in [(self.match_find,''),(self.match_state,'All'),(self.match_rule,'All rules'),
                          (self.match_package,'All packages'),(self.match_manufacturer,'All manufacturers'),(self.match_view,'All matches'),(self.match_scope,'Component')]:var.set(value)
        self.refresh_matches()

    def refresh_matches(self):
        db=self.browser.db
        rules=[r[0] for r in db.execute('SELECT DISTINCT rule FROM pl_matches ORDER BY rule')]
        packages=[r[0] for r in db.execute("SELECT DISTINCT json_extract(project_json,'$.package') FROM pl_definitions ORDER BY 1")]
        manufacturers=[r[0] for r in db.execute('SELECT DISTINCT c.manufacturer FROM components c JOIN pl_matches m ON m.component_id=c.id ORDER BY 1')]
        self.filter_boxes['Rule'].configure(values=['All rules']+rules)
        self.filter_boxes['Package'].configure(values=['All packages']+packages)
        self.filter_boxes['Manufacturer'].configure(values=['All manufacturers']+manufacturers)
        rows=match_rows(db,self.match_find.get(),self.match_state.get(),self.match_rule.get(),
                        self.match_package.get(),self.match_manufacturer.get(),self.match_view.get(),self.match_scope.get())
        self.match_rows={str(r['id']):r for r in rows}
        self.match_list.replace([(r['id'],(r['part_number'],r['function'] or '',r['title'],r['package'],
                            r['status']+(' !' if r['blocked'] else ''),r['rule'])) for r in rows])
        self.match_scene=None;self.match_canvas.delete('all');self.set_text(self.match_info,'Select a match to inspect its pins and evidence.')

    def search_datasheet(self):
        ids=self.matches.selection()
        if not ids:return
        row=self.match_rows.get(ids[0])
        if not row:return
        try:
            if not webbrowser.open(datasheet_search_url(row['part_number'],row['manufacturer'])):
                messagebox.showinfo('Datasheet search','The browser could not be opened. Check your default browser settings.',parent=self.root)
        except Exception as exc:messagebox.showerror('Datasheet search',str(exc),parent=self.root)

    def run_matching(self):
        # Site rules are code on the shared folder: ask before new/changed ones run on this computer.
        if not rule_api.confirm_site_rules(DATA,parent=self.root):return
        self.run('Matching',scan,self.match_done)

    def match_done(self,result):
        self.status.set(f"Matching complete: {result['candidates']:,} candidates; {result['blocked']:,} blocked. Select rows to review.")
        errors=result.get('rule_errors') or [] if isinstance(result,dict) else []
        if errors:
            self.status.set(self.status.get()+f' {len(errors)} match rule problem(s).')
            messagebox.showwarning('Match rules',f'{len(errors)} match rule(s) could not be used; matching ran without them:\n\n'+self.first_lines(errors),parent=self.root)

    @staticmethod
    def first_lines(lines,limit=10):
        lines=[str(x) for x in lines]
        return '\n'.join(lines[:limit])+(f'\n… and {len(lines)-limit} more' if len(lines)>limit else '')

    def show_skipped(self,title,result):
        skipped=result.get('skipped') or [] if isinstance(result,dict) else []
        if skipped:
            self.status.set(self.status.get()+f' {len(skipped)} skipped.')
            messagebox.showwarning(title,f'{len(skipped)} accepted link(s) were skipped and not published:\n\n'+self.first_lines(skipped)
                                   +'\n\nFix them in Matching (re-accept or resolve), then publish again.',parent=self.root)

    def match_details(self,event=None):
        ids=self.matches.selection()
        if not ids:return
        row=self.match_rows.get(ids[0])
        if row is None:return
        _,data=self.library.get(row['definition_id'])
        lines=[row['part_number']+' / '+row['manufacturer'],'Function: '+(row['function'] or ''),row['status'],row['reason'],row['blocked'],
               'Source: '+data.get('source',''),'','Pin\tName\tRole']
        lines.extend(f"{p['number']}\t{p['name']}\t{p.get('role','')}" for p in data['pins'])
        self.set_text(self.match_info,'\n'.join(lines))
        try:self.match_scene=diagram(project(data,row['part_number']));self.match_scene.draw_canvas(self.match_canvas)
        except (ValueError,TypeError):self.match_scene=None;self.match_canvas.delete('all')

    def decide(self,status):
        if not self.available():return
        ids=self.match_list.selected()
        if ids:self.apply_match_decision(ids,status)

    def apply_match_decision(self,ids,status):
        try:
            self.library.decide(ids,status);self.refresh_matches();self.refresh_library();self.status.set(f'{len(ids)} links set to {status}. Publish when ready.')
        except BatchDecisionError as exc:self.show_decision_issues(ids,exc)
        except Exception as exc:messagebox.showerror('Review decision',str(exc),parent=self.root)

    def show_decision_issues(self,ids,error):
        problems={i['match_id'] for i in error.issues}
        remaining=[i for i in ids if int(i) not in problems]
        win=tk.Toplevel(self.root);win.title('Selected links need review');win.geometry('1100x570');win.transient(self.root)
        ttk.Label(win,text=f'{len(error.issues)} of {len(ids)} selected links cannot be accepted. No changes have been made.',padding=10).pack(fill='x')
        ttk.Label(win,text='Existing accepted pinouts are kept. Select a row to read the full reason.',padding=(10,0)).pack(fill='x')
        body=ttk.Frame(win,padding=8);body.pack(fill='both',expand=True)
        tree=self.table(body,[('part','Component',150),('package','Package',90),('proposed','Proposed pinout',250),('reason','Conflict / action',560)])
        details=tk.Text(win,height=7,wrap='word',state='disabled');details.pack(fill='x',padx=8)
        by_id={str(i['match_id']):i for i in error.issues}
        for iid,i in by_id.items():tree.insert('','end',iid=iid,values=(i['part'],i['package'],i['proposed'],i['reason']))
        def selected(event=None):
            choice=tree.selection()
            if choice:
                i=by_id[choice[0]]
                self.set_text(details,f"{i['part']} — {i['package']}\nProposed: {i['proposed']}\n{i['reason']}")
        tree.bind('<<TreeviewSelect>>',selected)
        if by_id:tree.selection_set(next(iter(by_id)));selected()
        buttons=ttk.Frame(win,padding=8);buttons.pack(fill='x')
        def accept_remaining():
            win.destroy()
            if self.available():self.apply_match_decision(remaining,'Accepted')
        if remaining:ttk.Button(buttons,text=f'Accept remaining {len(remaining)} links',command=accept_remaining).pack(side='left')
        ttk.Button(buttons,text='Close',command=win.destroy).pack(side='right')
        win.grab_set()

    def undo(self):
        if not self.available():return
        describe=getattr(self.library,'undo_description',None)
        try:description=describe() if describe else 'the most recent decision'
        except Exception:description='the most recent decision'
        if description is None:self.status.set('No decision to undo.');return
        if not messagebox.askyesno('Undo',f'Undo: {description}?',parent=self.root):return
        try:
            changed=self.library.undo();self.refresh_matches();self.refresh_library();self.status.set('Decision undone. Publish to update output.' if changed else 'No decision to undo.')
        except Exception as exc:
            self.status.set('Undo failed: '+str(exc));messagebox.showerror('Undo',str(exc),parent=self.root)

    def compare_matches(self):
        selected=[self.match_rows[i] for i in self.match_list.selected()]
        unique={r['definition_id']:r for r in selected}
        if len(unique)<2:
            messagebox.showinfo('Compare pinouts','Select two or more different pinouts in Matching.',parent=self.root);return
        rows=list(unique.values())[:6];maps=[]
        win=tk.Toplevel(self.root);win.title('Compare selected pinouts');win.geometry('1100x600')
        cols=[('pin','Pin',70)]
        for index,row in enumerate(rows):
            _,data=self.library.get(row['definition_id']);maps.append(comparison_pins(data))
            cols.append((str(index),data['device']+' / '+package_label(data),160))
        ttk.Label(win,text='Different pin names or roles are highlighted. Up to six unique pinouts are shown.',padding=8).pack(anchor='w')
        tree=self.table(win,cols);tree.tag_configure('different',background='#fff0c2')
        numbers=set().union(*(m.keys() for m in maps))
        for number in sorted(numbers,key=lambda n:(not n.isdecimal(),int(n) if n.isdecimal() else n)):
            values=[m.get(number,{}).get('name','—')+' ['+m.get(number,{}).get('role','')+']' for m in maps]
            tree.insert('','end',values=[number]+values,tags=('different',) if len(set(values))>1 else ())

    def edit_match(self):
        ids=self.matches.selection()
        if not ids or not self.available() or not self.discard():return
        self.load_definition(self.match_rows[ids[0]]['definition_id']);self.tabs.select(self.library_tab);self.refresh_library()

    def publish(self):
        self.pin_grid.commit()
        if self.dirty:
            messagebox.showinfo('Unsaved pinout','Save your pinout changes before publishing.',parent=self.root);return
        def done(r):
            self.status.set(f"Published: {r['updated']} updated, {r['unchanged']} unchanged, {r['removed']} removed.");self.show_skipped('Publish to ICOCR',r)
        self.run('Publish to ICOCR',lambda lib:lib.publish(),done)

    def rebuild_svgs(self):
        if not self.available():return
        self.pin_grid.commit()
        if self.dirty:
            messagebox.showinfo('Unsaved pinout','Save your pinout changes before rebuilding SVGs.',parent=self.root);return
        def done(r):
            self.status.set(f"SVG rebuild: {r['rendered']} rendered, {r['updated']} links updated, {r['removed']} removed.");self.show_skipped('Rebuild SVGs',r)
        self.run('Rebuild SVGs',lambda lib:lib.publish(force=True),done)

    def build_import(self):
        top=ttk.Frame(self.import_tab,padding=8);top.pack(fill='x')
        ttk.Button(top,text='Choose pinout source…',command=self.choose_import).pack(side='left')
        ttk.Button(top,text='Import previewed data',command=self.apply_import).pack(side='left',padx=8)
        ttk.Button(top,text='Import history',command=self.import_history).pack(side='left')
        ttk.Button(top,text='Resolve source conflicts',command=self.resolve_conflicts).pack(side='left',padx=8)
        ttk.Label(self.import_tab,text='Master/grouped DB · KiCad symbols · ICPin catalog/project · bundle · pin-table CSV',padding=8).pack(anchor='w')
        self.import_text=tk.Text(self.import_tab,wrap='word',state='disabled');self.import_text.pack(fill='both',expand=True,padx=8,pady=8)
        self.set_text(self.import_text,'Choose a pinout source to preview. No SVG files are generated during import.\n\nFor marking-database CSV files, use Import CSV on the Components tab.\n\nChanged source records are retained as conflicts; existing edits and links are preserved.')

    def choose_import(self):
        if not self.available():return
        paths=filedialog.askopenfilenames(parent=self.root,title='Import pinout data',filetypes=[('Pinout sources','*.db *.sqlite *.sqlite3 *.json *.kicad_sym *.zip *.csv'),('All files','*.*')])
        if not paths:return
        devices_path=None
        if len(paths)==1 and Path(paths[0]).suffix.lower()=='.csv':
            devices_path=filedialog.askopenfilename(parent=self.root,title='Optional device mapping CSV — Cancel to use pinout IDs as names',filetypes=[('CSV','*.csv')]) or None
        self.batch=None
        def preview_done(result):
            self.batch,counts=result
            lines=[self.batch['name'],f"{len(self.batch['items']):,} source pinouts",encoded(counts),'',
                   'Preview (first 100 records):']
            for item in self.batch['items'][:100]:
                p=item['project'];issue=render_issue(p)
                lines.append(f"{p['device']} | {package_label(p)} | {len(item['devices'])} source names"+(' | Stored only: '+issue if issue else ''))
            lines+=['','Importer report:']+self.batch.get('report',[])[:200]
            self.set_text(self.import_text,'\n'.join(lines));self.tabs.select(self.import_tab)
        def prepare(lib):
            batch=load_files(paths,devices_path);return batch,lib.preview_import(batch)
        self.run('Read source',prepare,preview_done)

    def apply_import(self):
        if self.batch is None:return
        batch=self.batch
        def done(result):
            self.set_text(self.import_text,'Import complete\n'+encoded(result)+'\n\nRun matching to find candidates for your components.');self.batch=None
        self.run('Import pinout data',lambda lib:lib.import_batch(batch),done)

    def resolve_conflicts(self):
        if not self.available():return
        rows=self.browser.db.execute('SELECT * FROM pl_conflicts ORDER BY namespace,external_id').fetchall()
        if not rows:
            messagebox.showinfo('Source conflicts','No unresolved source conflicts.',parent=self.root);return
        win=tk.Toplevel(self.root);win.title('Resolve source conflicts');win.geometry('1000x650');win.transient(self.root)
        tree=self.table(win,[('namespace','Source',240),('id','Record',240)])
        details=tk.Text(win,height=15,wrap='word');details.pack(fill='both',expand=True,padx=8)
        items={str(i):dict(r) for i,r in enumerate(rows)}
        for i,r in items.items():tree.insert('','end',iid=i,values=(r['namespace'],r['external_id']))
        def show(event=None):
            ids=tree.selection()
            if not ids:return
            r=items[ids[0]];incoming=json.loads(r['incoming_json'])
            old=self.browser.db.execute('SELECT definition_id FROM pl_sources WHERE namespace=? AND external_id=?',
                                        (r['namespace'],r['external_id'])).fetchone()
            current=self.library.get(old[0])[1] if old else {}
            oldpins={n:p['name']+' ['+p.get('role','Signal')+']' for n,p in comparison_pins(current).items()}
            newpins={n:p['name']+' ['+p.get('role','Signal')+']' for n,p in comparison_pins(incoming['project']).items()}
            lines=['Current: '+current.get('device','')+' / '+current.get('package',''),
                   'Incoming: '+incoming['project']['device']+' / '+incoming['project']['package'],'','Pin differences:']
            for n in sorted(oldpins.keys()|newpins.keys()):
                if oldpins.get(n)!=newpins.get(n):lines.append(f'{n}: {oldpins.get(n,"missing")} → {newpins.get(n,"missing")}')
            if len(lines)==4:lines.append('No pin-label changes. Source metadata, roles or aliases changed.')
            lines+=['','Incoming source names: '+', '.join(d['device'] for d in incoming['devices']),
                    'Keep current dismisses this exact incoming revision. Import as alternative keeps both for matching review.']
            details.delete('1.0','end');details.insert('1.0','\n'.join(lines))
        tree.bind('<<TreeviewSelect>>',show)
        def resolve(alternative):
            try:
                for iid in tree.selection():
                    r=items[iid];self.library.resolve_conflict(r['namespace'],r['external_id'],alternative);tree.delete(iid)
                self.refresh_library();self.import_history()
                if not tree.get_children():win.destroy()
            except Exception as exc:messagebox.showerror('Resolve conflict',str(exc),parent=win)
        buttons=ttk.Frame(win,padding=8);buttons.pack(fill='x')
        ttk.Button(buttons,text='Keep current',command=lambda:resolve(False)).pack(side='left')
        ttk.Button(buttons,text='Import as alternative',command=lambda:resolve(True)).pack(side='left',padx=8)
        ttk.Button(buttons,text='Close',command=win.destroy).pack(side='right')
        win.grab_set()

    def import_history(self):
        lines=[]
        for row in self.browser.db.execute('SELECT * FROM pl_imports ORDER BY id DESC LIMIT 10'):
            lines.extend([row['created_at']+' '+row['name'],row['report'][:15000],''])
        conflicts=self.browser.db.execute('SELECT * FROM pl_conflicts').fetchall()
        lines.append(f'{len(conflicts)} source conflicts:')
        for row in conflicts[:100]:lines.append(row['namespace']+' / '+row['external_id']+'\n'+row['incoming_json'][:1500])
        self.set_text(self.import_text,'\n'.join(lines) or 'No imports yet.')

    def set_text(self,widget,text):
        widget.configure(state='normal');widget.delete('1.0','end');widget.insert('1.0',text);widget.configure(state='disabled')

    def close(self):
        if self.closed:return
        if not self.browser.commit_cell():return
        if not self.available() or not self.discard():return
        # Child windows may refuse (busy scan/review): check before tearing anything down.
        if not self.close_manager('close ICDB'):return
        if self.preview_job:self.root.after_cancel(self.preview_job)
        for table in self.tables:table.cancel()
        self.pin_grid.cancel();self.closed=True
        self.executor.shutdown(wait=False);self.browser.close()
