"""Fixed-size, centered utility windows within the supported 1280x800 desktop."""


def configure_dialog(window,width,height):
    screen_width=window.winfo_screenwidth()
    screen_height=window.winfo_screenheight()
    width=min(width,1240,max(1,screen_width-24))
    height=min(height,760,max(1,screen_height-24))
    x=max(0,(screen_width-width)//2)
    y=max(0,(screen_height-height)//2)
    window.geometry(f'{width}x{height}+{x}+{y}')
    window.minsize(width,height)
    window.maxsize(width,height)
    window.resizable(False,False)
