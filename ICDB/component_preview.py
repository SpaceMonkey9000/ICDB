"""Embedded component pinout viewer: accepted definitions and linked images."""
import json
import tkinter as tk
from tkinter import ttk
from PIL import ImageOps, ImageTk
from pinout import diagram
from pin_library import package_label, project
from reference_images import load_reference_image
from version import fit_window


class ComponentPreview(ttk.LabelFrame):
    def __init__(self,parent,browser):
        super().__init__(parent,text='Pinout',width=500,height=260)
        self.browser=browser;self.items=[];self.scene=None;self.image=None;self.photo=None
        self.choice=ttk.Combobox(self,state='readonly');self.choice.pack(fill='x',padx=4,pady=4)
        self.choice.bind('<<ComboboxSelected>>',lambda e:self.load())
        self.canvas=tk.Canvas(self,bg='white',height=240,highlightthickness=0)
        self.canvas.pack(fill='both',expand=True,padx=4,pady=(0,4))
        self.canvas.bind('<Configure>',lambda e:self.draw())
        self.canvas.bind('<Double-1>',self.open_large)
        self.canvas.configure(cursor='hand2')
        self.message='Select a component to display its pinout.'

    def show(self,component_id):
        old=self.items[self.choice.current()][0] if self.items and self.choice.current()>=0 else None
        self.items=[];db=self.browser.db
        if component_id is not None:
            # Published image references carry default/package choices. Also expose
            # accepted native definitions, including those not yet published as SVG.
            for ref in self.browser.pinouts.links(component_id=component_id):
                self.items.append((('image',ref['id']),
                    ('Default · ' if ref['is_default'] else '')+(ref['label'] or ref['original_name'])+
                    (' · '+ref['package'] if ref['package'] else ''),dict(ref)))
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='pl_matches'").fetchone():
                rows=db.execute("SELECT d.id,d.project_json FROM pl_matches m JOIN pl_definitions d ON d.id=m.definition_id WHERE m.component_id=? AND m.status='Accepted' ORDER BY d.id",(component_id,))
                for row in rows:
                    data=json.loads(row['project_json'])
                    self.items.append((('definition',row['id']),f"{data['device']} · {package_label(data)} (library)",data))
        self.choice.configure(values=[item[1] for item in self.items])
        if not self.items:
            self.choice.set('');self.scene=None;self.image=None;self.photo=None
            self.message='No linked pinout for this component.' if component_id is not None else 'Select a component to display its pinout.'
            self.draw();return
        index=next((i for i,item in enumerate(self.items) if item[0]==old),0)
        self.choice.current(index);self.load()

    def load(self):
        self.scene=None;self.image=None;self.photo=None
        index=self.choice.current()
        if not 0<=index<len(self.items):return
        key,label,data=self.items[index]
        try:
            if key[0]=='definition':self.scene=diagram(project(data))
            else:self.image=load_reference_image(self.browser.pinouts.path(data))
            self.message=''
        except Exception as exc:self.message='Pinout unavailable: '+str(exc)
        self.draw()

    def open_large(self,event=None):
        if not self.items or (self.scene is None and self.image is None):return 'break'
        win=tk.Toplevel(self)
        win.title('Pinout · '+self.items[self.choice.current()][1])
        fit_window(win,1100,800,420,320)
        win.resizable(True,True)
        viewer=ComponentPreview(win,self.browser)
        viewer.pack(fill='both',expand=True)
        viewer.items=list(self.items)
        viewer.choice.configure(values=[item[1] for item in viewer.items])
        viewer.choice.current(self.choice.current())
        viewer.canvas.unbind('<Double-1>')
        viewer.canvas.configure(cursor='')
        viewer.load()
        win.bind('<Escape>',lambda e:win.destroy())
        return 'break'

    def draw(self):
        self.canvas.delete('all')
        if self.scene:self.scene.draw_canvas(self.canvas)
        elif self.image is not None:
            width=max(1,self.canvas.winfo_width()-12);height=max(1,self.canvas.winfo_height()-12)
            scaled=ImageOps.contain(self.image,(width,height))
            self.photo=ImageTk.PhotoImage(scaled,master=self)
            self.canvas.create_image(self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,image=self.photo)
        else:self.canvas.create_text(12,16,text=self.message,anchor='nw',width=max(80,self.canvas.winfo_width()-24),fill='#555555')
