"""A review-first importer within the ICDB pinout manager."""
import queue
import sqlite3
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import ImageTk
from icpin_bundle import Bundle, preview, apply_bundle
from pinouts import Pinouts

class BundlePreview:
    def __init__(self,manager,path):
        self.manager=manager;self.queue=queue.Queue();self.running=True;self.closed=False
        self.bundle=self.plan=None;self.note=''
        self.database=next(row[2] for row in manager.store.db.execute('PRAGMA database_list') if row[1]=='main')
        manager.busy=True
        self.window=win=tk.Toplevel(manager.window);win.title('ICPin bundle — review import');win.geometry('1120x720')
        win.transient(manager.window);win.grab_set();win.protocol('WM_DELETE_WINDOW',self.close)
        self.status=tk.StringVar(value='Reading bundle and checking device matches…')
        ttk.Label(win,textvariable=self.status,padding=10,wraplength=1060).pack(fill='x')
        tabs=ttk.Notebook(win);tabs.pack(fill='both',expand=True,padx=10)
        maps=ttk.Frame(tabs);devices=ttk.Frame(tabs)
        tabs.add(maps,text='Pinouts');tabs.add(devices,text='Device matches')
        self.maps=manager.table(maps,[('id','Pinout',210),('package','Package',90),('action','Action',100),('reason','Details',490)],10)
        self.maps.configure(selectmode='browse');self.maps.bind('<<TreeviewSelect>>',self.show_image)
        image_frame=tk.Frame(maps,background='white',height=270);image_frame.pack(fill='x',pady=6);image_frame.pack_propagate(False)
        self.image=tk.Label(image_frame,background='white');self.image.pack(fill='both',expand=True)
        self.links=manager.table(devices,[('part','Device',150),('mfr','Manufacturer',140),('pkg','Package',90),('status','Status',150),('reason','Details',400)],15)
        ttk.Label(win,text='Import applies all non-conflicting pinouts and Ready device matches. Other rows are skipped. Existing links and defaults are retained.',padding=10,wraplength=1050).pack(fill='x')
        bar=ttk.Frame(win,padding=10);bar.pack(fill='x')
        ttk.Button(bar,text='Close',command=self.close).pack(side='right')
        self.button=ttk.Button(bar,text='Import ready items',command=self.apply,state='disabled');self.button.pack(side='right',padx=8)
        self.path=path
        self.start('load',self.load);self.timer=win.after(100,self.poll)

    def load(self,store):
        bundle=Bundle(self.path)
        return bundle,preview(store,bundle)

    def start(self,kind,fn):
        self.running=True
        def work():
            db=None
            try:
                db=sqlite3.connect(self.database,timeout=30);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
                result=fn(Pinouts(db,self.manager.store.root));self.queue.put((kind,result,None))
            except Exception as exc:self.queue.put((kind,None,str(exc)))
            finally:
                if db:db.close()
        threading.Thread(target=work,daemon=True).start()

    def poll(self):
        try:
            try:kind,result,error=self.queue.get_nowait()
            except queue.Empty:return
            self.running=False
            if error and kind=='apply':
                # A stale or failed import is retryable: rebuild the preview, then re-enable Import.
                self.note='Import failed: '+error+' The preview has been refreshed; review it and import again.\n'
                self.status.set(self.note+'Refreshing preview…')
                self.maps.delete(*self.maps.get_children());self.links.delete(*self.links.get_children())
                self.bundle=self.plan=None;self.image.configure(image='',text='');self.photo=None
                self.start('load',self.load)
            elif error:self.status.set(self.note+'Import unavailable: '+error)
            elif kind=='load':
                self.bundle,self.plan=result
                for index,item in enumerate(self.plan['assets']):
                    self.maps.insert('','end',iid=str(index),values=(item['pinout_id'],item['package'],item['action'],item['reason']))
                for item in self.plan['links']:
                    self.links.insert('','end',values=(item['device'],item['manufacturer'],item['package'],item['status'],item['reason']))
                ready=sum(r['status']=='Ready' for r in self.plan['links'])
                skipped=sum(r['status'] not in {'Ready','Linked'} for r in self.plan['links'])
                count=sum(r['action']!='Conflict' for r in self.plan['assets'])
                self.status.set(self.note+f'{count} importable pinouts · {ready} new device links · {skipped} device rows need attention. Review both tabs before importing.')
                self.note=''
                if count:self.button.configure(state='normal')
                if self.maps.get_children():self.maps.selection_set('0');self.show_image()
            else:
                changed,linked=result
                self.status.set(f'Imported: {changed} new/updated pinouts and {linked} new links. Skipped rows remain listed for correction in ICPin.')
                self.manager.changed()
        except Exception as exc:
            # Keep polling so a later retry is still received and Close keeps working.
            self.status.set(self.note+'Could not show the result: '+str(exc))
            messagebox.showerror('ICPin bundle',str(exc),parent=self.window)
        finally:
            if not self.closed:self.timer=self.window.after(100,self.poll)

    def show_image(self,event=None):
        selected=self.maps.selection()
        if not selected or not self.bundle:return
        item=self.plan['assets'][int(selected[0])];entry=self.bundle.pinouts[item['pinout_id']]
        try:
            import tempfile
            from pathlib import Path
            from reference_images import load_reference_image
            with tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/'preview.svg';path.write_bytes(entry['svg'])
                thumb=load_reference_image(path,(900,260))
            self.photo=ImageTk.PhotoImage(thumb);self.image.configure(image=self.photo,text='',height=260)
        except Exception as exc:self.image.configure(image='',text='Preview unavailable: '+str(exc))

    def apply(self):
        if self.running or not self.bundle:return
        self.button.configure(state='disabled');self.status.set('Importing reviewed items…')
        self.start('apply',lambda store:apply_bundle(store,self.bundle,self.plan))

    def close(self):
        if self.running:
            self.status.set('Please wait for this operation to finish.');return
        self.closed=True;self.manager.busy=False;self.window.after_cancel(self.timer);self.window.grab_release();self.window.destroy()
