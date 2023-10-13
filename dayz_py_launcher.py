import a2s
import ctypes
import hashlib
import json
import os
import platform
import re
import requests
import subprocess
import threading
import time
import tkinter as tk
from a2s import dayzquery
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timezone
from queue import Queue
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from threading import Event, Thread
from tkinter import filedialog, messagebox, PhotoImage, simpledialog, ttk
from vdf2json import vdf2json


SERVER_DB = {}
MOD_DB = {}

hidden_items = set()

appName = 'DayZ Py Launcher/0.5'
# game = 'dayz'
dzsa_api_servers = 'https://dayzsalauncher.com/api/v2/launcher/servers/dayz'
workshop_url = 'steam://url/CommunityFilePage/'
steam_cmd = 'steam'
app_id = '221100'
# home_dir = os.path.expanduser('~')
settings_json = 'dayz_py.json'

# Header used in DZSA API request
headers = {
    'User-Agent': f'({appName}'
}

# Default settings
settings = {
    'dayz_dir': '',
    'steam_dir': '',
    'profile_name': '',
    'launch_params': '',
    'theme': 'dark',
    'install_type': 'steam',
    'max_servers_display': 0, # 0 = No Limit
    'max_sim_pings': 20,
    'load_favs_on_startup': True,
    'check_updates': False,
    'favorites': {},
    'history': {}
}


