"""Shared application leases and exclusive updater lease on the DATA folder."""
import os
from pathlib import Path


class DataLease:
    def __init__(self, folder, exclusive=False):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        self.file = open(folder/'.icsuite.lock', 'a+b')
        try:
            if os.name == 'nt':
                import ctypes
                import msvcrt
                from ctypes import wintypes
                class OVERLAPPED(ctypes.Structure):
                    _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                                ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD),
                                ('hEvent', wintypes.HANDLE)]
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                              wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(OVERLAPPED)]
                kernel.LockFileEx.restype = wintypes.BOOL
                self.overlapped = OVERLAPPED()
                if not kernel.LockFileEx(msvcrt.get_osfhandle(self.file.fileno()),
                                         1 | (2 if exclusive else 0), 0, 1, 0, ctypes.byref(self.overlapped)):
                    raise OSError(ctypes.get_last_error(), 'DATA is in use')
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise RuntimeError('Close ICOCR, ICDB and any DATA updater, then retry.') from exc

    def close(self):
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
