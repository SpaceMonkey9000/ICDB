"""Tk pinout manager; image discovery runs off the Tk event thread."""
import queue
import sqlite3
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from PIL import ImageTk, ImageOps
from pinouts import Pinouts
from reference_images import load_reference_image
from table_sort import enable_sorting, sort_table
from version import APP_VERSION, fit_window
from pinout import PACKAGES


class PinoutManager:
    worker_store = None; job_manual = True; loaded = None

    def __init__(self, browser):
        self.browser = browser
        self.store = browser.pinouts
        self.window = win = tk.Toplevel(browser.root)
        win.title(f'ICDB {APP_VERSION} — Image references'); fit_window(win,1240,850,900,600)
        self.busy = False; self.closed = False; self.results = queue.Queue(); self.asset_id = None
        self.photo = None; self.preview_image = None
        self.selected_devices = browser.selected_components()
        self.target_text = tk.StringVar()
        bar = ttk.Frame(win,padding=8); bar.pack(fill='x')
        ttk.Button(bar,text='Import images…',command=self.import_images).pack(side='left')
        if not hasattr(browser,'workbench'):
            ttk.Button(bar,text='Import ICPin bundle…',command=self.import_bundle).pack(side='left',padx=4)
        ttk.Button(bar,text='Scan now',command=self.scan).pack(side='left')
        ttk.Button(bar,text='Review filename matches…',command=self.suggestions).pack(side='left',padx=4)
        if not hasattr(browser,'workbench'):
            ttk.Button(bar,text='Batch pinout review…',command=self.match_imported).pack(side='left',padx=4)
        self.folder_text = tk.StringVar(value='Pinouts: '+str(self.store.root/'pinouts'))
        ttk.Label(win,textvariable=self.folder_text,padding=(10,0)).pack(fill='x')
        panes = ttk.Panedwindow(win,orient='horizontal');panes.pack(fill='both',expand=True,padx=8,pady=8)
        left = ttk.Frame(panes);right = ttk.Frame(panes);panes.add(left,weight=2);panes.add(right,weight=3)
        find = ttk.Frame(left);find.pack(fill='x')
        self.search = tk.StringVar(); self.search.trace_add('write',lambda *_:self.refresh_assets())
        ttk.Label(find,text='Find image:').pack(side='left');ttk.Entry(find,textvariable=self.search).pack(side='left',fill='x',expand=True,padx=5)
        self.assets = self.table(left, [('name','Image',210),('caption','Caption',150),('links','Links',45)],height=10)
        self.assets.configure(selectmode='browse')
        self.assets.bind('<<TreeviewSelect>>',self.select_asset)
        self.canvas = tk.Label(right,bg='white',text='Select an image to preview',anchor='center')
        self.canvas.pack(fill='both',expand=True);self.canvas.bind('<Configure>',self.render)
        self.canvas.bind('<Double-1>',self.enlarge)
        ttk.Label(right,text='Double-click preview to enlarge').pack()
        meta = ttk.LabelFrame(left,text='Shared image details',padding=7);meta.pack(fill='x',pady=6)
        self.caption = tk.StringVar(); self.source = tk.StringVar()
        for row,(label,var) in enumerate([('Caption',self.caption),('Source / URL',self.source)]):
            ttk.Label(meta,text=label).grid(row=row,column=0,sticky='w')
            ttk.Entry(meta,textvariable=var).grid(row=row,column=1,sticky='ew',padx=5,pady=2)
        meta.columnconfigure(1,weight=1)
        ttk.Button(meta,text='Save image details',command=self.save_meta).grid(row=2,column=1,sticky='e',pady=3)
        form = ttk.LabelFrame(left,text='Attach image to devices',padding=7);form.pack(fill='x')
        ttk.Label(form,textvariable=self.target_text,wraplength=430).grid(row=0,column=0,columnspan=2,sticky='w')
        ttk.Button(form,text='Use selected catalogue devices',command=self.use_selection).grid(row=1,column=0,columnspan=2,sticky='w',pady=4)
        self.package=tk.StringVar();self.pins=tk.StringVar();self.label=tk.StringVar();self.default=tk.BooleanVar()
        for row,(label,var) in enumerate([('Package',self.package),('Pin count',self.pins),('Optional label',self.label)],2):
            ttk.Label(form,text=label).grid(row=row,column=0,sticky='w')
            if row==2:
                widget=ttk.Combobox(form,textvariable=var,values=['',*PACKAGES,'BGA'])
            else:widget=ttk.Entry(form,textvariable=var)
            widget.grid(row=row,column=1,sticky='ew',padx=5,pady=2)
        form.columnconfigure(1,weight=1)
        ttk.Checkbutton(form,text='Make default for selected devices',variable=self.default).grid(row=5,column=0,columnspan=2,sticky='w')
        ttk.Button(form,text='Attach / update association',command=self.attach).grid(row=6,column=0,columnspan=2,sticky='ew',pady=5)
        ttk.Label(form,text='Blank package = general reference. Reuse the same image for another package.',wraplength=420).grid(row=7,column=0,columnspan=2,sticky='w')
        linked = ttk.LabelFrame(win,text='Devices using the selected image',padding=6);linked.pack(fill='x',padx=8)
        self.links = self.table(linked,[('part','Device',160),('mfr','Manufacturer / group',180),('pkg','Package',100),('pins','Pins',55),('label','Label',220),('default','Default',65)],height=5)
        self.links.bind('<Double-1>',self.double_click_link)
        actions=ttk.Frame(linked);actions.pack(fill='x')
        ttk.Button(actions,text='Edit selected association…',command=self.edit_link).pack(side='left')
        ttk.Button(actions,text='Set default',command=self.make_default).pack(side='left',padx=5)
        ttk.Button(actions,text='Unlink selected',command=self.unlink).pack(side='left')
        self.status=tk.StringVar(value='Select catalogue devices, then attach an image. Changes are saved immediately.')
        ttk.Label(win,textvariable=self.status,padding=8,wraplength=1150).pack(fill='x')
        self.update_targets();self.refresh_assets()
        win.protocol('WM_DELETE_WINDOW',self.close)
        self.timer=win.after(250,self.poll);self.scan_timer=win.after(1000,self.auto_scan)

    @staticmethod
    def table(parent,columns,height):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame,columns=[x[0] for x in columns],show='headings',height=height,selectmode='extended')
        for name,label,width in columns:
            tree.heading(name,text=label);tree.column(name,width=width,minwidth=40)
        sy=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);sy.pack(side='right',fill='y')
        sx=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview);sx.pack(side='bottom',fill='x')
        tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set);tree.pack(fill='both',expand=True)
        enable_sorting(tree)
        return tree

    def safe(self,fn):
        try:return fn()
        except Exception as exc:
            self.status.set('Failed: '+str(exc));messagebox.showerror('Pinout manager',str(exc),parent=self.window)

    def update_targets(self):
        names=[r[0] for cid in self.selected_devices for r in self.store.db.execute("SELECT coalesce(part_number,'') FROM components WHERE id=?",(cid,))]
        self.target_text.set(f'{len(names)} target device(s): '+(', '.join(names[:5])+('…' if len(names)>5 else '') if names else 'Select devices in the main catalogue.'))

    def use_selection(self):
        self.selected_devices=self.browser.selected_components();self.update_targets()

    def refresh_assets(self):
        keep=self.asset_id
        self.assets.delete(*self.assets.get_children())
        for row in self.store.assets(self.search.get()):
            self.assets.insert('','end',iid=str(row['id']),values=(row['original_name'],row['caption'],row['links']))
        sort_table(self.assets)
        if keep and self.assets.exists(str(keep)):
            self.assets.selection_set(str(keep))
        else:
            self.asset_id=None;self.preview_image=None;self.photo=None;self.loaded=None
            self.canvas.configure(image='',text='Select an image to preview')
            self.caption.set('');self.source.set('');self.refresh_links()

    def select_asset(self,event=None):
        selected=self.assets.selection()
        if not selected:return
        row=self.store.db.execute('SELECT * FROM pinout_assets WHERE id=?',(int(selected[0]),)).fetchone()
        if row is None:
            # Removed elsewhere (e.g. another window or a rebuild); reload the list instead of crashing.
            self.status.set('That image no longer exists; the list has been refreshed.');self.asset_id=None;self.refresh_assets();return
        self.asset_id=row['id']
        old=self.loaded;self.loaded=(row['id'],row['path'],row['sha256'],row['caption'],row['source'])
        same=bool(old and old[0]==row['id'])
        # Reselecting the same image after a refresh keeps unsaved caption/source typing.
        if not same or (self.caption.get(),self.source.get())==old[3:]:
            self.caption.set(row['caption']);self.source.set(row['source'])
        if not same or old[1:3]!=self.loaded[1:3] or self.preview_image is None:
            self.preview_image=None
            try:
                self.preview_image=load_reference_image(self.store.path(row))
                self.render()
            except Exception as exc:self.canvas.configure(image='',text='Preview unavailable: '+str(exc))
        self.refresh_links()

    def render(self,event=None):
        if self.preview_image is None:return
        size=(max(1,self.canvas.winfo_width()-16),max(1,self.canvas.winfo_height()-16))
        im=ImageOps.contain(self.preview_image,size)
        self.photo=ImageTk.PhotoImage(im,master=self.window);self.canvas.configure(image=self.photo,text='')

    def enlarge(self,event=None):
        if self.preview_image is None:return
        win=tk.Toplevel(self.window);win.title('Pinout preview')
        im=ImageOps.contain(self.preview_image,(win.winfo_screenwidth()-100,win.winfo_screenheight()-150))
        photo=ImageTk.PhotoImage(im,master=win);label=tk.Label(win,image=photo,bg='white');label.image=photo;label.pack()

    def refresh_links(self):
        self.links.delete(*self.links.get_children())
        if self.asset_id:
            for row in self.store.links(asset_id=self.asset_id):
                self.links.insert('','end',iid=str(row['id']),values=(row['part_number'],row['manufacturer'],row['package'] or 'General',row['pin_count'] or '',row['label'],'Yes' if row['is_default'] else ''))

        sort_table(self.links)

    def changed(self):
        self.refresh_assets();self.refresh_links();self.browser.details()

    def save_meta(self):
        if self.asset_id:
            self.safe(lambda:self.store.metadata(self.asset_id,self.caption.get(),self.source.get()));self.loaded=None;self.changed()

    def attach(self):
        if self.asset_id and self.store.db.execute("SELECT 1 FROM pinout_assets WHERE id=? AND path LIKE 'pinouts/generated/%'",(self.asset_id,)).fetchone():
            messagebox.showinfo('Generated pinout','Use Pinout library → Link selected components to generate a correctly titled diagram.',parent=self.window);return
        if not self.asset_id or not self.selected_devices:
            messagebox.showinfo('Attach reference','Select an image and one or more catalogue devices first.',parent=self.window);return
        def work():
            self.store.link(self.asset_id,self.selected_devices,self.package.get(),self.pins.get(),self.label.get(),self.default.get())
            self.status.set(f'Reference attached to {len(self.selected_devices)} device(s).');self.changed()
        self.safe(work)

    def double_click_link(self,event):
        ident=self.links.identify_row(event.y)
        if not ident:return
        if ident not in self.links.selection():self.links.selection_set(ident)
        self.edit_link()
        return 'break'

    def edit_link(self):
        ids=self.links.selection()
        if hasattr(self.browser,'workbench') and any(self.store.db.execute('SELECT 1 FROM pl_publications WHERE link_id=?',(int(i),)).fetchone() for i in ids):
            messagebox.showinfo('Generated pinout','Edit or reject this link in Matching, then Publish to ICOCR.',parent=self.window);return
        if not ids:return
        rows=[self.store.db.execute('SELECT * FROM pinout_links WHERE id=?',(int(i),)).fetchone() for i in ids]
        win=tk.Toplevel(self.window);win.title(f'Edit {len(ids)} association(s)');win.transient(self.window)
        ttk.Label(win,text='Checked fields apply to every selected association. Unchecked fields keep their values.').grid(row=0,column=0,columnspan=3,padx=10,pady=8)
        fields={}
        for i,(field,label) in enumerate([('package','Package'),('pin_count','Pin count'),('label','Label')],1):
            values={str(row[field] or '') for row in rows}
            common=len(values)==1
            apply=tk.BooleanVar(value=common);var=tk.StringVar(value=next(iter(values)) if common else '')
            fields[field]=(apply,var)
            ttk.Checkbutton(win,text=label,variable=apply).grid(row=i,column=0,padx=10,pady=6,sticky='w')
            entry=ttk.Entry(win,textvariable=var,width=35);entry.grid(row=i,column=1,padx=10)
            var.trace_add('write',lambda *_,flag=apply:flag.set(True))
            ttk.Label(win,text='' if common else 'Mixed values').grid(row=i,column=2,padx=10)
        def save():
            changes={field:var.get() for field,(apply,var) in fields.items() if apply.get()}
            self.store.edit_links(ids,**changes)
            win.destroy();self.changed();self.status.set(f'{len(ids)} association(s) updated.')
        ttk.Button(win,text='Save selected associations',command=lambda:self.safe(save)).grid(row=4,column=1,pady=10)
        win.grab_set()

    def make_default(self):
        ids=self.links.selection()
        if not ids:return
        def work():
            self.store.set_defaults(ids);self.changed()
            self.status.set(f'Default set for {len(ids)} device(s).')
        self.safe(work)

    def unlink(self):
        ids=self.links.selection()
        if hasattr(self.browser,'workbench') and any(self.store.db.execute('SELECT 1 FROM pl_publications WHERE link_id=?',(int(i),)).fetchone() for i in ids):
            messagebox.showinfo('Generated pinout','Edit or reject this link in Matching, then Publish to ICOCR.',parent=self.window);return
        if not ids:return
        def work():
            self.store.unlink(list(map(int,ids)));self.changed();self.status.set('Association removed; shared image retained.')
        self.safe(work)

    def launch_job(self,fn,manual=True):
        if self.busy:return
        database = next(row[2] for row in self.store.db.execute('PRAGMA database_list') if row[1] == 'main')
        if not database:
            raise ValueError('Background imports require a saved database')
        self.busy=True;self.job_manual=manual
        if manual:self.status.set('Importing / scanning images…')
        def worker():
            try:
                # One worker connection per manager window; migrations run once, not every 30 s.
                # Jobs never overlap (busy flag), so sharing it across worker threads is safe.
                if self.worker_store is None:
                    db=sqlite3.connect(database,timeout=30,check_same_thread=False);db.row_factory=sqlite3.Row
                    db.execute('PRAGMA foreign_keys=ON')
                    try:self.worker_store=Pinouts(db,self.store.root)
                    except Exception:
                        db.close();raise
                result=fn(self.worker_store);self.results.put((True,result))
            except Exception as exc:self.results.put((False,str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        manual=self.job_manual
        try:
            try:ok,result=self.results.get_nowait()
            except queue.Empty:return
            self.busy=False;manual=self.job_manual
            if ok:
                count,errors=result
                if manual or count or errors:
                    self.status.set(f'{count} image(s)/mapping(s) processed. {len(errors)} skipped. Review filename matches to link discovered images.'
                        +('' if manual or not errors else ' Use Scan now to see the skipped files.'))
                # Automatic scans never open windows; failed files are retried by Scan now.
                if errors and manual:self.browser.show_report('Pinout import issues','\n'.join(errors))
                if count:self.changed()
            elif manual:self.status.set('Import failed: '+result)
        except Exception as exc:
            # Keep polling: a failing refresh must not leave busy set and the window unclosable.
            self.status.set('Could not show the import / scan result: '+str(exc))
            if manual:messagebox.showerror('Pinout manager',str(exc),parent=self.window)
        finally:
            if not self.closed:self.timer=self.window.after(250,self.poll)

    def import_bundle(self):
        if self.busy:
            self.status.set('Wait for the current import or scan to finish.');return
        path=filedialog.askopenfilename(parent=self.window,title='Import ICPin bundle',filetypes=[('ICPin bundle','*.icpin.zip *.zip')])
        if path:
            from bundle_ui import BundlePreview
            BundlePreview(self,path)

    def match_imported(self):
        if self.busy:
            self.status.set('Wait for the current import or scan to finish.');return
        from matcher_ui import MatchImported
        self.safe(lambda:MatchImported(self))

    def import_images(self):
        paths=filedialog.askopenfilenames(parent=self.window,title='Import pinout images',filetypes=[('Images','*.jpg *.jpeg *.png *.bmp *.webp *.svg')])
        if not paths:return
        def job(store):
            count=0;errors=[]
            for path in paths:
                try:store.import_image(path);count+=1
                except Exception as exc:errors.append(Path(path).name+': '+str(exc))
            return count,errors
        self.launch_job(job)

    def scan(self):
        self.launch_job(lambda store:store.scan(store.root/'pinouts'))

    def auto_scan(self):
        self.launch_job(lambda store:store.scan(store.root/'pinouts',retry_failed=False),manual=False)
        self.scan_timer=self.window.after(30000,self.auto_scan)

    def suggestions(self):
        rows=self.store.suggestions();win=tk.Toplevel(self.window);win.title('Review exact filename matches');win.geometry('900x500')
        ttk.Label(win,text='Select matches to accept. Package labels come from PART__PACKAGE filenames. Verify the pinout before linking.',wraplength=850,padding=10).pack()
        tree=self.table(win,[('file','Image',260),('part','Device',200),('package','Package',120)],height=12)
        for i,row in enumerate(rows):tree.insert('','end',iid=str(i),values=(row[4],row[2],row[3] or 'General'))
        def accept():
            for ident in tree.selection():
                aid,cid,_,pkg,_=rows[int(ident)];self.store.link(aid,[cid],pkg)
                tree.delete(ident)
            self.changed()
        bar=ttk.Frame(win);bar.pack(fill='x',pady=8)
        ttk.Button(bar,text='Select all',command=lambda:tree.selection_set(tree.get_children())).pack(side='left',padx=10)
        ttk.Button(bar,text='Accept selected matches',command=lambda:self.safe(accept)).pack(side='right',padx=10)

    def close(self):
        if self.busy:
            self.status.set('Please wait for image import / scan to finish before closing.');return
        self.closed=True;self.window.after_cancel(self.timer);self.window.after_cancel(self.scan_timer)
        if self.worker_store is not None:self.worker_store.db.close();self.worker_store=None
        self.window.destroy()