class App(ttk.Frame):
    def __init__(self, parent):
        ttk.Frame.__init__(self)

        # Make the app responsive
        for index in [0, 1]:
            self.columnconfigure(index=index, weight=1)
            self.rowconfigure(index=index, weight=1)

        # List for Map Combobox
        self.dayz_maps = []

        # Create widgets :)
        self.setup_widgets()

        # Messagebox Title
        self.message_title = 'DayZ Py Message'

    def MessageBoxAskYN(self, message):
        return messagebox.askyesno(title=self.message_title, message=message)

    def MessageBoxInfo(self, message):
        messagebox.showinfo(title=self.message_title, message=message)

    def MessageBoxError(self, message):
        messagebox.showerror(title=self.message_title, message=message)

    def MessageBoxWarn(self, message):
        messagebox.showwarning(title=self.message_title, message=message)

    # To be used for copy to clipboard
    # def copy_item(self):
    #     selected_item = self.treeview.selection()
    #     if selected_item:
    #         copied_item = self.treeview.item(selected_item[0])['values']
    #         print("Copied item:", copied_item)

    def OnSingleClick(self, event):
        """
        These actions are performed when the user clicks on a server/entry in the
        Server List Treeview. Gets IP and Port info from treeview entry. Queries
        the SERVER_DB for the info to compare server mods vs locally installed mods.
        Then generates the Server Mod Treeview and Info on Tab 2 ('Server Info')
        """
        if self.treeview.selection():

            ip, _, qport = get_selected_ip(self.treeview.selection()[0])

            self.check_favorites(ip, qport)

            server_db_info = SERVER_DB.get(f'{ip}:{qport}')

            last_joined = self.check_history(ip, qport)
            # Since we are manually inserting servers into the DB (i.e. Favorites and History)
            # that may be down or unable to get all of the server info, skip the following in
            # that scenario
            if server_db_info.get('environment'):
                self.server_info_text.set(
                    f'Name:    {server_db_info.get("name")}\n\n'
                    f'Server OS:   {"Windows" if server_db_info.get("environment") == "w" else "Linux":<25}'
                    f'DayZ Version:   {server_db_info.get("version"):<25}'
                    f'Password Protected:   {bool_to_yes_no(server_db_info.get("password")):<25}'
                    f'VAC Enabled:   {bool_to_yes_no(server_db_info.get("vac")):<25}'
                    f'Shard:   {server_db_info.get("shard").title()}\n\n'
                    f'BattlEye:   {bool_to_yes_no(server_db_info.get("battlEye")):<35}'
                    f'First Person Only:   {bool_to_yes_no(server_db_info.get("firstPersonOnly")):<24}'
                    f'Time Acceleration:   {server_db_info.get("timeAcceleration")}{"x":<28}'
                    f'Last Joined:   {last_joined:<25}'
                )

                generate_server_mod_treeview(server_db_info)

                treeview_sort_column(self.server_mods_tv, 'Status', True)
            else:
                # Clear the existing info and treeview on the Server Info tab to prevent previously
                # selected server info from being displayed for a newly selected server that is down
                self.server_info_text.set('')
                self.server_mods_tv.delete(*self.server_mods_tv.get_children())


    def OnDoubleClick(self, event):
        """
        Used to open the Steam Workshop Mod URL when user double clicks
        either a Server Info treeview item or an Installed Mods treeview
        item. This allows the user to easily subscribe to missing mods.
        """
        widget = event.widget

        if widget == self.server_mods_tv and self.server_mods_tv.selection():
            item = self.server_mods_tv.selection()[0]
            url = self.server_mods_tv.item(item, 'values')[2]

        elif widget == self.installed_mods_tv and self.installed_mods_tv.selection():
            item = self.installed_mods_tv.selection()[0]
            url = self.installed_mods_tv.item(item, 'values')[3]

        self.open_steam_url(url)

    def toggle_favorite(self):
        """
        Adds or Removes the currently selected item in the Server List Treeview to
        or from the Favorites list stored in the dayz_py.json.
        """
        fav_state = self.favorite_var.get()

        if self.treeview.selection():
            ip, _, qport = get_selected_ip(self.treeview.selection()[0])
            server_db_info = SERVER_DB.get(f'{ip}:{qport}')

            if fav_state:
                print('Add to Favorite')
                settings['favorites'][f'{ip}:{qport}'] = {'name': server_db_info.get('name')}
            else:
                print('Remove from Favorite')
                settings['favorites'].pop(f'{ip}:{qport}', None)
                filter_treeview()
            save_settings_to_json()

        else:
            error_message = (
                f'No server is currently selected to add or remove from favorites. '
                f'Please select a server first.'
            )
            print(error_message)
            self.favorite_var.set(value=False)
            self.MessageBoxError(message=error_message)

    def check_favorites(self, ip, qport):
        """
        Check if the currently selected treeview item is a favorite. If so,
        set the 'Add/Remove Favorite' checkbox appropriately.
        """
        if f'{ip}:{qport}' not in settings.get('favorites'):
            self.favorite_var.set(value=False)
        else:
            self.favorite_var.set(value=True)

    def add_history(self, ip, qport):
        """
        Adds server to the History stored in the users dayz_py.json upon joining
        the server. Updates the timestamp if the history already exist.
        """
        settings['history'][f'{ip}:{qport}'] = {
            'name': SERVER_DB.get(f'{ip}:{qport}').get('name'),
            'last_joined': str(datetime.now().astimezone())
        }
        save_settings_to_json()

    def check_history(self, ip, qport):
        """
        Checks if the curently selected treeview item is in the History. If so,
        get the timestamp. Then format and return. Example format '2023-10-10 @ 14:09'.
        This is currently displayed as the Last Joined under the Server Info tab.
        """
        last_joined = 'Unknown'
        if f'{ip}:{qport}' in settings.get('history'):
            timestamp = settings.get('history').get(f'{ip}:{qport}').get('last_joined')
            dt_timestamp = datetime.strptime(settings.get('history').get(f'{ip}:{qport}').get('last_joined'), '%Y-%m-%d %H:%M:%S.%f%z')
            last_joined = dt_timestamp.strftime('%Y-%m-%d @ %H:%M')

        return last_joined

    def update_map_list(self):
        """
        Sets value of the map dropdown combobox in Tab 1 (Server List)
        """
        self.map_combobox['values'] = self.dayz_maps

    def clear_filters(self):
        """
        Resets filter/serach boxes back to default. Resets the treeview to an
        unfiltered state (Unhides/Reattaches 'detached' items). Removes treeview
        selection and restores checkboxs back to default.
        """
        # Clear Filter Boxes
        self.entry.delete('0', 'end')
        self.map_combobox.set(self.default_map_combobox_text)

        # Clear Server Info tab
        self.server_info_text.set('')
        self.server_mods_tv.delete(*self.server_mods_tv.get_children())

        # Reset previous filters
        restore_treeview()

        # Unselect previously clicked treeview item & Checkboxes
        self.treeview.selection_set([])
        self.show_favorites_var.set(value=False)
        self.favorite_var.set(value=False)
        self.show_history_var.set(value=False)

    def combobox_focus_out(self):
        """
        Sets the default text/string ('Map') in the Map dropdown/combobox
        (visible only when there is no map selected) and also refreshes the
        Treeview filters
        """
        self.map_combobox.set(self.default_map_combobox_text)
        filter_treeview()

    def on_tab_change(self, event):
        """
        Change which buttons/entries/labels are displayed depending on the tab selected.
        Currently the only widgets that are toggled are the ones on the right hand side.
        """
        selected_tab = self.notebook.index(self.notebook.select())
        if selected_tab == 0:
            # If "Server List" tab is selected
            self.refresh_all_button.grid(row=0, column=0, padx=5, pady=(0, 5), sticky='nsew')
            self.refresh_selected_button.grid(row=1, column=0, padx=5, pady=(5, 10), sticky='nsew')
            self.keypress_filter.grid(row=2, column=0, padx=5, pady=5, sticky='ew')
            self.entry.grid(row=3, column=0, padx=5, pady=5, sticky='ew')
            self.map_combobox.grid(row=4, column=0, padx=5, pady=5, sticky='ew')
            self.show_favorites.grid(row=5, column=0, padx=5, pady=5, sticky='ew')
            self.show_history.grid(row=6, column=0, padx=5, pady=5, sticky='ew')
            self.clear_filter.grid(row=7, column=0, padx=5, pady=5, sticky='nsew')
            self.separator.grid(row=8, column=0, padx=(20, 20), pady=10, sticky='ew')
            self.join_server_button.grid(row=9, column=0, padx=5, pady=5, sticky='nsew')
            self.favorite.grid(row=10, column=0, padx=5, pady=10, sticky='ew')

            # Hide widgets from all tabs except tab_1
            self.hide_tab_widgets(self.tab_1_widgets)

        elif selected_tab == 1:
            # If "Server Info" tab is selected
            # Hide widgets from all tabs except tab_2
            self.hide_tab_widgets(self.tab_2_widgets)

            self.refresh_info_button.grid(row=0, column=0, padx=5, pady=(0, 10), sticky='nsew')
            self.load_workshop_label.grid(row=1, column=0, padx=5, pady=(0, 10), sticky='nsew')
            self.refresh_info_label.grid(row=2, column=0, padx=5, pady=(0, 10), sticky='nsew')

        elif selected_tab == 2:
            # If "Installed Mods" tab is selected
            # Hide widgets from all tabs except tab_3
            self.hide_tab_widgets(self.tab_3_widgets)

            self.refresh_mod_button.grid(row=0, column=0, padx=5, pady=(0, 10), sticky='nsew')
            self.total_label.grid(row=1, column=0, padx=5, pady=10, sticky='nsew')

        else:
            for grid_item in self.grid_list:
                grid_item.grid_forget()

    def hide_tab_widgets(self, tab_list):
        """
        Used in the on_tab_change function to hide widgets when
        switching to a tab where the widget is not needed.
        """
        for grid_item in self.grid_list:
            if grid_item not in tab_list:
                grid_item.grid_forget()

    def open_steam_url(self, url):
        """
        Opens the mod in the Steam Workshop. Used for subscribing/downloading
        missing mods.
        """
        try:
            subprocess.Popen([steam_cmd, url])
        except subprocess.CalledProcessError as e:
            error_message = f'Failed to launch Steam Mod URL.\n\n{e}'
            print(error_message)
            app.MessageBoxError(error_message)

    def toggle_filter_on_keypress(self):
        """
        Enable or Disable filter on keypress. If disabled, enable filter on
        'FocusOut'
        """
        if self.keypress_filter_var.get():
            self.keypress_trace_id = self.filter_text.trace_add("write", lambda *args: filter_treeview())
            self.entry.unbind('<FocusOut>', self.focus_trace_id)
        else:
            self.filter_text.trace_remove("write", self.keypress_trace_id)
            self.focus_trace_id = self.entry.bind('<FocusOut>', lambda e: filter_treeview())

    def setup_widgets(self):
        # Create a Frame for input widgets
        self.widgets_frame = ttk.Frame(self, padding=(0, 0, 0, 10))
        self.widgets_frame.grid(
            row=0, column=1, padx=(0, 0), pady=(40, 5), sticky='nsew', rowspan=3
        )
        self.widgets_frame.columnconfigure(index=0, weight=1)

        # Notebook to hold the Tabs
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=0, column=0, padx=(25, 10), pady=(30, 10), sticky='nsew', rowspan=3)
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_change)

        # Tab #1 (Server List)
        self.tab_1 = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_1, text='Server List')

        # Scrollbar
        self.scrollbar = ttk.Scrollbar(self.tab_1)
        self.scrollbar.pack(side='right', fill='y')

        # Removes border around treeviews (This style is not used on the Server Info treeview)
        borderless_treeview = ttk.Style()
        borderless_treeview.layout("NoBorder.Treeview", [
            ('NoBorder.treearea', {'sticky': 'nswe'})
        ])

        cols = ('Map', 'Name', 'Players', 'Max', 'Gametime', 'IP:Port', 'Qport', 'Ping')
        # Server List Treeview
        self.treeview = ttk.Treeview(
            self.tab_1,
            selectmode='extended',
            show='headings',
            yscrollcommand=self.scrollbar.set,
            columns=cols,
            height=14,
            style="NoBorder.Treeview"
        )
        for col in cols:
            self.treeview.heading(col, text=col, anchor='w', command=lambda _col=col:
                                  treeview_sort_column(self.treeview, _col, False))

        self.treeview.pack(expand=True, fill='both')
        self.treeview.bind('<<TreeviewSelect>>', self.OnSingleClick)
        self.treeview.bind('<Double-1>', self.OnDoubleClick)
        # Right Click
        # self.treeview.bind("<Button-3>", lambda e: self.treeview.context_menu.post(e.x_root, e.y_root))
        # self.treeview.context_menu = tk.Menu(self.treeview, tearoff=0)
        # self.treeview.context_menu.add_command(label="Copy", command=self.copy_item)

        self.scrollbar.config(command=self.treeview.yview)

        # Treeview columns - Set default width
        self.treeview.column('Map', width=110)
        self.treeview.column('Name', width=460)
        self.treeview.column('Players', width=60)
        self.treeview.column('Max', width=45)
        self.treeview.column('Gametime', width=75)
        self.treeview.column('IP:Port', width=135)
        self.treeview.column('Qport', width=50)
        self.treeview.column('Ping', width=50)

        # Refresh All Servers Accentbutton
        self.refresh_all_button = ttk.Button(
            self.widgets_frame, text='Refresh All Servers', style='Accent.TButton', command=refresh_servers
        )

        # Refresh Selected server Accentbutton
        # self.refresh_selected_button = ttk.Button(
        #     self.widgets_frame, text='Refresh Selected', style='Accent.TButton', command=lambda: Thread(target=refresh_selected, daemon=True).start()
        # )
        # Refresh Selected server button
        self.refresh_selected_button = ttk.Button(
            self.widgets_frame, text='Refresh Selected', command=lambda: Thread(target=refresh_selected, daemon=True).start()
        )

        # Toggle real time filter update on every keypress
        self.keypress_filter_var = tk.BooleanVar(value=False)
        self.keypress_filter = ttk.Checkbutton(
            self.widgets_frame, text='Filter on Keypress', variable=self.keypress_filter_var, command=self.toggle_filter_on_keypress
        )

        # Filter/Search Entry Box
        self.filter_text = tk.StringVar()
        self.default_filter_text = 'Filter Server List    >>>'

        self.entry = ttk.Entry(self.widgets_frame, textvariable=self.filter_text)

        self.entry.bind('<Return>', lambda e: filter_treeview())
        self.entry.bind('<KP_Enter>', lambda e: filter_treeview())
        # Add 'trace' to filter on keypress. Store 'trace_id' in order to disable it
        # if the user wants to turn it off. When enabled, can cause lag when typing
        # when searching a large server list.
        # self.keypress_trace_id = self.filter_text.trace_add("write", lambda *args: filter_treeview())
        self.focus_trace_id = self.entry.bind('<FocusOut>', lambda e: filter_treeview())

        # Map List Combobox
        self.default_map_combobox_text = 'Map'
        self.map_combobox = ttk.Combobox(self.widgets_frame, values=self.dayz_maps)
        self.map_combobox.set(self.default_map_combobox_text)

        self.map_combobox.bind('<FocusIn>', lambda e: (
            self.map_combobox.set('') if self.map_combobox.get() == self.default_map_combobox_text else None)
        )
        self.map_combobox.bind('<FocusOut>', lambda e: self.combobox_focus_out() if self.map_combobox.get() == '' else app.map_combobox.selection_clear())
        self.map_combobox.bind('<Return>', lambda e: filter_treeview())
        self.map_combobox.bind('<KP_Enter>', lambda e: filter_treeview())
        self.map_combobox.bind('<<ComboboxSelected>>', lambda e: filter_treeview())

        # Show Only Favorites Filter Checkbutton
        self.show_favorites_var = tk.BooleanVar()
        self.show_favorites = ttk.Checkbutton(
            self.widgets_frame, text='Only Show Favorites', variable=self.show_favorites_var, command=filter_treeview
        )

        # Show Only History Filter Checkbutton
        self.show_history_var = tk.BooleanVar()
        self.show_history = ttk.Checkbutton(
            self.widgets_frame, text='Only Show History', variable=self.show_history_var, command=filter_treeview
        )

        # Clear Filters button
        self.clear_filter = ttk.Button(
            self.widgets_frame, text='Clear Filters', command=self.clear_filters
        )

        # Separator
        self.separator = ttk.Separator(self.widgets_frame)

        # Join Server Accentbutton
        self.join_server_button = ttk.Button(
            self.widgets_frame, text='Join Server', style='Accent.TButton', command=launch_game
        )

        # Add/Remove Favorite Checkbuttons
        self.favorite_var = tk.BooleanVar()
        self.favorite = ttk.Checkbutton(
            self.widgets_frame, text='Add/Remove Favorite', variable=self.favorite_var, command=self.toggle_favorite
        )

        # Tab #2 (Server Info)
        self.tab_2 = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_2, text='Server Info')

        self.tab_2.columnconfigure(0, weight=1)
        self.tab_2.rowconfigure(0, weight=2)
        self.tab_2.rowconfigure(1, weight=1)

        # Refresh Info Accentbutton
        self.refresh_info_button = ttk.Button(
            self.widgets_frame, text='Refresh Info', style='Accent.TButton', command=refresh_server_mod_info
        )

        # Load Mod in Steam Workshop Label
        self.load_workshop_label = ttk.Label(
            self.widgets_frame,
            text='Double-click mods to open\nin Steam Workshop.\nSubscribe to download.',
            justify='center',
            anchor='n',
        )

        # Refresh Info Label
        self.refresh_info_label = ttk.Label(
            self.widgets_frame,
            text='Click "Refresh Info" after\ninstalling missing mods.',
            justify='center',
            anchor='n',
        )

        # Server Info/Mods Tab - Treeview
        # Scrollbar
        self.server_mod_scrollbar = ttk.Scrollbar(self.tab_2)
        self.server_mod_scrollbar.grid(row=0, column=1, sticky='ns')

        # Server Mods Treeview
        server_mods_cols = ['Name', 'Workshop ID', 'Steam Workshop / Download URL', 'Status']
        self.server_mods_tv = ttk.Treeview(
            self.tab_2,
            # selectmode='browse',
            selectmode='extended',
            show='headings',
            yscrollcommand=self.server_mod_scrollbar.set,
            columns=server_mods_cols,
            height=14,
        )
        for col in server_mods_cols:
            self.server_mods_tv.heading(col, text=col, anchor='w', command=lambda _col=col:
                                  treeview_sort_column(self.server_mods_tv, _col, False))

        # self.server_mods_tv.pack(expand=True, fill='both')
        self.server_mods_tv.grid(row=0, column=0, padx=(0, 0), pady=(0, 0), sticky='nsew')
        self.server_mods_tv.bind('<Double-1>', self.OnDoubleClick)

        self.server_mod_scrollbar.config(command=self.server_mods_tv.yview)

        # Server Mods Treeview columns
        self.server_mods_tv.column('Name', width=250)
        self.server_mods_tv.column('Workshop ID', width=250)
        self.server_mods_tv.column('Steam Workshop / Download URL', width=400)
        self.server_mods_tv.column('Status', width=125)

        # Server Info Label & Textvariable (Below Server Mods Treeview)
        self.server_info_text = tk.StringVar()
        self.server_info_text.set('')

        self.label = ttk.Label(
            self.tab_2,
            textvariable=self.server_info_text,
            justify='center',
        )
        self.label.grid(row=1, column=0, padx=(75, 0), sticky='nsew')

        # Tab #3 (Installed Mods)
        self.tab_3 = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_3, text='Installed Mods')

        # Installed Mod Scrollbar
        self.mod_scrollbar = ttk.Scrollbar(self.tab_3)
        self.mod_scrollbar.pack(side='right', fill='y')

        # Installed Mods Treeview
        installed_mods_cols = ['Symlink', 'Name', 'Workshop ID', 'Steam Workshop / Download URL', 'Size (MBs)']
        self.installed_mods_tv = ttk.Treeview(
            self.tab_3,
            # selectmode='browse',
            selectmode='extended',
            show='headings',
            yscrollcommand=self.mod_scrollbar.set,
            columns=installed_mods_cols,
            height=14,
            style="NoBorder.Treeview"
        )
        for col in installed_mods_cols:
            self.installed_mods_tv.heading(col, text=col, anchor='w', command=lambda _col=col:
                                  treeview_sort_column(self.installed_mods_tv, _col, False))

        self.installed_mods_tv.pack(expand=True, fill='both')
        self.installed_mods_tv.bind('<Double-1>', self.OnDoubleClick)

        self.mod_scrollbar.config(command=self.installed_mods_tv.yview)

        # # Installed Mods Treeview columns
        self.installed_mods_tv.column('Symlink', width=65)
        self.installed_mods_tv.column('Name', width=200)
        self.installed_mods_tv.column('Workshop ID', width=100)
        self.installed_mods_tv.column('Steam Workshop / Download URL', width=350)
        self.installed_mods_tv.column('Size (MBs)', width=75)

        # Refresh Mods Accentbutton
        self.refresh_mod_button = ttk.Button(
            self.widgets_frame, text='Refresh Mods', style='Accent.TButton', command=generate_mod_treeview
        )

        # Total Label (Total size of installed mods)
        self.total_size_var = tk.StringVar()
        self.total_label = ttk.Label(
            self.widgets_frame,
            textvariable=self.total_size_var,
            justify='center',
            anchor='n'
        )

        # # Tab #4 (Settings)
        self.tab_4 = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_4, text='Settings')

        SettingsMenu(self.tab_4)

        # Switch (Toggle Dark/Light Mode)
        self.switch = ttk.Checkbutton(
            self.widgets_frame, style='Switch.TCheckbutton', command=change_theme
        )
        self.switch.grid(row=99, column=0, padx=5, pady=10, sticky='se')
        # Force Theme Switch to the bottom of the window
        self.widgets_frame.grid_rowconfigure(12, weight=5)

        # Sizegrip (Resize Window icon located at bottom right)
        self.sizegrip = ttk.Sizegrip(self)
        self.sizegrip.grid(row=100, column=100, padx=(0, 5), pady=(0, 5))

        # Button list Used to disable while server list populates
        self.button_list = [
            self.refresh_all_button,
            self.refresh_selected_button,
            self.clear_filter,
            self.join_server_button
        ]
        # List of grid used for enabling/disabling between Tab selection
        self.grid_list = [
            self.refresh_all_button,
            self.refresh_selected_button,
            self.keypress_filter,
            self.clear_filter,
            self.join_server_button,
            self.show_favorites,
            self.show_history,
            self.favorite,
            self.entry,
            self.map_combobox,
            self.separator,
            self.refresh_mod_button,
            self.refresh_info_button,
            self.total_label,
            self.refresh_info_label,
            self.load_workshop_label
        ]
        # Widgets to display on Tab 1
        self.tab_1_widgets = [
            self.refresh_all_button,
            self.refresh_selected_button,
            self.keypress_filter,
            self.entry,
            self.map_combobox,
            self.show_favorites,
            self.show_history,
            self.clear_filter,
            self.separator,
            self.join_server_button,
            self.favorite
        ]
        # Widgets to display on Tab 2
        self.tab_2_widgets = [
            self.refresh_info_button,
            self.load_workshop_label
            self.refresh_info_label
        ]
        # Widgets to display on Tab 3
        self.tab_3_widgets = [
            self.refresh_mod_button,
            self.total_label
        ]


