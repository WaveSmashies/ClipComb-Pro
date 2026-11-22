# SPDX-License-Identifier: GPL-3.0-or-later
"""A calendar and a 24-hour time picker for the audio layout cutoff."""
from calendar import Calendar, day_abbr, month_name, monthrange
from datetime import datetime
import tkinter as tk
from tkinter import ttk

from review_dialogs import own_variables
from review_theme import dialog, present, show_error


def display_cutoff(value):
    try:
        return datetime.fromisoformat(value).strftime('%b %d, %Y  ·  %H:%M:%S')
    except ValueError:
        return 'Choose Date And Time…'


class DateTimePicker(ttk.Button):
    def __init__(self, parent, variable):
        super().__init__(parent, command=self.open, style='Round.TButton', width=26)
        self.variable = variable
        self.popup = None
        self.configure(text=display_cutoff(variable.get()))
        self.trace_id = variable.trace_add('write', self.refresh)
        self.bind('<Destroy>', self.destroyed, add='+')

    def refresh(self, *_):
        self.configure(text=display_cutoff(self.variable.get()))

    def destroyed(self, event):
        if event.widget==self:
            self.variable.trace_remove('write', self.trace_id)

    def open(self):
        if self.popup and self.popup.winfo_exists():
            self.popup.lift()
            return self.popup
        try:
            cutoff = datetime.fromisoformat(self.variable.get())
        except ValueError:
            cutoff = datetime.now().replace(microsecond=0)
        parent = self.winfo_toplevel()
        previous = parent.grab_current()
        window = dialog(parent, 'Track Format Change Date')
        self.popup = window
        window.resizable(False, False)
        page = ttk.Frame(window, padding=16)
        page.pack(fill='both', expand=True)
        nav = ttk.Frame(page)
        nav.pack(fill='x', pady=(0,8))
        year = tk.StringVar(value=str(cutoff.year))
        months = tuple(month_name[i] for i in range(1,13))
        month = tk.StringVar(value=months[cutoff.month-1])
        selected_day = cutoff.day

        def shown_month():
            number = int(year.get())
            if not 1 <= number <= 9999:
                raise ValueError('Choose a year from 1 to 9999.')
            return number, months.index(month.get())+1

        def shift(delta):
            try:
                current_year, current_month = shown_month()
            except ValueError:
                return
            index = (current_year-1)*12+current_month-1+delta
            if 0 <= index < 9999*12:
                next_year, next_month = divmod(index,12)
                month.set(months[next_month]);year.set(str(next_year+1))
                redraw()

        ttk.Button(nav, text='‹', width=4, command=lambda:shift(-1)).pack(side='left')
        month_combo = ttk.Combobox(nav, textvariable=month, values=months, state='readonly', width=12)
        month_combo.pack(side='left', padx=6)
        year_picker = ttk.Spinbox(nav, textvariable=year, from_=1, to=9999, width=6, command=lambda:redraw())
        year_picker.pack(side='left')
        ttk.Button(nav, text='›', width=4, command=lambda:shift(1)).pack(side='right')

        calendar = ttk.Frame(page)
        calendar.pack(fill='x')
        for column,name in enumerate(day_abbr):
            ttk.Label(calendar, text=name, anchor='center', style='Hint.TLabel').grid(row=0,column=column,sticky='ew',pady=(0,4))
            calendar.columnconfigure(column,weight=1,uniform='day')
        cells = [[ttk.Button(calendar, width=4) for _ in range(7)] for _ in range(6)]
        for row,week in enumerate(cells,1):
            for column,button in enumerate(week):
                button.grid(row=row,column=column,sticky='ew',padx=1,pady=1)

        def choose_day(day):
            nonlocal selected_day
            selected_day = day
            redraw()

        def redraw(event=None):
            nonlocal selected_day
            try:
                y,m = shown_month()
            except ValueError:
                return
            selected_day = min(selected_day,monthrange(y,m)[1])
            days = Calendar().monthdayscalendar(y,m)
            for index,week in enumerate(cells):
                for column,button in enumerate(week):
                    day = days[index][column] if index<len(days) else 0
                    button.configure(text=str(day) if day else '',state='normal' if day else 'disabled',
                                     style='Primary.TButton' if day==selected_day else 'Round.TButton',
                                     command=lambda day=day:choose_day(day))

        month_combo.bind('<<ComboboxSelected>>',redraw)
        year_picker.bind('<Return>',redraw)
        year_picker.bind('<FocusOut>',redraw)
        redraw()

        clock = ttk.Frame(page)
        clock.pack(fill='x',pady=(10,12))
        ttk.Label(clock,text='Time (24-hour)').pack(side='left',padx=(0,10))
        parts = []
        for index,(value,limit) in enumerate(((cutoff.hour,24),(cutoff.minute,60),(cutoff.second,60))):
            if index:ttk.Label(clock,text=':').pack(side='left')
            variable = tk.StringVar(value=f'{value:02d}')
            parts.append(variable)
            ttk.Combobox(clock,textvariable=variable,values=tuple(f'{n:02d}' for n in range(limit)),
                         state='readonly',width=3,height=10).pack(side='left')

        def apply():
            try:
                y,m = shown_month()
                day = min(selected_day,monthrange(y,m)[1])
                value = datetime(y,m,day,*(int(part.get()) for part in parts))
            except ValueError:
                show_error(window,'Check Date And Time','Choose a valid year and date before applying.')
                return
            self.variable.set(value.isoformat(timespec='seconds'))
            window.destroy()

        def restore_grab(event):
            if event.widget==window and previous and previous.winfo_exists():previous.grab_set()

        buttons = ttk.Frame(page)
        buttons.pack(fill='x')
        ttk.Button(buttons,text='Apply',style='Primary.TButton',command=apply).pack(side='right')
        ttk.Button(buttons,text='Cancel',style='Round.TButton',command=window.destroy).pack(side='right',padx=6)
        window.bind('<Destroy>',restore_grab,add='+')
        own_variables(window,year,month,*parts)
        present(window,parent)
        return window
