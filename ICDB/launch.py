from contextlib import closing
import argparse
import json
import os
from pathlib import Path
import tempfile
import traceback


def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--report')
    args=p.parse_args()
    import tkinter as tk
    from version import APP_VERSION
    from browser import Browser, DATA, ROOT
    from data_lock import DataLease
    if args.self_test:
        import browser
        import workbench
        with tempfile.TemporaryDirectory() as tmp:
            browser.DATA = workbench.DATA = Path(tmp)
            root=tk.Tk();root.withdraw()
            app=workbench.Workbench(root);root.update();app.close()
        if args.report:Path(args.report).write_text(json.dumps({'ok':True,'version':APP_VERSION,'screens':4}),'utf-8')
    else:
        with DataLease(DATA):
            from workbench import Workbench
            root=tk.Tk();Workbench(root);root.mainloop()
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        import tkinter as tk
        from tkinter import messagebox
        root=tk.Tk();root.withdraw();messagebox.showerror('ICDB startup failed',f'{exc}\n\nDetails:\n{traceback.format_exc()}');root.destroy()
        raise SystemExit(1)