class SettingsMenu:
    def __init__(self, master):
        self.master = master
        self.frame = ttk.Frame(master)
        self.frame.pack(padx=20, pady=20)

        # DayZ Directory selection
        self.dayz_dir_var = tk.StringVar(name='dayz_dir', value=settings.get('dayz_dir'))
        self.dayz_dir_label = tk.Label(self.frame, text='DayZ Install Directory:')
        self.dayz_dir_label.grid(row=0, column=0, padx=(0, 5), pady=(0, 10), sticky='e')
        self.dayz_dir_entry = ttk.Entry(self.frame, textvariable=self.dayz_dir_var, width=60)
        self.dayz_dir_entry.grid(row=0, column=1, pady=(0, 10))
        self.dayz_dir_button = ttk.Button(self.frame, text='Select', command=lambda: self.select_dir(self.dayz_dir_var))
        self.dayz_dir_button.grid(row=0, column=2, padx=5, pady=(0, 10))

        # Steam Directory selection
        self.steam_dir_var = tk.StringVar(name='steam_dir', value=settings.get('steam_dir'))
        self.steam_dir_label = tk.Label(self.frame, text='Steam Workshop Directory:')
        self.steam_dir_label.grid(row=1, column=0, padx=(0, 5), pady=(0, 10), sticky='e')
        self.steam_dir_entry = ttk.Entry(self.frame, textvariable=self.steam_dir_var, width=60)
        self.steam_dir_entry.grid(row=1, column=1, pady=(0, 10))
        self.steam_dir_button = ttk.Button(self.frame, text='Select', command=lambda: self.select_dir(self.steam_dir_var))
        self.steam_dir_button.grid(row=1, column=2, padx=5, pady=(0, 10))

        # Parameters
        self.parameters_var = tk.StringVar(value=settings.get('launch_params'))
        self.params_label = ttk.Label(self.frame, text='Addional Launch Parameters:')
        self.params_label.grid(row=2, column=0, padx=(0, 5), pady=(0, 10), sticky='e')
        self.params_entry = ttk.Entry(self.frame, textvariable=self.parameters_var, width=60)
        self.params_entry.grid(row=2, column=1, pady=(0, 10), sticky='e')
        self.params_entry.bind("<FocusOut>", self.on_entry_focus_change)

        # Profile name
        self.profile_name_var = tk.StringVar(value=settings.get('profile_name'))
        self.profile_label = ttk.Label(self.frame, text='Profile Name:')
        self.profile_label.grid(row=3, column=0, padx=(0, 5), pady=(0, 10), sticky='e')
        self.profile_entry = ttk.Entry(self.frame, textvariable=self.profile_name_var, width=60)
        self.profile_entry.grid(row=3, column=1, pady=(0, 10), sticky='e')
        self.profile_entry.bind("<FocusOut>", self.on_entry_focus_change)

        # Radio buttons for options
        self.install_options_label = ttk.Label(self.frame, text='Steam Install Type:')
        self.install_options_label.grid(row=4, column=0, padx=(0, 5), pady=(10, 10), sticky='e')

        self.install_var = tk.StringVar(value=settings.get('install_type'))  # Default value
        self.install1_button = ttk.Radiobutton(
            self.frame, text='Standard/Runtime', variable=self.install_var, value='steam', command=self.on_install_change
        )
        self.install1_button.grid(row=4, column=1, padx=(100, 0), sticky='w')

        self.install2_button = ttk.Radiobutton(
            self.frame, text='Flatpak', variable=self.install_var, value='flatpak', command=self.on_install_change
        )
        self.install2_button.grid(row=4, column=1, padx=(0, 100), sticky='e')

        # Theme selection
        self.theme_var = tk.StringVar(value=settings.get('theme'))
        self.theme_label = ttk.Label(self.frame, text='Default Theme/Mode:')
        self.theme_label.grid(row=5, column=0, padx=(0, 5), pady=(10, 10), sticky='e')

        self.dark_button = ttk.Radiobutton(
            self.frame, text='Dark', variable=self.theme_var, value='dark', command=self.on_theme_change
        )
        self.dark_button.grid(row=5, column=1, padx=(100, 0), sticky='w')

        self.light_button = ttk.Radiobutton(
            self.frame, text='Light', variable=self.theme_var, value='light', command=self.on_theme_change
        )
        self.light_button.grid(row=5, column=1, padx=(0, 114), sticky='e')

        # Load Favorites and History on Startup
        self.load_favs_var = tk.BooleanVar(value=settings.get('load_favs_on_startup'))
        self.load_favs_label = ttk.Label(self.frame, text='Load Favorites/History on Startup:')
        self.load_favs_label.grid(row=6, column=0, padx=(0, 5), pady=(10, 10), sticky='e')

        self.fav_enable_button = ttk.Radiobutton(
            self.frame, text='Enable', variable=self.load_favs_var, value=True, command=self.load_favs_startup_change
        )
        self.fav_enable_button.grid(row=6, column=1, padx=(100, 0), sticky='w')

        self.fav_disable_button = ttk.Radiobutton(
            self.frame, text='Disable', variable=self.load_favs_var, value=False, command=self.load_favs_startup_change
        )
        self.fav_disable_button.grid(row=6, column=1, padx=(0, 99), sticky='e')

        # Check for DayZ Py Launcher updates
        self.check_updates_var = tk.BooleanVar(value=settings.get('check_updates'))
        self.check_updates_label = ttk.Label(self.frame, text='Check for Launcher Updates:')
        self.check_updates_label.grid(row=7, column=0, padx=(0, 5), pady=(10, 10), sticky='e')

        self.updates_enable_button = ttk.Radiobutton(
            self.frame, text='Enable', variable=self.check_updates_var, value=True, command=self.check_updates
        )
        self.updates_enable_button.grid(row=7, column=1, padx=(100, 0), sticky='w')

        self.updates_disable_button = ttk.Radiobutton(
            self.frame, text='Disable', variable=self.check_updates_var, value=False, command=self.check_updates
        )
        self.updates_disable_button.grid(row=7, column=1, padx=(0, 99), sticky='e')

        # Max Values
        self.max_servers_var = tk.IntVar(value=settings.get('max_servers_display'))
        self.max_servers_label = ttk.Label(self.frame, text="Max Servers to Display (0 = No Limit):")
        self.max_servers_label.grid(row=8, column=0, padx=(0, 5), pady=(7, 10), sticky='e')
        self.max_servers_entry = ttk.Entry(self.frame, width=15, textvariable=self.max_servers_var)
        self.max_servers_entry.grid(row=8, column=1, pady=(7, 10), sticky='w')
        self.max_servers_entry.bind("<FocusOut>", self.on_entry_focus_change)

        self.max_pings_var = tk.IntVar(value=settings.get('max_sim_pings'))
        self.max_pings_label = ttk.Label(self.frame, text="Max Simultaneous Pings:")
        self.max_pings_label.grid(row=8, column=1, padx=(65, 0), pady=(7, 10))
        self.max_pings_entry = ttk.Entry(self.frame, width=15, textvariable=self.max_pings_var)
        self.max_pings_entry.grid(row=8, column=1, pady=(7, 10), sticky='e')
        self.max_pings_entry.bind("<FocusOut>", self.on_entry_focus_change)

        # Clear Favorites and History Buttons
        self.clear_favorites_button = ttk.Button(
            self.frame, text='Clear Favorites', command=lambda: self.clear_fav_history('Favorites')
        )
        self.clear_favorites_button.grid(row=9, column=1, padx=(65, 0), pady=(7, 10), sticky='w')

        self.clear_history_button = ttk.Button(
            self.frame, text='Clear History', command=lambda: self.clear_fav_history('History')
        )
        self.clear_history_button.grid(row=9, column=1, padx=(0, 95), pady=(7, 10), sticky='e')


    def select_dir(self, var):
        """
        Used to Prompt user for selecting DayZ and Steam install
        directories
        """
        global settings
        directory = filedialog.askdirectory()
        print(directory)
        if (directory and os.path.exists(directory)) or directory == '':
            var.set(directory)
            settings[str(var)] = directory
            save_settings_to_json()
        elif directory != ():
            error_message = 'Warning: The selected directory does not exist.'
            print(error_message)
            app.MessageBoxError(message=error_message)


    def on_entry_focus_change(self, event):
        """
        Used to save Entry box settings boxes once the focus moves away
        from the selected entry box.
        """
        global settings
        try:
            if event.widget == self.profile_entry:
                settings['profile_name'] = self.profile_name_var.get()

            elif event.widget == self.params_entry:
                settings['launch_params'] = self.parameters_var.get()

            elif event.widget == self.max_servers_entry:
                settings['max_servers_display'] = self.max_servers_var.get()

            elif event.widget == self.max_pings_entry:
                settings['max_sim_pings'] = self.max_pings_var.get()

            save_settings_to_json()

        except tk.TclError as tclerror:
            error_message = f'Invalid Entry. Must be a number.'
            print(error_message, tclerror)
            app.MessageBoxError(message=error_message)

    def on_install_change(self):
        """
        Save users settings whenever they change their Steam install type.
        Update steam_cmd to corresponding steam/flatpak command.
        """
        global settings, steam_cmd
        install_type = self.install_var.get()
        print(install_type)
        settings['install_type'] = install_type
        if 'flatpak' in install_type:
            steam_cmd = 'flatpak run com.valvesoftware.Steam'
        else:
            steam_cmd = 'steam'
        print(steam_cmd)
        save_settings_to_json()

    def on_theme_change(self):
        """
        Save users settings whenever they change the Theme.
        """
        global settings
        print(self.theme_var.get())
        root.tk.call('set_theme', self.theme_var.get())
        settings['theme'] = self.theme_var.get()
        save_settings_to_json()

    def load_favs_startup_change(self):
        """
        Save users settings whenever they change the option to enable
        or disable loading Favorites and History on App Startup.
        """
        global settings
        print(self.load_favs_var.get())
        settings['load_favs_on_startup'] = self.load_favs_var.get()
        save_settings_to_json()

    def check_updates(self):
        """
        Check repo for updates to DayZ Py Launcher.
        """
        global settings
        settings['check_updates'] = self.check_updates_var.get()
        save_settings_to_json()

    def clear_fav_history(self, button_identity):
        """
        Clears the users Favorites or History depending on the button they
        clicked in the Settings menu.
        """
        global settings
        ask_message = f'Are you sure you want to clear your {button_identity}?'
        answer = app.MessageBoxAskYN(message=ask_message)
        print(f'Clear {button_identity}:', answer)
        if answer:
            if button_identity == 'Favorites':
                settings['favorites'] = {}
            elif button_identity == 'History':
                settings['history'] = {}
            save_settings_to_json()


