"""Resizable pin columns, in-place editing and clipboard table paste."""
import csv
import io
import tkinter as tk
from tkinter import ttk, messagebox
from pinout import ROLES
from table_sort import enable_sorting, sort_table


class PinGrid(ttk.Frame):
    columns=('number','name','role','description')
    def __init__(self,parent,changed):
        super().__init__(parent); self.changed=changed; self.editor=None;self.cell=None;self.counter=0
        self.tree=ttk.Treeview(self,columns=self.columns,show='headings',height=7,selectmode='extended')
        for key,title,width in [('number','Pin',60),('name','Name',140),('role','Role',90),('description','Description',250)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=width,minwidth=45,stretch=key in ('name','description'))
        sy=ttk.Scrollbar(self,orient='vertical',command=self.scroll_y);sy.pack(side='right',fill='y')
        sx=ttk.Scrollbar(self,orient='horizontal',command=self.scroll_x);sx.pack(side='bottom',fill='x')
        self.tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set);self.tree.pack(fill='both',expand=True)
        enable_sorting(self.tree)
        self.tree.bind('<Double-1>',self.click_edit)
        self.tree.bind('<F2>',lambda e:self.edit_selected())
        self.tree.bind('<Return>',lambda e:self.edit_selected())
        self.tree.bind('<Control-v>',lambda e:self.paste())
        self.tree.bind('<Control-c>',lambda e:self.copy())
        for wheel in ('<MouseWheel>','<Button-4>','<Button-5>'):self.tree.bind(wheel,lambda e:self.commit(),add='+')
        self.tree.bind('<Button-1>',lambda e:self.commit(),add='+')
        self.tree.bind('<Configure>',lambda e:self.commit(),add='+')

    def scroll_y(self,*args):self.commit();self.tree.yview(*args)
    def scroll_x(self,*args):self.commit();self.tree.xview(*args)

    def fill(self,pins):
        self.cancel();self.tree.delete(*self.tree.get_children())
        for pin in pins:self.insert([pin['number'],pin['name'],pin.get('role','Signal'),pin.get('description','')])
        sort_table(self.tree)

    def insert(self,values):
        self.counter+=1;iid=str(self.counter);self.tree.insert('','end',iid=iid,values=values);return iid

    def pins(self,commit=True):
        # commit=False reads the in-progress editor value without closing it (live preview).
        if commit:self.commit()
        pins=[];live=self.cell if self.editor is not None else None
        for iid in self.tree.get_children():
            number,name,role,description=[(self.editor.get() if live==(iid,c) else self.tree.set(iid,c)).strip() for c in self.columns]
            number=int(number) if number.isdecimal() else number
            pins.append(dict(number=number,name=name,role=role or 'Signal',description=description))
        return pins

    def click_edit(self,event):
        if self.tree.identify_region(event.x,event.y)!='cell':return
        row=self.tree.identify_row(event.y);column=self.tree.identify_column(event.x)
        if row and column:self.edit(row,self.columns[int(column[1:])-1])
        return 'break'

    def edit_selected(self):
        ids=self.tree.selection()
        if ids:self.edit(ids[0],'name')
        return 'break'

    def edit(self,row,column):
        self.commit();self.tree.see(row);box=self.tree.bbox(row,column)
        if not box:return
        self.cell=(row,column);value=self.tree.set(row,column)
        self.editor=ttk.Combobox(self.tree,values=ROLES,state='readonly') if column=='role' else ttk.Entry(self.tree)
        if column=='role':self.editor.set(value)
        else:self.editor.insert(0,value);self.editor.select_range(0,'end')
        self.editor.place(x=box[0],y=box[1],width=box[2],height=box[3]);self.editor.focus_set()
        self.editor.bind('<Return>',lambda e:self.finish())
        self.editor.bind('<Escape>',lambda e:self.escape())
        self.editor.bind('<Tab>',lambda e:self.next_cell(1))
        self.editor.bind('<Shift-Tab>',lambda e:self.next_cell(-1))
        self.editor.bind('<FocusOut>',lambda e,w=self.editor:self.after_idle(self.focus_left,w))
        self.editor.bind('<<ComboboxSelected>>',lambda e:self.finish())

    def commit(self):
        if self.editor is None:return
        widget=self.editor;row,column=self.cell;self.editor=None;self.cell=None
        value=widget.get();widget.destroy()
        if self.tree.exists(row) and self.tree.set(row,column)!=value:
            self.tree.set(row,column,value);self.changed()

    def focus_left(self,widget):
        # Opening the role list moves focus to the combobox popdown; that is not leaving the editor.
        if self.editor is not widget or not widget.winfo_exists():return
        focus=str(self.tk.call('focus'))
        if focus==str(widget):return
        if isinstance(widget,ttk.Combobox):
            try:popdown=str(self.tk.call('ttk::combobox::PopdownWindow',widget))
            except tk.TclError:popdown=None
            if popdown and focus.startswith(popdown):return
        self.commit()

    def finish(self):self.commit();self.tree.focus_set();return 'break'

    def escape(self):
        row=self.cell[0] if self.cell else None;self.cancel();self.tree.focus_set()
        if row and self.tree.exists(row):self.tree.selection_set(row);self.tree.focus(row)
        return 'break'

    def cancel(self):
        widget=self.editor;self.editor=None;self.cell=None
        if widget is not None:widget.destroy()
        return 'break'

    def next_cell(self,delta):
        if not self.cell:return 'break'
        row,column=self.cell;rows=list(self.tree.get_children())
        offset=rows.index(row)*4+self.columns.index(column)+delta
        self.commit()
        if 0<=offset<len(rows)*4:self.edit(rows[offset//4],self.columns[offset%4])
        return 'break'

    def add(self):
        self.commit();numbers=[p['number'] for p in self.pins() if isinstance(p['number'],int)]
        iid=self.insert([max(numbers,default=0)+1,'NC','NC','']);self.tree.selection_set(iid);self.tree.see(iid);self.changed()

    def remove(self):
        self.commit();ids=self.tree.selection()
        if ids:self.tree.delete(*ids);self.changed()

    def paste(self,text=None):
        try:
            text=self.clipboard_get() if text is None else text
            delimiter='\t' if '\t' in text else ';' if ';' in text.splitlines()[0] else ','
            pins=[]
            for row in csv.reader(io.StringIO(text),delimiter=delimiter):
                if not row or not any(x.strip() for x in row):continue
                if row[0].strip().lower() in ('number','pin','pin_number'):continue
                if not 2<=len(row)<=4:raise ValueError('Paste 2–4 columns: pin, name, optional role and description.')
                role=row[2].strip() if len(row)>2 and row[2].strip() else 'Signal'
                role=next((r for r in ROLES if r.casefold()==role.casefold()),role)
                if role not in ROLES:raise ValueError('Unknown pin role: '+role)
                pins.append(dict(number=row[0].strip(),name=row[1].strip(),role=role,description=row[3] if len(row)>3 else ''))
            if not pins:raise ValueError('No pin rows found.')
            self.fill(pins);self.changed()
        except (ValueError,IndexError,tk.TclError) as exc:messagebox.showerror('Paste pins',str(exc),parent=self)
        return 'break'

    def copy(self):
        self.commit();out=io.StringIO();writer=csv.writer(out,delimiter='\t',lineterminator='\n')
        for iid in self.tree.selection() or self.tree.get_children():writer.writerow([self.tree.set(iid,c) for c in self.columns])
        self.clipboard_clear();self.clipboard_append(out.getvalue());return 'break'
