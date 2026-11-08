"""Single application version and small window-size helper shared by the Tk screens."""
APP_VERSION = '0.8.3-RC1'


def fit_window(window, width, height, min_width=None, min_height=None):
    """Initial geometry that fits small/high-DPI screens (e.g. 1366x768 at 125%)."""
    try:sw,sh=window.winfo_screenwidth(),window.winfo_screenheight()
    except Exception:sw,sh=width+40,height+80
    w=max(400,min(width,sw-40));h=max(300,min(height,sh-80))
    window.geometry(f'{w}x{h}')
    if min_width and min_height:window.minsize(min(min_width,w),min(min_height,h))