def save_settings_to_json():
    """
    Save settings to json configuation file.
    """
    with open(settings_json, 'w') as json_file:
        json.dump(settings, json_file, indent=4)


def load_settings_from_file():
    """
    Load settings to json configuation file. Alert user if corrupted.
    """
    global settings
    if os.path.exists(settings_json):
        with open(settings_json, 'r') as json_file:
            try:
                settings.update(json.load(json_file))
                # print(json.dumps(settings, indent=4))
            except json.decoder.JSONDecodeError:
                error_message = (
                    'Error: Unable to load Settings file. Not in valid json format.\n\n'
                    'Try reconfiguring settings.'
                )
                print(error_message)
                messagebox.showerror(message=error_message)


def server_pings(id, server_info):
    """
    Attempted to ping the server using the ping command. If that fails,
    since some servers block normal pings, perform an a2s query and use
    it's ping/response time.
    """
    ip = server_info[5].split(':')[0]
    qport = server_info[6]
    ping = get_ping_cmd(ip)

    if not ping:
        ping, _ = a2s_query(ip, qport)
    app.treeview.item(id, text='', values=server_info + (ping,))


def filter_treeview():
    global hidden_items

    # Gets values from Entry box
    filter_text = app.entry.get()
    # Gets values from Map combobox
    filter_map = app.map_combobox.get()

    # Clear Server Info tab
    app.server_info_text.set('')

    # Reset previous filters. If turned on, treeview is reset after every
    # filter update. Without it, you can 'stack' filters and search within
    # the current filtered view.
    if app.keypress_filter_var.get():
        restore_treeview()

    # Checks if entry and combobox values exist and are not the
    # default prefilled strings/text. i.e. Like 'Map' in the combobox
    text_entered = False
    if filter_text != '' and filter_text != app.default_filter_text:
        text_entered = True

    map_selected = False
    if filter_map != '' and filter_map != app.default_map_combobox_text:
        map_selected = True

    # Gets values from Only Show Favorites checkbox
    show_favorites = app.show_favorites_var.get()
    # Gets values from Only Show History checkbox
    show_history = app.show_history_var.get()

    # Check if ANY of the bools above are true. Then hides/detaches Treeview items
    # that do not match. Stores hidden items in the global 'hidden_items' list.
    bool_filter_list = [text_entered, map_selected, show_favorites, show_history]
    if any(bool_filter_list):
        for item_id in app.treeview.get_children():
            server_values = app.treeview.item(item_id, 'values')
            map_name = server_values[0]
            server_name = server_values[1]
            ip = server_values[5].split(':')[0]
            ip_port = server_values[5]
            qport = server_values[6]
            # str_values = str(server_values)
            if text_entered and filter_text.lower() not in server_name.lower() and filter_text not in ip_port:
                # print(f'Hiding: {server_values}')
                hide_treeview_item(item_id)

            if map_selected and filter_map.lower() not in map_name.lower():
                # print(f'Hiding: {server_values}')
                hide_treeview_item(item_id)
                # Remove highlight from selected entry
                # app.map_combobox.selection_clear()

            if show_favorites and not settings.get('favorites').get(f'{ip}:{qport}'):
                hide_treeview_item(item_id)

            if show_history and not settings.get('history').get(f'{ip}:{qport}'):
                hide_treeview_item(item_id)


