"""All rows in one scrollable tree, inserted in short chunks to keep Tk responsive."""
from table_sort import sort_key


class ContinuousTable:
    def __init__(self, tree, on_progress=None):
        self.tree = tree; self.on_progress = on_progress
        self.rows = []; self.pending = None; self.column = None; self.reverse = False
        self.titles = {c:tree.heading(c,'text') for c in tree['columns']}
        self.columns = list(tree['columns']); self.selection = set(); self.select_everything = False
        for column in self.columns:
            tree.heading(column,command=lambda c=column:self.sort(c))
        for key in ('<Control-a>','<Control-A>'):tree.bind(key,lambda e:self.select_all())
        tree.bind('<Button-1>',self.click,add='+')
        for key in ('<Up>','<Down>','<Home>','<End>','<Escape>'):
            tree.bind(key,self.clear_bulk_selection,add='+')
        tree.bind('<Destroy>',lambda e:self.cancel() if e.widget==tree else None,add='+')

    def cancel(self):
        if self.pending:
            self.tree.after_cancel(self.pending); self.pending = None

    def replace(self, rows, selection=None):
        self.selection = self._remembered() if selection is None else set(map(str,selection))
        self.cancel(); self.rows = list(rows)
        self.select_everything = False
        self._order(); self._start()

    def _order(self):
        if self.column is not None:
            col = self.columns.index(self.column)
            self.rows.sort(key=lambda row:sort_key(row[1][col]),reverse=self.reverse)
        for col,title in self.titles.items():
            self.tree.heading(col,text=title+(' ▼' if self.reverse else ' ▲') if col==self.column else title)

    def sort(self, column):
        self.selection = self._remembered(); self.cancel()
        self.reverse = not self.reverse if self.column==column else False
        self.column = column; self._order(); self._start()

    def _start(self):
        self.tree.delete(*self.tree.get_children()); self.index = 0; self._append()

    def _append(self):
        self.pending = None; end = min(self.index+250,len(self.rows)); selected=[]
        for iid,values in self.rows[self.index:end]:
            iid=str(iid);self.tree.insert('','end',iid=iid,values=values)
            if self.select_everything or iid in self.selection:selected.append(iid)
        if selected:self.tree.selection_add(selected)
        self.index=end
        if self.on_progress:self.on_progress(self.index,len(self.rows))
        if end<len(self.rows):self.pending=self.tree.after(1,self._append)

    def select_all(self):
        self.select_everything=True
        self.tree.selection_set(self.tree.get_children())
        return 'break'

    def selected(self):
        # Includes unloaded rows after Ctrl+A, so bulk operations are never silently truncated.
        return [str(r[0]) for r in self.rows] if self.select_everything else list(self.tree.selection())

    def _remembered(self):
        # While chunks are still loading, rows not inserted yet keep their remembered selection.
        current = set(self.tree.selection())
        if not self.pending: return current
        loaded = set(self.tree.get_children())
        return current|{i for i in self.selection if i not in loaded}

    def click(self,event):
        # Heading clicks sort and separator drags resize; neither changes the selection.
        if self.tree.identify_region(event.x,event.y) in ('heading','separator'): return
        self.clear_bulk_selection()

    def clear_bulk_selection(self,event=None):
        self.select_everything=False; self.selection=set()
