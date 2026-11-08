"""Grouped, resumable pinout batch review."""
import queue
import sqlite3
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import ImageOps, ImageTk
from pinouts import Pinouts
from pinout_matcher import scan, recover_sources, apply, undo, candidate_order
import rule_api
from reference_images import load_reference_image
from version import APP_VERSION, fit_window
from review_model import (ACTIONABLE, QUEUES, group_key, group_evidence, filtered_groups,
                          resolve_parts, changed_spans, load_session, save_session)


class MatchImported:
    def __init__(self, manager):
        self.manager = manager
        self.database = next(r[2] for r in manager.store.db.execute('PRAGMA database_list') if r[1]=='main')
        self.rows=[]; self.operations=[]; self.groups={}; self.group_ids={}; self.current=None
        self.checked=set(); self.manual_targets=set(); self.cache={}; self.running=False
        self.queue=queue.Queue(); self.preview=None; self.photo=None; self.compare_preview=None; self.compare_photo=None
        self.pending_save=None; self.pending_filter=None; self.after_group=None
        state=load_session(manager.store.db)
        self.deferred=state.get('deferred',{}); self.saved_group=state.get('group')
        self.saved_candidate=state.get('candidate'); self.saved_y=state.get('y',0)
        self.checked=set()
        self.unchecked=set(state.get('unchecked',[]))
        identities={r['id']:(r['part_number'],r['manufacturer']) for r in manager.store.db.execute('SELECT id,part_number,manufacturer FROM components')}
        self.manual_targets={tuple(v[:3]) for v in state.get('manual',[]) if isinstance(v,list) and len(v)==5 and identities.get(v[2])==tuple(v[3:])}
        win=self.window=tk.Toplevel(manager.window)
        win.title(f'ICDB {APP_VERSION} - Pinout batch review');fit_window(win,1480,900,980,600)
        win.transient(manager.window);win.grab_set();manager.busy=True;win.protocol('WM_DELETE_WINDOW',self.close)
        top=ttk.Frame(win,padding=8);top.pack(fill='x')
        ttk.Button(top,text='Rescan integrity',command=self.rescan).pack(side='left')
        ttk.Button(top,text='Bulk assign...',command=self.bulk).pack(side='left',padx=5)
        ttk.Button(top,text='Verified mappings...',command=self.mappings).pack(side='left')
        ttk.Button(top,text='Apply checked visible exact',command=self.exact).pack(side='right')
        self.filters={};self.combos={};saved=state.get('filters',{})
        filters=ttk.Frame(win,padding=(8,0));filters.pack(fill='x')
        specs=[('queue','Queue',QUEUES,'Pending'),('batch','Import batch',['All'],'All'),
               ('manufacturer','Manufacturer',['All'],'All'),('package','Package',['All'],'All'),
               ('pins','Pins',['All'],'All'),('rule','Match rule',['All'],'All'),
               ('reference','Reference',['All','Missing reference','Has reference'],'All')]
        for i,(name,label,values,default) in enumerate(specs):
            row,col=divmod(i,4);frame=ttk.Frame(filters);frame.grid(row=row,column=col,sticky='ew',padx=(0,8),pady=3)
            ttk.Label(frame,text=label).pack(side='left')
            var=tk.StringVar(value=saved.get(name,default));self.filters[name]=var
            combo=ttk.Combobox(frame,textvariable=var,values=values,state='readonly',width=19)
            combo.pack(side='left',fill='x',expand=True,padx=4);self.combos[name]=combo
            combo.bind('<<ComboboxSelected>>',self.filter_changed)
            filters.columnconfigure(col,weight=1)
        search=ttk.Frame(filters);search.grid(row=1,column=3,sticky='ew')
        ttk.Label(search,text='Find').pack(side='left')
        self.filters['find']=tk.StringVar(value=saved.get('find',''))
        ttk.Entry(search,textvariable=self.filters['find'],width=20).pack(side='left',fill='x',expand=True)
        self.filters['find'].trace_add('write',self.filter_changed)
        options=ttk.Frame(win,padding=(8,4));options.pack(fill='x')
        self.broad=tk.BooleanVar(value=saved.get('broad',False))
        ttk.Checkbutton(options,text='Include shared-number suggestions',variable=self.broad,command=self.filter_changed).pack(side='left')
        self.remember=tk.BooleanVar(value=False)
        ttk.Checkbutton(options,text='Save accepted pairs as verified mappings',variable=self.remember).pack(side='left',padx=16)
        self.compare=tk.BooleanVar(value=False)
        ttk.Checkbutton(options,text='Compare existing reference',variable=self.compare,command=self.show).pack(side='right')
        panes=ttk.Panedwindow(win,orient='horizontal');panes.pack(fill='both',expand=True,padx=8,pady=5)
        left=ttk.Frame(panes);centre=ttk.Frame(panes);right=ttk.Frame(panes)
        panes.add(left,weight=2);panes.add(centre,weight=4);panes.add(right,weight=4)
        ttk.Label(left,text='Pinout groups — Ctrl/Shift to select multiple').pack(anchor='w')
        self.group_tree=manager.table(left,[('source','Source / diagram',140),('package','Package',65),('count','Rows',40)],20)
        self.group_tree.configure(selectmode='extended');self.group_tree.bind('<<TreeviewSelect>>',self.select_group)
        self.group_note=tk.StringVar();ttk.Label(left,textvariable=self.group_note,wraplength=230).pack(fill='x',pady=6)
        self.title=tk.StringVar(value='Select a pinout group');ttk.Label(centre,textvariable=self.title,wraplength=460).pack(fill='x')
        self.image=tk.Label(centre,background='white',text='Source pinout');self.image.pack(fill='both',expand=True)
        self.image.bind('<Configure>',self.render);self.image.bind('<Double-1>',self.enlarge)
        self.existing_choice=ttk.Combobox(centre,state='readonly');self.existing_choice.bind('<<ComboboxSelected>>',self.load_existing)
        self.existing_image=tk.Label(centre,background='#f0f0f0');self.existing_image.bind('<Configure>',self.render)
        ttk.Label(centre,text='Double-click the source diagram to enlarge').pack(fill='x')
        ttk.Label(right,text='Candidate devices - Space toggles selected rows').pack(anchor='w')
        self.tree=manager.table(right,[('check','Use',36),('target','Target',130),('manufacturer','Manufacturer',90),
                   ('source','Source',100),('status','Status',70),('kind','Match',105),('reference','Reference',75)],12)
        self.tree.bind('<<TreeviewSelect>>',self.show);self.tree.bind('<space>',self.toggle)
        self.tree.bind('<Button-1>',self.click_check)
        selectbar=ttk.Frame(right);selectbar.pack(fill='x',pady=4)
        ttk.Button(selectbar,text='Check visible group',command=lambda:self.check_group(True)).pack(side='left')
        ttk.Button(selectbar,text='Clear group',command=lambda:self.check_group(False)).pack(side='left',padx=5)
        self.details=tk.Text(right,height=11,wrap='word',state='disabled',width=40)
        self.details.pack(fill='both',expand=True);self.details.tag_configure('diff',foreground='#aa2400',background='#fff0d0')
        actions=ttk.Frame(win,padding=8);actions.pack(fill='x')
        for title,fn in [('Accept checked',lambda:self.decide('accept')),('Reject checked',lambda:self.decide('reject')),
                         ('Defer group',self.defer),('Previous',lambda:self.move(-1)),('Next',lambda:self.move(1)),
                         ('Resume deferred',self.resume)]:
            ttk.Button(actions,text=title,command=fn).pack(side='left',padx=(0,6))
        history=ttk.Frame(win,padding=(8,0));history.pack(fill='x')
        ttk.Label(history,text='Accepted batch').pack(side='left')
        self.history=ttk.Combobox(history,state='readonly',width=65);self.history.pack(side='left',padx=6)
        ttk.Button(history,text='Undo batch',command=self.undo).pack(side='left')
        ttk.Label(history,text='Ctrl+Enter accept   Ctrl+R reject   Ctrl+D defer   Alt+Left/Right navigate').pack(side='right')
        self.status=tk.StringVar(value='Scanning imported pinouts...');ttk.Label(win,textvariable=self.status,padding=8,wraplength=1400).pack(fill='x')
        for binding,fn in [('<Control-Return>',lambda:self.decide('accept')),('<Control-r>',lambda:self.decide('reject')),
                           ('<Control-d>',self.defer),('<Alt-Right>',lambda:self.move(1)),('<Alt-Left>',lambda:self.move(-1))]:
            win.bind(binding,lambda event,f=fn:(f(),'break')[1])
        self.panes=panes;self.panes_initialized=False
        def arrange(event):
            if not self.panes_initialized and event.width>=900:
                self.panes_initialized=True
                panes.sashpos(0,int(event.width*.21));panes.sashpos(1,int(event.width*.54))
        panes.bind('<Configure>',arrange)
        self.timer=win.after(80,self.poll);self.rescan()

    def filter_state(self):
        return dict({k:v.get() for k,v in self.filters.items()},broad=self.broad.get())

    def save(self):
        if self.pending_save:self.window.after_cancel(self.pending_save)
        self.pending_save=None
        selected=self.selected()
        identities={r['id']:(r['part_number'],r['manufacturer']) for r in self.manager.store.db.execute('SELECT id,part_number,manufacturer FROM components')}
        state=dict(filters=self.filter_state(),deferred=self.deferred,group=self.current,
                   candidate=selected[0]['decision_key'] if selected else None,
                   checked=sorted(self.checked),unchecked=sorted(self.unchecked),manual=[list(v)+list(identities[v[2]]) for v in sorted(self.manual_targets) if v[2] in identities],y=self.group_tree.yview()[0])
        try:save_session(self.manager.store.db,state)
        except sqlite3.Error as exc:self.status.set('Could not save review session: '+str(exc))

    def save_later(self):
        if self.pending_save:self.window.after_cancel(self.pending_save)
        self.pending_save=self.window.after(350,self.save_if_idle)

    def save_if_idle(self):
        self.pending_save=None
        if self.running:self.save_later()
        else:self.save()

    def filter_changed(self,*_):
        if self.pending_filter:self.window.after_cancel(self.pending_filter)
        self.pending_filter=self.window.after(180,self.apply_filter)

    def apply_filter(self):
        self.pending_filter=None;self.populate();self.save_later()

    def start(self,fn,scope=None,force=False):
        if self.running:return
        self.running=True
        if self.pending_save:self.window.after_cancel(self.pending_save);self.pending_save=None
        manual=list(self.manual_targets)
        def work():
            db=None
            try:
                db=sqlite3.connect(self.database,timeout=30);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
                store=Pinouts(db,self.manager.store.root);note=fn(store)
                rows=scan(store,manual,source_scope=scope,integrity_cache=self.cache,force_integrity=force)
                errors=getattr(scan,'rule_errors',[])
                if errors:note=((note+' | ') if note else '')+'Match rule problems: '+'; '.join(errors[:5])
                ops=[dict(r) for r in db.execute("SELECT * FROM pinout_match_operations WHERE action='accept' AND undone=0 ORDER BY created_at DESC,rowid DESC")]
                self.queue.put((rows,ops,note,None,scope))
            except Exception as exc:self.queue.put((None,None,None,str(exc),scope))
            finally:
                if db:db.close()
        threading.Thread(target=work,daemon=True).start()

    def rescan(self):
        if self.running:return
        if not rule_api.confirm_site_rules(self.manager.store.root,parent=self.window):
            self.status.set('Scan cancelled: site match rules were not reviewed.');return
        self.status.set('Checking all imported diagrams and rebuilding candidates...');self.cache.clear()
        self.start(lambda store:'\n'.join(recover_sources(store)),force=True)

    def poll(self):
        try:
            try:rows,ops,note,error,scope=self.queue.get_nowait()
            except queue.Empty:return
            self.running=False
            if error:
                self.after_group=None;self.status.set(error);messagebox.showerror('Pinout review',error,parent=self.window)
            else:
                if scope is None:self.rows=rows
                else:
                    self.rows=sorted([r for r in self.rows if (r['catalog_id'],r['source_id']) not in scope]+rows,key=candidate_order)
                self.operations=ops
                # Caution rows (e.g. CAN transceivers) never start checked.
                self.checked={r['decision_key'] for r in self.rows
                              if r['status'] in ACTIONABLE and r['decision_key'] not in self.unchecked and not r.get('caution')}
                self.history.configure(values=[f"{o['created_at']} | {o['count']} links | {o['id']}" for o in ops])
                if ops:self.history.current(0)
                else:self.history.set('')
                for name,column in [('batch','catalog_id'),('manufacturer','target_manufacturer'),('package','package'),('pins','pin_count'),('rule','match_kind')]:
                    values={str(r[column]) for r in self.rows if str(r[column])}
                    if name=='manufacturer':values.update(r['source_manufacturer'] for r in self.rows if r['source_manufacturer'])
                    self.combos[name].configure(values=['All']+sorted(values))
                self.populate()
                if self.after_group:
                    if self.after_group in self.group_ids:self.focus_group(self.after_group)
                    self.after_group=None
                pending=sum(r['status'] in {'Exact','Review'} for r in self.rows)
                self.status.set(f'{len(self.groups)} visible groups | {pending} pending associations | {len(self.checked)} checked'+((' | '+note) if note else ''))
                self.manager.changed();self.save_later()
        except Exception as exc:
            # Keep polling so later jobs finish and the window can still close.
            self.after_group=None;self.status.set('Could not show the review result: '+str(exc))
            messagebox.showerror('Pinout review',str(exc),parent=self.window)
        finally:
            try:alive=bool(self.window.winfo_exists())
            except tk.TclError:alive=False
            if alive:self.timer=self.window.after(80,self.poll)

    def populate(self):
        selected_groups=self.selected_group_keys()
        old=list(self.group_ids);keep=self.current or self.saved_group
        pos=old.index(keep) if keep in old else 0
        y=self.group_tree.yview()[0] if old else self.saved_y
        self.groups=filtered_groups(self.rows,self.filter_state(),self.deferred)
        self.group_ids={g:'g'+str(i) for i,g in enumerate(self.groups)}
        self.group_tree.delete(*self.group_tree.get_children())
        for gid,rows in self.groups.items():
            names=list(dict.fromkeys(r['source'] for r in rows))
            self.group_tree.insert('','end',iid=self.group_ids[gid],values=(', '.join(names),rows[0]['package'],len(rows)))
        self.group_tree.yview_moveto(y)
        if self.groups:
            self.focus_group(keep if keep in self.groups else list(self.groups)[min(pos,len(self.groups)-1)])
            remaining=[self.group_ids[g] for g in selected_groups if g in self.group_ids]
            if remaining:
                self.group_tree.selection_set(remaining)
                if self.group_tree.focus() not in remaining:self.group_tree.focus(remaining[0])
                self.select_group()
        else:
            self.current=None;self.tree.delete(*self.tree.get_children());self.preview=None;self.image.configure(image='',text='No groups in this queue')
            self.title.set('No matching groups');self.group_note.set('');self.details.configure(state='normal');self.details.delete('1.0','end');self.details.configure(state='disabled')
            self.existing_choice.pack_forget();self.existing_image.pack_forget()
        self.saved_group=None

    def focus_group(self,gid):
        iid=self.group_ids.get(gid)
        if iid:
            self.group_tree.selection_set(iid);self.group_tree.focus(iid);self.group_tree.see(iid);self.select_group()

    def select_group(self,event=None):
        sel=self.group_tree.selection()
        if not sel:return
        focused=self.group_tree.focus()
        active=focused if focused in sel else sel[0]
        gid=next((g for g,i in self.group_ids.items() if i==active),None)
        if gid is None:return
        selected=self.selected();keep=selected[0]['decision_key'] if selected else self.saved_candidate
        self.current=gid;rows=self.groups[gid]
        self.tree.delete(*self.tree.get_children());self.row_ids={}
        for i,r in enumerate(rows):
            iid='r'+str(i);self.row_ids[iid]=r
            self.tree.insert('','end',iid=iid,values=self.values(r))
        target=next((i for i,r in self.row_ids.items() if r['decision_key']==keep),'r0')
        self.tree.selection_set(target);self.tree.focus(target);self.tree.see(target)
        self.group_note.set(f'{len(sel)} selected group(s)\nShowing {len(rows)} rows for this diagram\nBatch: {rows[0]["catalog_id"]}\nDiagram: {rows[0]["pinout_id"]}')
        self.saved_candidate=None;self.show();self.save_later()

    def values(self,r):
        return ('[x]' if r['decision_key'] in self.checked else '[ ]' if r['status'] in ACTIONABLE else '-',
                r['target'] or '(no candidate)',r['target_manufacturer'],r['source'],r['status'],
                'Verified pair' if r.get('verified') else r['match_kind'],'Present' if r.get('has_reference') else 'Missing')

    def selected(self):
        return [self.row_ids[i] for i in self.tree.selection() if i in getattr(self,'row_ids',{})]

    def selected_group_keys(self):
        selected=set(self.group_tree.selection())
        return [gid for gid,iid in self.group_ids.items() if iid in selected]

    def checked_group_rows(self):
        return [r for gid in self.selected_group_keys() for r in self.groups.get(gid,[])
                if r['decision_key'] in self.checked and r['status'] in ACTIONABLE]

    def click_check(self,event):
        if self.tree.identify_column(event.x)=='#1':
            iid=self.tree.identify_row(event.y)
            if iid:self.tree.selection_set(iid);self.toggle();return 'break'

    def toggle(self,event=None):
        if self.running:return 'break'
        for r in self.selected():
            if r['status'] not in ACTIONABLE:continue
            key=r['decision_key']
            if key in self.checked:
                self.checked.remove(key);self.unchecked.add(key)
            else:
                self.checked.add(key);self.unchecked.discard(key)
        self.refresh_checks();return 'break'

    def check_group(self,value):
        if self.running:return
        for r in self.groups.get(self.current,[]):
            if r['status'] not in ACTIONABLE:continue
            if value:
                self.checked.add(r['decision_key']);self.unchecked.discard(r['decision_key'])
            else:
                self.checked.discard(r['decision_key']);self.unchecked.add(r['decision_key'])
        self.refresh_checks()

    def refresh_checks(self):
        for iid,r in getattr(self,'row_ids',{}).items():self.tree.item(iid,values=self.values(r))
        count=sum(r['decision_key'] in self.checked for r in self.groups.get(self.current,[]))
        total=len(self.checked_group_rows())
        self.status.set(f'{count} checked in displayed group. Accept/reject applies to {total} checked visible candidates across {len(self.selected_group_keys())} selected group(s).');self.save_later()

    def show(self,event=None):
        rows=self.selected()
        if not rows:return
        r=rows[0];self.title.set(f"{r['source']} | {r['package']} | {r['pin_count']} pins")
        self.details.configure(state='normal');self.details.delete('1.0','end')
        self.details.insert('end',r['source']+'\n'+r['target']+'\n')
        for a,b,c,d in changed_spans(r['source'],r['target']):
            self.details.tag_add('diff',f'1.{a}',f'1.{b}');self.details.tag_add('diff',f'2.{c}',f'2.{d}')
        self.details.insert('end',f"\n{r['source_manufacturer']} -> {r['target_manufacturer'] or 'unknown'}\n{r['status']} | {r['match_kind']}\n{r['reason']}\n\nSource: {r['source_url']}\nPage: {r['source_page']}\n{r['notes']}\n"+
                            ('\nVerified explicit pair; current pin assignments match the saved mapping.' if r.get('verified') else ''))
        self.details.configure(state='disabled')
        try:
            path=self.manager.store.path(r) if r['path'] else None
            stamp=(str(path),path.stat().st_mtime_ns) if path else None
            if stamp!=getattr(self,'preview_stamp',None) or self.preview is None:
                self.preview=load_reference_image(path) if path else None;self.preview_stamp=stamp
            if self.preview is None:self.image.configure(image='',text='No imported diagram')
            else:self.render()
        except Exception as exc:self.preview=None;self.image.configure(image='',text=str(exc))
        if self.compare.get():
            self.existing_rows=[dict(x) for x in self.manager.store.db.execute('''SELECT l.package,l.label,a.path,a.id
                FROM pinout_links l JOIN pinout_assets a ON a.id=l.asset_id WHERE l.component_id=? ORDER BY l.package,l.id''',(r['component_id'],))]
            self.existing_choice.configure(values=[f"{x['package'] or 'General'} | {x['label'] or x['path']}" for x in self.existing_rows])
            self.existing_choice.pack(fill='x');self.existing_image.pack(fill='both',expand=True)
            if self.existing_rows:self.existing_choice.current(0)
            else:self.existing_choice.set('No existing reference')
            self.load_existing()
        else:self.existing_choice.pack_forget();self.existing_image.pack_forget()
        self.save_later()

    def load_existing(self,event=None):
        self.compare_preview=None;i=self.existing_choice.current()
        try:
            if 0<=i<len(self.existing_rows):self.compare_preview=load_reference_image(self.manager.store.path(self.existing_rows[i]))
            self.existing_image.configure(image='',text='No existing reference' if self.compare_preview is None else '')
        except Exception as exc:self.existing_image.configure(image='',text=str(exc))
        self.render()

    def render(self,event=None):
        for preview,label,attr in [(self.preview,self.image,'photo'),(self.compare_preview,self.existing_image,'compare_photo')]:
            if preview is None:continue
            im=ImageOps.contain(preview,(max(1,label.winfo_width()-10),max(1,label.winfo_height()-10)))
            photo=ImageTk.PhotoImage(im,master=self.window);setattr(self,attr,photo);label.configure(image=photo,text='')

    def enlarge(self,event=None):
        if self.preview is None:return
        win=tk.Toplevel(self.window);win.title('Source pinout')
        im=ImageOps.contain(self.preview,(win.winfo_screenwidth()-100,win.winfo_screenheight()-100))
        photo=ImageTk.PhotoImage(im,master=win);label=tk.Label(win,image=photo,bg='white');label.image=photo;label.pack()

    def move(self,delta):
        keys=list(self.group_ids)
        if not keys:return
        i=keys.index(self.current) if self.current in keys else 0
        self.focus_group(keys[min(max(0,i+delta),len(keys)-1)])

    def defer(self):
        if self.running or not self.current:return
        self.deferred[self.current]=group_evidence(self.rows,self.current);self.populate();self.save_later()

    def resume(self):
        if self.running or not self.current:return
        self.deferred.pop(self.current,None);self.populate();self.save_later()

    def decide(self,action,rows=None):
        if self.running:return
        rows=self.checked_group_rows() if rows is None else rows
        if not rows:self.status.set('Check candidate rows before accepting or rejecting.');return
        if any(r['status'] not in ACTIONABLE for r in rows):self.status.set('Only exact, review or rejected candidates can be decided.');return
        self.save()
        keys=list(self.group_ids)
        selected_groups=self.selected_group_keys()
        if action=='accept' and selected_groups:
            last=max(keys.index(g) for g in selected_groups)
            self.after_group=keys[last+1] if last+1<len(keys) else None
        scope={(r['catalog_id'],r['source_id']) for r in rows}
        # Other source records for the same targets must refresh conflict/reference state too.
        targets={r['component_id'] for r in rows}
        scope.update((r['catalog_id'],r['source_id']) for r in self.rows if r['component_id'] in targets)
        remember=self.remember.get()
        if remember and action=='accept':scope=None
        self.status.set('Revalidating affected diagrams and saving batch...')
        self.start(lambda store:f'{apply(store,rows,action,remember)[1]} associations {action}ed.',scope=scope)

    def exact(self):
        # Compatibility with the earlier flat controller's public method test.
        if not hasattr(self,'groups'):
            rows=[self.rows[int(i)] for i in self.tree.get_children() if self.rows[int(i)]['status']=='Exact']
        else:rows=[r for group in self.groups.values() for r in group
                   if r['status']=='Exact' and r['decision_key'] in self.checked]
        self.decide('accept',rows)

    def undo(self):
        if self.running:return
        i=self.history.current()
        if i<0:return
        op=self.operations[i]['id'];self.start(lambda store:f'{undo(store,op)} batch-owned links removed; saved mappings from that batch disabled.')

    def bulk(self):
        if self.running or not self.current:return
        sources={ (r['catalog_id'],r['source_id']):r for r in self.groups[self.current] }
        win=tk.Toplevel(self.window);win.title('Bulk manual assignment');win.geometry('780x600');win.transient(self.window);win.grab_set()
        ttk.Label(win,text='Choose a source identity, then paste exact part numbers separated by spaces, commas or newlines.').pack(padx=8,pady=8)
        choice=ttk.Combobox(win,state='readonly',values=[f"{r['source']} | {r['source_manufacturer']}" for r in sources.values()]);choice.pack(fill='x',padx=8);choice.current(0)
        entry=tk.Text(win,height=6);entry.pack(fill='x',padx=8,pady=6)
        tree=self.manager.table(win,[('part','Requested',150),('result','Result',180),('manufacturer','Manufacturer',130)],10)
        resolved={};report=tk.StringVar();ttk.Label(win,textvariable=report,wraplength=750).pack(fill='x',padx=8)
        def resolve():
            tree.delete(*tree.get_children());resolved.clear();ambiguous=missing=0
            for part,matches in resolve_parts(self.manager.store.db,entry.get('1.0','end')):
                if not matches:tree.insert('','end',values=(part,'Not found',''));missing+=1
                for candidate in matches:
                    iid=tree.insert('','end',values=(part,'Exact' if len(matches)==1 else 'Ambiguous - select identity',candidate['manufacturer']))
                    resolved[iid]=candidate['id']
                    if len(matches)==1:tree.selection_add(iid)
                if len(matches)>1:ambiguous+=1
            report.set(f'{missing} missing; {ambiguous} ambiguous names. Select the resolved identities to add. No associations are saved here.')
        def close():win.grab_release();win.destroy();self.window.grab_set()
        def add():
            ids={resolved[i] for i in tree.selection() if i in resolved}
            if not ids:report.set('Select resolved target identities.');return
            source=list(sources.values())[choice.current()]
            entries={(source['catalog_id'],source['source_id'],cid) for cid in ids};self.manual_targets.update(entries)
            close()
            for k in ('batch','manufacturer','package','pins','rule','reference'):self.filters[k].set('All')
            self.filters['queue'].set('All');self.filters['find'].set('');self.saved_group=group_key(source)
            self.start(lambda store:f'{len(ids)} manual targets added for review.',scope={(source['catalog_id'],source['source_id'])})
        bar=ttk.Frame(win,padding=8);bar.pack(fill='x')
        ttk.Button(bar,text='Resolve names',command=resolve).pack(side='left')
        ttk.Button(bar,text='Add selected for review',command=add).pack(side='right')
        win.protocol('WM_DELETE_WINDOW',close);entry.focus_set()

    def mappings(self):
        if self.running:return
        win=tk.Toplevel(self.window);win.title('Verified explicit mappings');win.geometry('1000x500');win.transient(self.window);win.grab_set()
        ttk.Label(win,text='Mappings require the same source identity, manufacturer, package and pin assignments. They remain reviewable suggestions.').pack(padx=8,pady=8)
        tree=self.manager.table(win,[('source','Source',130),('target','Target',130),('package','Package',80),('mfr','Target manufacturer',120),('url','Evidence source',280),('page','Page',40)],12)
        for r in self.manager.store.db.execute('SELECT * FROM pinout_verified_mappings WHERE active=1 ORDER BY source_name,target_name'):
            tree.insert('','end',iid=str(r['id']),values=(r['source_name'],r['target_name'],r['package'],r['target_manufacturer'],r['source_url'],r['source_page']))
        def close():win.grab_release();win.destroy();self.window.grab_set()
        def disable():
            ids=tree.selection()
            if not ids:return
            with self.manager.store.db:self.manager.store.db.executemany('UPDATE pinout_verified_mappings SET active=0 WHERE id=?',[(int(i),) for i in ids])
            close();self.start(lambda store:f'{len(ids)} mappings disabled; existing links retained.')
        ttk.Button(win,text='Disable selected mappings',command=disable).pack(pady=8);win.protocol('WM_DELETE_WINDOW',close)

    def close(self):
        if self.running:self.status.set('Wait for the current transaction to finish.');return
        if self.pending_save:self.window.after_cancel(self.pending_save)
        if self.pending_filter:self.window.after_cancel(self.pending_filter)
        self.save();self.window.after_cancel(self.timer);self.manager.busy=False;self.window.grab_release();self.window.destroy()