def hide_treeview_item(item_id):
    """
    This hides/detaches Treeview items that do not match.
    Stores hidden items in the global 'hidden_items' list.
    """
    global hidden_items
    app.treeview.detach(item_id)
    hidden_items.add(item_id)


def restore_treeview():
    """
    This hides/detaches Treeview items that do not match.
    Stores hidden items in the global 'hidden_items' list.
    """
    global hidden_items
    for item_id in hidden_items:
        app.treeview.reattach(item_id, '', 'end')
        # print(f'Re-adding: {item_id}')
    treeview_sort_column(app.treeview, 'Players', True)
    hidden_items = set()


def generate_server_db(servers):
    """
    Generate the SERVER_DB from the DZSA API. Also, adds each map
    to the dayz_maps list which is used to populate the Map combobox
    """
    for server in servers:
        ip = server.get("endpoint").get("ip")
        qport = server.get("endpoint").get("port")
        server_map = server.get('map').title()

        SERVER_DB[f'{ip}:{qport}'] = {
            'sponsor': server.get('sponsor'),
            'profile': server.get('profile'),
            'nameOverride': server.get('nameOverride'),
            'mods': server.get('mods'),
            'game': server.get('game'),
            "endpoint": {
                "ip": ip,
                "port": qport
            },
            'name': server.get('name'),
            'map': server_map,
            'mission': server.get('mission'),
            'players': server.get('players'),
            'maxPlayers': server.get('maxPlayers'),
            'environment': server.get('environment'),
            'password': server.get('password'),
            'version': server.get('version'),
            'vac': server.get('vac'),
            'gamePort': server.get("gamePort"),
            'shard': server.get('shard'),
            'battlEye': server.get('battlEye'),
            'timeAcceleration': server.get('timeAcceleration'),
            'time': server.get('time'),
            'firstPersonOnly': server.get('firstPersonOnly')
        }

        # Generate Map list for Filter Combobox
        if server_map not in app.dayz_maps and server_map != '':
            app.dayz_maps.append(server_map)

    # Sort the dayzmap list ignoring case
    app.dayz_maps = sorted(app.dayz_maps, key=str.casefold)
    app.map_combobox['values'] = app.dayz_maps
    # print(app.dayz_maps)


def refresh_servers():
    """
    This downloads the Server List from DayZ Standalone launcher API.
    Only ran when user clicks the Refresh All Servers button.
    """
    # Disable buttons while Querying the API and Treeview Populates
    for button in app.button_list:
        button.configure(state='disabled')

    # Clear search filters and Server Info tab
    app.clear_filters()

    # Clear Treeview. Can probably revert to the Clear Treeview loop below.
    # Switched to this one at one point when working with threading the
    # pings to all servers. Ran into an issue where servers were still loading
    # into the treeview while also trying to be deleted in the event another
    # 'Request All Servers' was made before the previous one completed.
    while len(app.treeview.get_children()) > 0:
        app.treeview.delete(*app.treeview.get_children())
        # print(len(app.treeview.get_children()))
        time.sleep(0.5)

    # Clear Treeview
    # for item in app.treeview.get_children():
    #     app.treeview.delete(item)

    # DayZ SA Launcher API. Set the inital Treeview sort to be by total
    # players online. From Highest to Lowest.
    sort_column = 'players'
    dzsa_response = get_dzsa_data(dzsa_api_servers)
    if not dzsa_response:
        # Enable buttons now that API has failed. Allow user to try again
        for button in app.button_list:
            button.configure(state='enabled')
        return

    servers = sort_server_info(dzsa_response['result'], sort_column)

    generate_server_db(servers)

    # Loops through all the servers from DZSA API and return the info that is
    # being inserted into the treeview
    treeview_list = format_server_list_dzsa(servers)

    # This allows the user to only show the number of servers they want. Can
    # also help with performance since not have to unnecessarily load and ping
    # all servers. If set to 2,000, that would only display the top 2,000
    # highest populated servers. From testing, the API tends to return over 10,000
    # servers, but only about 2,500 tend to have players on them. Putting a limit
    # could also cause a server that just rebooted to be excluded/hidden from the
    # Treeview Server List. And another 'Refresh All Servers' would need to be
    # performed once the server had time to regain it's population.'
    MAX_TREEVIEW_LENGTH = settings.get('max_servers_display')
    print(f'Max Servers to Display: {MAX_TREEVIEW_LENGTH}')

    for i, tuple in enumerate(treeview_list):
        app.treeview.insert('', tk.END, values=tuple)

        if MAX_TREEVIEW_LENGTH and i == MAX_TREEVIEW_LENGTH:
            break

    # Enable buttons now that Treeview is Populated
    for button in app.button_list:
        button.configure(state='enabled')

    # Start a new thread and pass the arguments.
    # server_pings is the function that each thread will run.
    # app.treeview.get_children() is a list/tuple of all the Treeview Item numbers
    # treeview_list is the tuple values for each Treeview item.
    thread = Thread(target=thread_pool, args=(server_pings, app.treeview.get_children(), treeview_list), daemon=True)
    thread.start()


def thread_pool(server_pings, treeview_children, treeview_list):
    """
    This creates a new thread for each ping request to the servers. Sets Maximum number
    of simultaneous pings/workers to the user defined amount or a default of 20. If the
    amount of total servers to ping is less than the amount of of user defined Max, use the
    total number of servers as the max. Also, checks to make sure the user didn't define an
    amount less than 1.
    - server_pings is the function that each thread will run.
    - treeview_children is a list/tuple of all the Treeview Item numbers
    - treeview_list is the tuple values for each Treeview item.
    ThreadPoolExecutor will use 'map' to join the treeview_children and treeview_list which
    is then passed to the server_pings function in order to know which server to ping and
    which Treeview item to update.
    """
    MAX_WORKERS = settings.get('max_sim_pings')
    if MAX_WORKERS < 1:
        MAX_WORKERS = 1
    print(f'Max Simultaneous Pings: {MAX_WORKERS}')
    worker_count = len(treeview_list)
    if worker_count > MAX_WORKERS:
        worker_count = MAX_WORKERS

    try:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = list(executor.map(server_pings, treeview_children, treeview_list))

        # print(futures)
        # for future in futures:
        #     print(future)
        #     # print(f'done={future.done()}')
    except tk.TclError as te:
        print(f'User probably "Refreshed All Servers" again before first one completed: {te}')


# TODO Build function for handling v1 Query
def refresh_selected():
    """
    For the currently selected server in the 'Server List' tab_1, directly query
    the server for an info, mod and ping update. Then update the existing
    treeview item
    """
    items = app.treeview.selection()
    for id in items:
        item_values = app.treeview.item(id, 'values')

        ip, port = item_values[5].split(':')
        qport = item_values[6]

        ping, _ = a2s_query(ip, qport)
        a2s_mods(ip, qport)

        server_dict = SERVER_DB[f'{ip}:{qport}']
        # Since we are manually inserting servers into the DB (i.e. Favorites and History)
        # that may be down or unable to get all of the server info, skip the following in
        # that scenario
        if server_dict.get('environment'):
            server_info = format_server_list_dzsa([server_dict])

            if ping:
                app.treeview.item(id, text='', values=server_info + (ping,))
                # app.update_idletasks()
            app.OnSingleClick('')


def encode(id):
    """
    Gets the first 8 characters of the md5 hashed mod id. Used for symlink name.
    Unsure if there's a specific need for the encoding, or why not just use the
    mod name like the Official DayZ Launcher. Other Linux based DayZ Launchers
    were using the same/similar method. So, just following suite to prevent
    running into unforeseen issues.
    """
    encoded_id = hashlib.md5(f'{id}\n'.encode('utf-8')).hexdigest()[:8]
    # print(encoded_id)
    return encoded_id


def remove_broken_symlinks(symlink_dir):
    """
    Removes symlinks to mods that have been uninstalled
    """
    with os.scandir(symlink_dir) as entries:
        # print(entries)
        for entry in entries:
            # print(entry)
            if entry.name.startswith('@') and entry.is_symlink() and not entry.is_dir():
                # print(f'Removing broken symlink: {entry.name}')
                os.unlink(entry.path)


def create_symlinks(workshop_dir, symlink_dir):
    """
    Creates symlinks to mods that have been installed from the Steam
    Workshop. Seems to be an issue with DayZ loading mods from Linux
    directories, so the symlinks are created in the DayZ install
    directory.
    """
    mods = [f.name for f in os.scandir(workshop_dir) if f.is_dir()]
    for mod in mods:
        mod_path = os.path.join(workshop_dir, mod)
        meta_path = os.path.join(mod_path, 'meta.cpp')
        with open(meta_path) as f:
            contents = f.read()

            lines = contents.strip().split('\n')

            for line in lines:
                if 'name' in line:
                    key, value = map(str.strip, line.split('='))
                    name = value[1:-2]
                if 'publishedid' in line:
                    key, value = map(str.strip, line.split('='))
                    id = value[:-1]

        symlink = os.path.join(symlink_dir, f'@{encode(id)}')

        if not os.path.islink(symlink) and not os.path.exists(symlink):
            # print(f'Creating Symlink for: {name}')
            os.symlink(mod_path, symlink)
        # else:
            # print(f'Mod Already Symlinked: {name}')


