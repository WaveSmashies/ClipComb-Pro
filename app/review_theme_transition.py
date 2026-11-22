# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep the current picture visible until every themed widget is ready."""
import tkinter as tk
from PIL import ImageGrab,ImageTk


class ThemeTransition:
    def __init__(self,app):self.app=app;self.covers=[]

    def __enter__(self):
        root=self.app.root;root.update_idletasks();root.review_theme_batch=set()
        windows=[root];pending=list(root.winfo_children())
        while pending:
            widget=pending.pop();pending.extend(widget.winfo_children())
            if isinstance(widget,tk.Toplevel) and widget.winfo_viewable():windows.append(widget)
        # These are temporary in-memory pictures of this app's visible windows.
        # No WM_SETREDRAW: removing child visibility lets parent paints erase the
        # child rectangles, which caused the solid-background regression.
        try:
            for window in windows:
                if not window.winfo_viewable():continue
                x,y=window.winfo_rootx(),window.winfo_rooty();width,height=window.winfo_width(),window.winfo_height()
                picture=ImageGrab.grab(bbox=(x,y,x+width,y+height),all_screens=True)
                image=ImageTk.PhotoImage(picture,master=root)
                cover=tk.Label(window,image=image,borderwidth=0,highlightthickness=0,takefocus=False)
                cover.review_theme_cover=True;cover.image=image
                cover.place(x=0,y=0,width=width,height=height);cover.lift()
                self.covers.append(cover)
            root.update_idletasks()
        except Exception:
            for cover in self.covers:cover.destroy()
            self.covers=[]
        return self

    def __exit__(self,*error):
        root=self.app.root
        try:
            root.update_idletasks()
            pending=root.review_theme_batch;del root.review_theme_batch
            from review_theme import dark_title
            for window in pending:
                if window.winfo_exists():dark_title(window)
            # Flush geometry and paints under the covers, then reveal together.
            root.update_idletasks()
        finally:
            if hasattr(root,'review_theme_batch'):del root.review_theme_batch
            for cover in self.covers:
                if cover.winfo_exists():cover.destroy()
            self.covers=[]
            root.update_idletasks()