def format_server_list_dzsa(servers):
    """
    Loops through all the servers and appends each server tuple to the
    list which will then be used to create the Treeview.
    """
    # print(servers)
    treeview_list = []
    server_count = len(servers)
    for server in servers:
        map_name = server.get('map').title()
        name = server.get('name')
        players = server.get('players')
        max_players = server.get('maxPlayers')
        ip = server.get('endpoint').get('ip')
        qport = server.get('endpoint').get('port')
        port = server.get('gamePort')
        ip_port = f'{ip}:{port}'
        time = server.get('time')

        server_info = (map_name, name, players, max_players, time, ip_port, qport)

        if server_count > 1:
            treeview_list.append(server_info)
        else:
            treeview_list = server_info

    return treeview_list


def get_installed_mod_ids(directory):
    """
    Loops through all the folders in the Steam Workshop directory to
    return a list of all the folder names which is also the Steam
    Workshop ID.
    """
    installed_mods = sorted([f.name for f in os.scandir(directory) if f.is_dir()])
    # print(installed_mods)

    return installed_mods


def get_mod_name(file):
    """
    Opens the file passed, in this case the Steam Mod meta.cpp file, which
    contains the mod info. Used to get the Name of the Mod when generating
    the MOD_DB
    """
    contents = file.read()
    lines = contents.strip().split('\n')

    for line in lines:
        if 'name' in line:
            key, value = map(str.strip, line.split('='))
            name = value[1:-2]
            return name


def get_installed_mods(directory):
    """
    Loops through all the folders in the Steam Workshop directory to
    generate the MOD_DB which stores all the locally installed mod's
    Steam Workshop ID, Mod Name and the size of the mod. Also, gets the
    total size of the Mod directory and is displayed on the right side
    of Tab 3 (Installed Mods)
    """
    global MOD_DB
    # Loop through all items in the directory. Add to list if dir and name of dir begins with @. Sort the list and ignore case
    # symlinks = [f.name for f in os.scandir(directory) if f.is_dir() and f.name.startswith('@')]
    MOD_DB = {f.name: {} for f in os.scandir(directory) if f.is_dir()}
    total_size = 0

    for mod in MOD_DB.keys():
        mod_path = os.path.join(f'{directory}/{mod}')
        # print(mod_path)
        mod_size = 0
        for dirpath, dirnames, filenames in os.walk(mod_path):
            # print(dirpath, dirnames, filenames)
            for f in filenames:
                fp = os.path.join(dirpath, f)
                mod_size += os.path.getsize(fp)
                # print(mod_size)
                if f == 'meta.cpp':
                    with open(fp) as file:
                        mod_name = get_mod_name(file)
                        # print(mod_name)
        # print(mod_size)

        total_size += mod_size
        MOD_DB[mod] = {
            'name': mod_name,
            'size': f'{round(mod_size / (1024 ** 2), 2):,}', # Size in MBs
            # 'size': round(mod_size / (1024 ** 2), 2),
            'url': f'{workshop_url}{mod}'
        }

    # MOD_DB['total_size'] = round(total_size / (1024 ** 3), 2)
    # MOD_DB['total_size'] = total_size # Size in bytes

    # Convert to GB or MB based on the size
    if total_size >= 1024**3:  # If size is >= 1 GB
        total_size = f'{round(total_size / (1024**3), 2)} GBs'
    else:  # If size is < 1 GB
        total_size = f'{round(total_size / (1024**2), 2)} MBs'

    app.total_size_var.set(f'Total Size of Installed Mods\n{total_size}')
    # print(json.dumps(MOD_DB, indent=4))


def refresh_server_mod_info():
    """
    Updates/Rescans installed mods and updates (Tab 3) Installed Mods
    Treeview. Then forces the Server Info tab update by running the
    OnSingleClick function which rechecks Server mods against the locally
    installed mods. Excuted when user clicks the 'Refresh Info' button
    and would typically be used after installing/subscribing to missing
    mods.
    """
    generate_mod_treeview()

    app.OnSingleClick('')


def generate_server_mod_treeview(server_info):
    """
    Generates the server mods treeview in the 'Server Info' Tab 2.
    Loops through each mod running on the server and compares it
    against the locally installed mods. If missing, sets the font
    color to Red.
    """
    app.server_mods_tv.delete(*app.server_mods_tv.get_children())

    for mod in server_info.get('mods'):
        # print(mod)
        workshop_id = mod.get('steamWorkshopId')
        # print(MOD_DB)
        if MOD_DB.get(str(workshop_id)):
            status = 'Installed'
            tag = ''
        else:
            status = 'Missing'
            tag = 'red'

        app.server_mods_tv.insert('', tk.END, tags=(tag,), values=(
            mod.get('name'),
            workshop_id,
            f'{workshop_url}{workshop_id}',
            status
            )
        )
    app.server_mods_tv.tag_configure("red", foreground="red")


def generate_mod_treeview():
    """
    Generates the installed mods treeview in the 'Installed Mods' Tab 3.
    Checks for broken symlinks, removes if necessary. Creates symlinks
    for installed mods.
    """
    # workshop_dir = settings.get('steam_dir')
    workshop_dir = os.path.join(settings.get('steam_dir'), f'content/{app_id}')
    # symlink_dir = os.path.join(settings.get('dayz_dir'), '!dayz_py')
    symlink_dir = settings.get('dayz_dir')

    remove_broken_symlinks(symlink_dir)
    create_symlinks(workshop_dir, symlink_dir)

    app.installed_mods_tv.delete(*app.installed_mods_tv.get_children())
    get_installed_mods(workshop_dir)

    for mod, info in MOD_DB.items():
        # print(mod, info)
        # if mod != 'total_size':
        app.installed_mods_tv.insert('', tk.END, values=(
            f'@{encode(mod)}',
            info.get('name'),
            mod,
            info.get('url'),
            info.get('size')
            )
        )
        # else:
        #     app.installed_mods_tv.insert('', tk.END, values=('', '', '', 'Total Size', f'{info} GBs'))


def compare_modlist(server_mods, installed_mods):
    """
    Check if all mods on server are installed locally
    """
    missing_mods = False
    for id, name in server_mods.items():
        # print(id, name)
        if str(id) not in installed_mods:
            message = f'Missing Mod: {name}'
            print(message)
            # info(message)
            # warn(message)
            missing_mods = True

    return missing_mods


def generate_mod_param_list(server_mods):
    """
    Generates the ';' separated mod directory/symlink list that is
    appended to the Launch Command
    """
    encoded_mod_list = []
    # Loop through the server mods IDs and append encoded ID to list. This encoded ID
    # is the same one used to create the symlink and is used in the DayZ launch parameters
    # to tell it where to locate the installed mod.
    for id in server_mods.keys():
        encoded_mod_list.append(f'@{encode(id)}')

    # Convert the encoded mod list into a string. Each mod is separted by ';'.
    mod_str_list = ';'.join(encoded_mod_list)
    # Command has to be in a list when passed to subprocess.
    mod_params = [f'"-mod={mod_str_list}"']

    return mod_params


def get_selected_ip(item):
    """
    Gets the IP and Port info from the currently selected entry
    in the 'Server List' tab. Handle the exception for a server
    in the favorites or history where it may not have the Port
    (gamePort) info in the event that the server was down or
    there were conenctivity issues during the initial query.
    """
    item_values = app.treeview.item(item, 'values')

    ip, port = item_values[5].split(':')
    qport = item_values[6]

    return ip, port, qport


def launch_game():
    """
    Executed when user selects a server and clicks the Join Server button
    """
    # Check if 'Profile Name' is blank. If so, alert user. Some servers will
    # kick you for using the default 'Survivor' profile name. So, I'm leaving
    # the default blank in order to force the user to set one.
    if not settings.get('profile_name'):
        error_message = 'No Profile Name is currently set.\nCheck the Settings tab, then try again.'
        app.MessageBoxError(message=error_message)
        return

    steam_running = check_steam_process()
    print('Steam Running:', steam_running)
    if not steam_running:
        ask_message = "Steam isn't running.\nStart it?"
        answer = app.MessageBoxAskYN(message=ask_message)
        print('Start Steam:', answer)
        if not answer:
            error_message = 'Steam is required for DayZ.\nCancelling "Join Server"'
            app.MessageBoxError(message=error_message)
            return

    dayz_running = check_dayz_process()
    print('DayZ Running:', dayz_running)
    if dayz_running:
        warn_message = 'DayZ is already running.\nClose the game and try again'
        app.MessageBoxWarn(message=warn_message)
        return

    if linux_os and not check_max_map_count():
        error_message = 'Unable to update max_map_count.\nCancelling "Join Server"'
        app.MessageBoxError(message=error_message)
        return

    # Get currently selected treeview item/server
    item = app.treeview.selection()[0]
    # Get IP and Ports info
    ip, port, qport = get_selected_ip(item)

    workshop_dir = os.path.join(settings.get('steam_dir'), f'content/{app_id}')
    # Get list of installed mod ID from the Steam Workshop directory
    installed_mods = get_installed_mod_ids(workshop_dir)
    # print(installed_mods)
    # Query the server directly for current mods.
    server_mods = a2s_mods(ip, qport)

    # If failed to get mods directly from the server, fail over to using the mods
    # previously stored in the SERVER_DB
    if server_mods:
        missing_mods = compare_modlist(server_mods, installed_mods)
    else:
        message = f'Failed getting mods directly from server ({ip}, {qport}. Using existing SERVER_DB mod list.)'
        print(message)
        missing_mods = compare_modlist(get_serverdb_mods(ip, qport), installed_mods)

    # Alert user that mods are missing
    if missing_mods:
        error_message = 'Unable to join server. Check the "Server Info" tab for missing mods'
        print(error_message)
        app.MessageBoxError(message=error_message)
        return

    # Create the list of commands/parameters that will be passed to subprocess to load the game with mods
    # required by the server along with any additional parameters input by the user
    default_params = [
        steam_cmd,
        '-applaunch',
        app_id,
        f'-connect={ip}:{port}',
        f'-name={settings.get("profile_name")}',
        '-nolauncher',
        '-nosplash',
        '-skipintro',
    ]

    launch_cmd = default_params

    # Append Additional parameters input by the user to launch command.
    if settings.get('launch_params'):
        print('Setting additional parameters.')
        steam_custom_params = settings.get('launch_params').strip().split(' ')
        launch_cmd = launch_cmd + steam_custom_params

    # Generate mod parameter list and append to launch command
    if server_mods and not missing_mods:
        print('Setting mod parameter list.')
        mod_params = generate_mod_param_list(server_mods)
        # Append mod param to launch command
        launch_cmd = launch_cmd + mod_params

    # launch_cmd = default_params + steam_custom_params + [mod_params]
    print(f'{launch_cmd=}')
    str_command = " ".join(launch_cmd)
    print(f'Using launch command: {str_command}')

    try:
        subprocess.Popen(launch_cmd)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(e)
        error_message = f'Failed to launch DayZ.\n\n{e}'
        app.MessageBoxError(error_message)

    # Add server to user's History'
    app.add_history(ip, qport)


def seconds_to_milliseconds(seconds):
    """
    Convert seconds to milliseconds. Used for the a2s ping.
    """
    return round(seconds * 1000)


def check_steam_process():
    """
    Check if Steam is running
    """
    try:
        if linux_os:
            output = subprocess.check_output(['pgrep', '-f', 'Steam/ubuntu12_64'])
            # print(output.decode())
        else:
            output = subprocess.check_output(['powershell', 'Get-Process "steam" | Select-Object -ExpandProperty Id'], text=True)
            # print("Process IDs:", output)
        return True
    except subprocess.CalledProcessError:
        return False


def check_dayz_process():
    """
    Check if DayZ is running
    """
    try:
        if linux_os:
            output = subprocess.check_output(['pgrep', '-f', 'DayZ.*exe'])
            # print(output.decode())
        else:
            output = subprocess.check_output(['powershell', 'Get-Process "DayZ" | Select-Object -ExpandProperty Id'], text=True)
            # print("Process IDs:", output)
        return True
    except subprocess.CalledProcessError:
        return False


def check_max_map_count():
    """
    DayZ requires the vm.max_map_count to be increased or else it crashes upon loading.
    Check if users vm.max_map_count is at least 1048576. If not, prompt for sudo password
    in order to execute the command to increase the vm.max_map_count.
    """
    try:
        output = subprocess.check_output(['sysctl', 'vm.max_map_count'], universal_newlines=True)
        value = output.split('=')[1].strip()
        print('Current vm.max_map_count:', value)

        if int(value) >= 1048576:
            return True

        else:
            # answer = messagebox.askyesno(title=None, message='Increase sysctl max_map_count? Requires sudo.')
            # if answer:
            sudo_password = simpledialog.askstring('Password Entry',
                f'Increase sysctl max_map_count?\n'
                f'{"":<7}Required for DayZ to load.\n\n'
                f'{"":<10}Enter sudo password:',
                show='*',
                parent=root
            )
            if sudo_password:
                try:
                    command = ['sudo', '-S', 'sysctl', '-w', 'vm.max_map_count=1048576']
                    result = subprocess.run(
                        command,
                        input=sudo_password,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=True
                    )
                    print("Output:", result)
                    return True
                except subprocess.CalledProcessError as e:
                    MessageBoxError(message='Command failed. Check your password.')
                    print("Command failed with exit status", e.returncode)
                    print("Error output:", e.stderr)
                    return False

    except subprocess.CalledProcessError as e:
        MessageBoxError(message='Failed to get max_map_count')
        print("Error:", e)
        return False


def a2s_query(ip, qport, update: bool=True):
    """
    Use the a2s module to query the server 'info' directly using the server's
    IP and Query Port (separte from the game port). Update the SERVER_DB with
    latest info and get the ping response time.

    Source: https://github.com/Yepoleb/python-a2s
    """
    try:
        # print(ip, port, qport)
        info = a2s.info((ip, int(qport)))
        # print(info)
        if 'etm' in info.keywords:
            timeAcceleration = int(info.keywords.split('etm')[1].split('.')[0])
        else:
            timeAcceleration = None

        server_update = {
            'map': info.map_name,
            'players': info.player_count,
            'maxPlayers': info.max_players,
            'environment': info.platform,
            'password': info.password_protected,
            'version': info.version,
            'vac': info.vac_enabled,
            'gamePort': info.port,
            'timeAcceleration': timeAcceleration,
            'time': info.keywords[-5:],
            'shard': 'private' if 'privHive' in info.keywords else 'public',
            'battlEye': True if 'battleye' in info.keywords else False,
            'firstPersonOnly': True if 'no3rd' in info.keywords else False,
            'endpoint': {
                'ip': ip,
                'port': int(qport)
            },
        }

        if update:
            SERVER_DB[f'{ip}:{qport}'].update(server_update)
        else:
            SERVER_DB[f'{ip}:{qport}'] = (server_update)
            SERVER_DB[f'{ip}:{qport}']['name'] = info.server_name
            SERVER_DB[f'{ip}:{qport}']['mods'] = []

        ping = seconds_to_milliseconds(info.ping)

    except TimeoutError:
        # message = f'Timed out getting info/ping from Server {ip} using Qport {qport}'
        # print(message)
        ping = 999
        info = None
    except IndexError as ie:
        message = f'IndexError from Server {ip} using Qport {qport}'
        print(message, ie)
        print(info)
        ping = 999
        info = None
    except KeyError as ke:
        message = f'KeyError from Server {ip} using Qport {qport}'
        print(message, ke)
        print(info)
        print(ip, qport)
        print(json.dumps(SERVER_DB, indent=4))
        ping = 999
        info = None

    return ping, info


def a2s_mods(ip, qport):
    """
    Queries the server directly to get the mods it's currently running.
    Updates the SERVER_DB in the DZSA format (List of Dictionaries).
    [{
        "name": "Community Framework",
        "steamWorkshopId": 1559212036
    }]
    Returns Dictionary of all mods where the key is the Steam workshop ID
    and the value is the name of the mod.
    { "1559212036": "Community Framework" }

    Source: https://github.com/Yepoleb/dayzquery
    """
    try:
        # print(ip, port, qport)
        mods = dayzquery.dayz_rules((ip, int(qport))).mods
        mods_dict = {}
        server_mod_list = []

        api_mod_list = SERVER_DB[f'{ip}:{qport}']['mods']
        # print(json.dumps(SERVER_DB[f'{ip}:{qport}']['mods'], indent=4))

        for mod in mods:
            # print(mod)
            mods_dict[mod.workshop_id] = mod.name
            server_mod_list.append({'name': mod.name, 'steamWorkshopId': mod.workshop_id})

        # api_mod_list = update_mod_list(api_mod_list, server_mod_list)
        # print(json.dumps(mods_dict, indent=4))    w
        SERVER_DB[f'{ip}:{qport}']['mods'] = update_mod_list(api_mod_list, server_mod_list)

    except TimeoutError:
        message = f'Timed out getting mods from Server {ip} using Qport {qport}'
        print(message)
        mods_dict = None

    return mods_dict


def get_ping_cmd(ip):
    """
    Run the ping command and capture the output
    """
    try:
        if linux_os:
            command = ['ping', '-c', '1', '-W', '1', ip]

        elif windows_os:
            command = ['ping', ip, '-n', '1', '-w', '1000']

        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        # Check if the command was successful
        if result.returncode == 0:
            # Use regular expressions to extract ping time in milliseconds
            ping_time_match = re.search(r"time=([\d.]+) ms", result.stdout)
            # print(ping_time_match)
            if ping_time_match:
                ping = ping_time_match.group(1)
                # print(ping)
                return round(float(ping))
            else:
                return None
        else:
            return None
            print("Error: " + result.stderr)
    except Exception as e:
        return None
        print("Exception: " + str(e))


def update_mod_list(list1, list2):
    """
    Update the DZSA generated list with ones from the server. But try to preserve
    the mod names from DZSA. Some mod names on the servers are different
    than DZSA and Steam
    list1 = DZSA Mod list
    list2 = Server Mod list
    """
    # Extract the steamWorkshopIds from each list
    ids_list1 = set(item['steamWorkshopId'] for item in list1)
    ids_list2 = set(item['steamWorkshopId'] for item in list2)

    # Add new items from list2 to list1
    for item in list2:
        if item['steamWorkshopId'] not in ids_list1:
            list1.append(item)

    # Remove items from list1 that are not in list2
    list1[:] = [item for item in list1 if item['steamWorkshopId'] in ids_list2]

    return list1


# Standalone Launcher
def get_dzsa_data(url):
    """
    Retrieves server list/data from the DayZ Standalone Launcher API.
    Had fairly common issues with the API timing out.
    """
    try:
        session = requests.Session()
        retry = Retry(connect=5, backoff_factor=1.0)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('https://', adapter)

        api_timeout = True
        count = 1
        while api_timeout and count <= 5:
            response = session.get(url, headers=headers)
            if json.loads(response.content).get('error') == 'Timeout has occurred':
                count += 1
                time.sleep(1)
            else:
                api_timeout = False

        if api_timeout:
            warn_message = 'DZSA API Timeout has occured. Try again.'
            print(warn_message)
            app.MessageBoxWarn(message=warn_message)
            return None

        if response.status_code == 200:
            return json.loads(response.content)
        else:
            print(f'HTTP Status Code: {response.status_code}')
            return None

    except requests.exceptions.ConnectionError as e:
        error_message = f'Error connecting to DZSA API:\n{e}'
        print(error_message)
        app.MessageBoxError(message=error_message)
        return None

    except json.decoder.JSONDecodeError as e:
        error_message = f'Invalid response from DZSA API:\n{e}\n\nTry again shortly.'
        print(error_message)
        app.MessageBoxError(message=error_message)
        return None


def load_fav_history():
    """
    This will parse the saved settings json, directly query each server and
    add them to the Server List treeview and SERVER_DB when the app starts.
    Allows you to use the app without the need of downloading all the servers
    from DZSA if you don't need them.
    """
    # Get all IP:Qports & server 'names' from Favorites and History
    # Merge favorites and history into one dict.
    fav_history = settings.get('favorites') | settings.get('history')

    for server, values in fav_history.items():
        ip, qport = server.split(':')
        stored_name = values.get('name')
        # Specify 'False' for the update argument in order to trigger an
        # insert into the SERVER_DB instead of an update. Also, creates
        # necessary keys in the SERVER_DB for future query updates
        ping, info = a2s_query(ip, qport, False)
        if info:
            a2s_mods(ip, qport)
            server_map = info.map_name.title()
            server_name = info.server_name
            players = info.player_count
            maxPlayers = info.max_players
            gamePort = info.port
            time = info.keywords[-5:]

            treeview_values = [server_map, server_name, players, maxPlayers, time, f'{ip}:{gamePort}', qport, ping]
            app.treeview.insert('', tk.END, values=treeview_values)

            # Generate Map list for Filter Combobox
            if server_map not in app.dayz_maps and server_map != '':
                app.dayz_maps.append(server_map)

        else:
            # If the server is down or unreachable, just insert info stored in favorites/history
            treeview_values = ['Server Down', stored_name, '', '', '', f'{ip}:{""}', qport, '']
            app.treeview.insert('', tk.END, values=treeview_values)
            SERVER_DB[f'{ip}:{qport}'] = {'name': stored_name, 'mods': []}

    app.dayz_maps = sorted(app.dayz_maps)
    app.map_combobox['values'] = app.dayz_maps


def get_serverdb_mods(ip, qport):
    """
    Returns Dictionary from the SERVER_DB of all mods where the key
    is the Steam workshop ID and the value is the name of the mod.
    { "1559212036": "Community Framework" }
    """
    mods_dict = {}
    for mod in SERVER_DB[f'{ip}:{qport}']['mods']:
        mods_dict[mod.get('steamWorkshopId')] = mod.get('name')

    return mods_dict


def bool_to_yes_no(bool):
    """
    This just returns Yes or No depending if bool was True or False.
    Used for populating the Server Info and displaying Yes/No instead
    of True/False.
    """
    bools = ('No','Yes')
    return bools[bool]


def sort_server_info(servers, column):
    """
    Sort list of servers by specified column/key. Used to sort the initial Server List
    view by Most Populated servers first (total players)
    """
    return sorted(servers, key=lambda x: x[column], reverse=True)


def treeview_sort_column(tv, col, reverse):
    """
    This Sorts a column when a user clicks on a column heading in a treeview.
    Convert treeview values to float before sorting columns where needed.
    https://stackoverflow.com/questions/67209658/treeview-sort-column-with-float-number
    Possibe TODO: add proper sorting of IP addresses
    """

    # Use casefold to make the sorting case insensitive
    l = [(tv.set(k, col).casefold(), k) for k in tv.get_children('')]

    try:
        # Used for sorting numerically. Mainly to handle the mod size column and other int
        l.sort(key=lambda t: float(t[0].replace(",","")), reverse=reverse)
    except:
        # Sort all other columns
        l.sort(reverse=reverse)

    # Re-arrange items in sorted positions
    for index, (val, k) in enumerate(l):
        tv.move(k, '', index)

    # Reverse sort next time
    tv.heading(col, text=col, command=lambda _col=col:
                treeview_sort_column(tv, _col, not reverse))


def windows_dark_title_bar(root):
    '''
    Dark Mode Title Bar for Windows
    https://gist.github.com/Olikonsti/879edbf69b801d8519bf25e804cec0aa
    https://www.youtube.com/watch?v=4Gi1sKKn_Ts
    '''
    root.update()
    DWWMA_USE_IMMERSIVE_DARK_MODE = 20
    set_window_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
    get_parent = ctypes.windll.user32.GetParent
    hwnd = get_parent(root.winfo_id())
    renduring_policy = DWWMA_USE_IMMERSIVE_DARK_MODE
    value = 2
    value = ctypes.c_int(value)
    set_window_attribute(hwnd, renduring_policy, ctypes.byref(value), ctypes.sizeof(value))


def change_theme():
    """
    Used for the toggle switch at the bottom right corner to alternate between
    Dark and Light mode/theme.
    NOTE: The theme's real name is azure-<mode>
    """

    if root.tk.call('ttk::style', 'theme', 'use') == 'azure-dark':
        # Set light theme
        root.tk.call('set_theme', 'light')
    else:
        # Set dark theme
        root.tk.call('set_theme', 'dark')


def detect_install_directories():
    """
    Fairly basic attempt at automatically detecting and settings the users DayZ
    and Steam Workshop mod directories. Uses the vdf2json module to parse Steam's
    vdf file which stores the workshop folders for each game.
    """
    # Set default directories for Linux
    if linux_os:
        home_dir = os.path.expanduser('~')
        default_steam_dir = f'{home_dir}/.local/share/Steam'
        vdfDir = f'{default_steam_dir}/steamapps/'

    # Set default directories for Windows
    elif windows_os:
        default_steam_dir = 'C:\\Program Files (x86)\\Steam'
        vdfDir = f'{default_steam_dir}\\config\\'

    # Use Steam's 'libraryfolders.vdf' to find DayZ and Steam Workshop directories
    # Idea from https://github.com/aclist/dztui
    vdfFile = os.path.join(vdfDir, 'libraryfolders.vdf')

    if (settings.get('dayz_dir') == '' or not os.path.exists(settings.get('dayz_dir'))) and os.path.isfile(vdfFile):

        with open(vdfFile, 'r') as file:
            steam_json = json.loads(vdf2json(file))

        for entry in steam_json.get('libraryfolders').values():
            # print(entry)
            if app_id in entry.get('apps'):
                path = entry.get('path')
                # print(path)

        settings['dayz_dir'] = os.path.join(path, 'steamapps/common/DayZ')
        settings['steam_dir'] = os.path.join(path, f'steamapps/workshop')

    # if not os.path.exists(os.path.join(settings.get('dayz_dir'), '!dayz_py')):
    #     os.makedirs(os.path.join(settings.get('dayz_dir'), '!dayz_py'))

    # profile = settings.get('profile_name')
    # game_dir = settings.get('dayz_dir')
    # workshop_dir = settings.get('steam_dir')
    # steam_custom_params = settings.get('launch_params')


def apply_windows_gui_fixes():
    """
    # Fixes Taskbar icon showing Python icon instead of App Icon
    # https://github.com/PySimpleGUI/PySimpleGUI/issues/5215
    """
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(appName)

    # Enable Dark Title bar if also using App dark mode/theme
    if settings.get('theme') == 'dark':
        windows_dark_title_bar(root)


def check_platform():
    """
    Check user's platform/OS
    """
    global linux_os, windows_os
    windows_os = False
    linux_os = False

    system_os = platform.system()

    if system_os.lower() == 'linux':
        linux_os = True
    elif system_os.lower() == 'windows':
        windows_os = True


if __name__ == '__main__':

    # Check user's platform
    check_platform()

    # Load Launcher Settings
    load_settings_from_file()

    if settings.get('install_type') == 'flatpak':
        steam_cmd = 'flatpak run com.valvesoftware.Steam'

    root = tk.Tk()
    root.title('DayZ Py Launcher')

    # Icon Source:
    # https://www.wallpaperflare.com/dayz-video-games-minimalism-monochrome-typography-artwork-wallpaper-pjmat
    img = PhotoImage(file='dayz_icon.png')

    if (settings.get('dayz_dir') == '' or not os.path.exists(settings.get('dayz_dir'))):
        detect_install_directories()

    if windows_os:
        apply_windows_gui_fixes()

    root.iconphoto(True, img)

    # Set the theme/mode configured in the settings
    # Source: https://github.com/rdbende/Azure-ttk-theme/tree/gif-based/
    root.tk.call('source', 'azure.tcl')
    root.tk.call('set_theme', settings.get('theme'))

    app = App(root)
    app.pack(fill='both', expand=True)

    # Set initial window size
    root.geometry('1280x600')

    # Warn user if not running on linux_os:
    if not linux_os:
        warn_message = 'Unsupported Operating Sytem.'
        print(warn_message)
        app.MessageBoxWarn(message=warn_message)

    # Generate Installed Mods treeview if DayZ directory in settings
    if settings.get('dayz_dir') != '':
        generate_mod_treeview()

    # Load Favorites and History on Startup unless disabled by user
    if settings.get('load_favs_on_startup'):
        app.after(500, load_fav_history)

    root.mainloop()
