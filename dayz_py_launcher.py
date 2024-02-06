import a2s
import hashlib
import ipaddress
import json
import logging
import multiprocessing
import os
import platform
import re
import requests
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from a2s import dayzquery
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from steamworks import STEAMWORKS
from threading import Event, Thread
from tkinter import filedialog, messagebox, PhotoImage, simpledialog, ttk


# Get the absolute path of the directory containing DayZ Py Launcher
app_directory = os.path.dirname(os.path.abspath(__file__))

loggingFile = os.path.join(app_directory, 'dayz_py.log')
logging.basicConfig(filename=loggingFile, level=logging.DEBUG, filemode='w',
                    format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S')
logging.getLogger(a2s.__name__).setLevel(logging.INFO)

appName = 'DayZ Py Launcher'
version = '2.6.0'
dzsa_api_servers = 'https://dayzsalauncher.com/api/v2/launcher/servers/dayz'
workshop_url = 'steam://url/CommunityFilePage/'
gameExecutable = 'steam'
app_id = '221100'
sym_folder = '_py'
settings_json = os.path.join(app_directory, 'dayz_py.json')
windows_os = False
linux_os = False
architecture = ''

steamworks_libraries = os.path.join(app_directory, 'steamworks', 'libs')

# Used for checking/downloading updates
main_branch_py = 'https://gitlab.com/tenpenny/dayz-py-launcher/-/raw/main/dayz_py_launcher.py'
main_branch_sh = 'https://gitlab.com/tenpenny/dayz-py-launcher/-/raw/main/dayz_py_installer.sh'
main_branch_ps1 = 'https://gitlab.com/tenpenny/dayz-py-launcher/-/raw/main/dayz_py_installer.ps1'

# Header used in API request
headers = {
    'User-Agent': f'{appName}/{version}'
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
    'check_updates': True,
    'favorites': {},
    'history': {}
}

serverDict = {}
modDict = {}
hashDict = {}

hidden_items = set()
hidden_items_server_mods = set()
hidden_items_installed_mods = set()

# Prevent multiple stdout/prints from ending up on the same line.
stdout_lock = threading.Lock()

# Used to check if App was loaded using pythonw.exe since it crashes
# or throws many exceptions when using "sys.__stdout__.write" or
# "sys.__stderr__.write"
disable_console_writes = False


class App(ttk.Frame):
    def __init__(self, parent):
        ttk.Frame.__init__(self)

        # Make the app responsive
        for index in [0, 1]:
            # self.columnconfigure(index=index, weight=1)
            self.rowconfigure(index=index, weight=1)

        self.columnconfigure(index=0, weight=5)
        self.columnconfigure(index=1, weight=1)

        # List for Map Combobox
        self.dayz_maps = []

        # List for Version Combobox
        self.dayz_versions = []

        # Create widgets :)
        self.setup_widgets()

        # Messagebox Title
        self.message_title = 'DayZ Py Message'

        self.steamworks_running = False

    def MessageBoxAskYN(self, message):
        return messagebox.askyesno(title=self.message_title, message=message)

    def MessageBoxInfo(self, message):
        messagebox.showinfo(title=self.message_title, message=message)

    def MessageBoxError(self, message):
        messagebox.showerror(title=self.message_title, message=message)

    def MessageBoxWarn(self, message):
        messagebox.showwarning(title=self.message_title, message=message)

    def LoadingBox(self, ip, gamePort, serverName):
        """
        This is a popup box that displays the server name and IP of the
        server the user joined. Sometimes it can take longer than expected
        for the game window to load. Let's the user know the request is
        being processed. Once the DayZ executable is found as a running
        process, the popup will close. Else, after 30 seconds, alert the user
        that it may have failed and to try checking Steam library Status for
        DayZ. If it shows running, stop it and try joining the server again.
        """
        self.loading_popup = tk.Toplevel(self)
        self.loading_popup.title(self.message_title)
        self.loading_popup.geometry('600x150')

        # Create a label for the join message
        join_message = (
            f'Joining Server...\n'
            f'{serverName[:65]}\n'
            f'IP: {ip} - GamePort: {gamePort}'
        )
        self.join_label_var = tk.StringVar(value=join_message)
        join_label = ttk.Label(self.loading_popup, justify='center', textvariable=self.join_label_var, font=("", 11))
        join_label.pack(pady=20)

        # Create a label for the loading message
        self.loading_label_var = tk.StringVar()
        loading_label = ttk.Label(self.loading_popup, justify='center', textvariable=self.loading_label_var, font=("", 11))
        loading_label.pack()

        # Create a variable to signal the thread to stop
        self.stop_thread = threading.Event()

        # Start a thread for the process-checking
        thread = threading.Thread(target=self.UpdateLoadingBox, daemon=True)
        thread.start()

        # Schedule closing the loading window after 30 seconds
        self.loading_popup.after(30000, self.StopLoadingBox)

    def UpdateLoadingBox(self):
        """
        Used to check for the DayZ process and close the popup once found.
        """
        if linux_os:
            find_process = ['pgrep', '-f', 'DayZ(_x64)?\.exe']
        elif windows_os:
            # Forcing "exit 1" since PowerShell wasn't throwing CalledProcessError on non-matching process queries
            get_wmi = (
                r"$process = Get-WmiObject Win32_Process | "
                r"Where-Object { $_.Name -match 'DayZ(_x64)?\.exe' }; "
                r"if ($process) { Write-Output $process } else { exit 1 }"
            )
            find_process = ['powershell', get_wmi]
        
        def find_dayz_exe():
            # Check if the 'DayZ_x64.exe' or 'DayZ.exe' process exists using subprocess and pgrep
            try:
                if windows_os:
                    subprocess.check_output(find_process, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    subprocess.check_output(find_process)
                return True
            except subprocess.CalledProcessError:
                return False

        # Loop until the thread times out (30 seconds) or DayZ process found
        count = 1
        while not self.stop_thread.is_set():
            # Make sure the user hasn't closed the popup manually
            if not self.loading_popup.winfo_exists():
                self.stop_thread.set()

            if find_dayz_exe():
                self.loading_label_var.set('DayZ process found!\n')
                self.loading_popup.after(2000, self.loading_popup.destroy)
                self.stop_thread.set()
                break
            else:
                dots = '.' * count
                self.loading_label_var.set(f'Waiting for DayZ to load{dots}')
                count = (count + 1) % 4

            time.sleep(1)

    def StopLoadingBox(self):
        """
        Used to stop the popup thread and alert the user if it timed out
        getting the DayZ process.
        """
        self.stop_thread.set()

        warn_message = (
            f'Timed out checking for the DayZ process.\n'
            f"If the game didn't load, you may need to check the status in your Steam Library.\n"
            f'If DayZ says "Running", Right Click > Stop and then try rejoining the server.'
        )
        logging.warning('Timed out checking for the DayZ process')
        self.join_label_var.set(warn_message)
        self.loading_popup.geometry('600x110')
        self.loading_label_var.set('')

    def SteamworksBox(self):
        """
        This is a popup box that displays the progress of Steam Workshop mod
        Subscriptions.
        """
        self.steamworks_popup = tk.Toplevel(self)
        self.steamworks_popup.title(self.message_title)
        self.steamworks_popup.geometry('500x125')

        self.progress_label_var = tk.StringVar(value='Loading Steamworks...')
        progress_label = ttk.Label(self.steamworks_popup, justify='center', textvariable=self.progress_label_var, font=("", 11))
        progress_label.pack(pady=(30, 10))

        self.progress_var = tk.DoubleVar()
        progress_bar = ttk.Progressbar(self.steamworks_popup, variable=self.progress_var, length=300, mode='determinate')
        progress_bar.pack(pady=10)

    def OnSingleClick(self, event):
        """
        These actions are performed when the user clicks on a server/entry in the
        Server List Treeview. Gets IP and Port info from treeview entry. Queries
        the serverDict for the info to compare server mods vs locally installed mods.
        Then generates the Server Mod Treeview and Info on Tab 2 ('Server Info')
        """
        if self.treeview.selection():

            ip, _, queryPort = get_selected_ip(self.treeview.selection()[0])

            self.check_favorites(ip, queryPort)

            self.filter_server_mods_text.set('')

            serverDict_info = serverDict.get(f'{ip}:{queryPort}')

            last_joined = self.check_history(ip, queryPort)
            # Since we are manually inserting servers into the DB (i.e. Favorites and History)
            # that may be down or unable to get all of the server info, skip the following in
            # that scenario
            if serverDict_info.get('environment'):
                time_accel = serverDict_info.get("timeAcceleration")
                time_accel = f'{time_accel}{"x"}' if time_accel is not None else time_accel
                self.server_info_text.set(
                    f'Name:    {serverDict_info.get("name")}\n\n'
                    f'Server OS:   {"Windows" if serverDict_info.get("environment") == "w" else "Linux":<25}'
                    f'DayZ Version:   {serverDict_info.get("version"):<25}'
                    f'Password Protected:   {bool_to_yes_no(serverDict_info.get("password")):<20}'
                    f'VAC Enabled:   {bool_to_yes_no(serverDict_info.get("vac")):<20}'
                    f'Shard:   {serverDict_info.get("shard").title()}\n\n'
                    f'BattlEye:   {bool_to_yes_no(serverDict_info.get("battlEye")):<35}'
                    f'First Person Only:   {bool_to_yes_no(serverDict_info.get("firstPersonOnly")):<24}'
                    f'Time Acceleration:   {str(time_accel):<28}'
                    f'Last Joined:   {last_joined:<25}'
                )

                generate_server_mod_treeview(serverDict_info)

                treeview_sort_column(self.server_mods_tv, 'Status', True)
            else:
                # Clear the existing info and treeview on the Server Info tab to prevent previously
                # selected server info from being displayed for a newly selected server that is down
                self.filter_server_mods_text.set('')
                self.server_info_text.set('')
                self.server_mods_tv.delete(*self.server_mods_tv.get_children())

    def OnDoubleClick(self, event):
        """
        Used to open the Steam Workshop Mod URL when user double clicks
        either a Server Info treeview item or an Installed Mods treeview
        item. This allows the user to easily subscribe to missing mods.
        Check the region in order to prevent double clicks on the column
        headings
        """
        widget = event.widget
        region = widget.identify_region(event.x, event.y)
        if region == 'cell':
            if widget == self.server_mods_tv and self.server_mods_tv.selection():
                item = self.server_mods_tv.selection()[0]
                url = self.server_mods_tv.item(item, 'values')[2]

            elif widget == self.installed_mods_tv and self.installed_mods_tv.selection():
                item = self.installed_mods_tv.selection()[0]
                url = self.installed_mods_tv.item(item, 'values')[3]

            self.open_url(url)

    def rightClick_selection(self, event):
        """
        Selects the treeview item below the current mouse position. Gets the item
        number and displays the context menu.
        """
        global rightClickItem
        rightClickItem = event.widget.identify_row(event.y)
        if rightClickItem:
            itemAlreadySelected = rightClickItem in event.widget.selection()
            # Allow right click to preserve multiselected rows
            if itemAlreadySelected and event.widget != self.treeview:
                event.widget.context_menu.post(event.x_root, event.y_root)
            else:
                event.widget.selection_set(rightClickItem)
                # rightClickValues = event.widget.item(item)['values']
                event.widget.context_menu.post(event.x_root, event.y_root)

    def close_menu(self, event):
        """
        Closes the Right Click context menu when you left click anywhere outside
        the menu.
        """
        context_menus = (
            self.treeview.context_menu,
            self.server_mods_tv.context_menu,
            self.installed_mods_tv.context_menu
        )
        for menu in context_menus:
            if menu.winfo_exists() and event.widget != menu:
                menu.unpost()

    def copyIP(self):
        """
        Copies the currently selected treeview item IP address to the clipboard.
        """
        global rightClickItem
        ip, _, _ = get_selected_ip(rightClickItem)
        self.clipboard_clear()
        self.clipboard_append(ip)

    def copyName(self):
        """
        Copies the currently selected treeview item Server Name to the clipboard.
        """
        global rightClickItem
        serverName = self.treeview.item(rightClickItem)["values"][1]
        self.clipboard_clear()
        self.clipboard_append(serverName)

    def copyGamePort(self):
        """
        Copies the currently selected treeview item Game Port address to the clipboard.
        """
        global rightClickItem
        _, gamePort, _ = get_selected_ip(rightClickItem)
        self.clipboard_clear()
        self.clipboard_append(gamePort)

    def copyQueryPort(self):
        """
        Copies the currently selected treeview item Query Port address to the clipboard.
        """
        global rightClickItem
        queryPort = self.treeview.item(rightClickItem)["values"][6]
        self.clipboard_clear()
        self.clipboard_append(queryPort)

    def copyIP_GamePort(self):
        """
        Copies the currently selected treeview item IP address & Game Port to the clipboard.
        """
        global rightClickItem
        ip, gamePort, _ = get_selected_ip(rightClickItem)
        self.clipboard_clear()
        self.clipboard_append(f'{ip}:{gamePort}')

    def copyIP_QueryPort(self):
        """
        Copies the currently selected treeview item IP address & Query Port to the clipboard.
        """
        global rightClickItem
        ip, _, queryPort = get_selected_ip(rightClickItem)
        self.clipboard_clear()
        self.clipboard_append(f'{ip}:{queryPort}')

    def copyModList(self):
        """
        Copies the currently selected treeview item Mod List to the clipboard.
        """
        global rightClickItem
        ip, _, queryPort = get_selected_ip(rightClickItem)
        mod_dict = get_serverDict_mods(ip, queryPort)

        mod_list = []
        for mod in mod_dict.values():
            mod_list.append(mod)
        mod_list = sorted(mod_list, key=str.casefold)
        mod_list_str = '\n'.join(mod_list)
        self.clipboard_clear()
        self.clipboard_append(mod_list_str)

    def copyAllInfo(self):
        """
        Copies the currently selected treeview item Server Info to the clipboard.
        """
        global rightClickItem
        ip, _, queryPort = get_selected_ip(rightClickItem)
        serverInfo = json.dumps(serverDict.get(f'{ip}:{queryPort}'), indent=4)
        self.clipboard_clear()
        self.clipboard_append(serverInfo)

    def checkProcess(self, process, error_queue, waitTime, progress_queue, print_queue):
        """
        Check if the subprocess has finished. Use the queue to communicate
        with the Steamworks process in order to update the GUI.
        """
        open_steam_downloads = False
        if not print_queue.empty():
            current_stdout = print_queue.get_nowait()
            print(current_stdout)
            if current_stdout == 'Open Steam Downloads':
                open_steam_downloads = True

        if process.is_alive():
            self.after(100, lambda: self.checkProcess(process, error_queue, waitTime, progress_queue, print_queue))
            if not progress_queue.empty() and self.steamworks_popup.winfo_exists():
                current_progress = progress_queue.get_nowait()
                print(current_progress)
                if len(current_progress) > 2: # Subscribing
                    self.progress_label_var.set(f'Downloading "{current_progress[0]}"...')

                    # Only update progress bar while "Total" download size is not 0. Note
                    # "downloaded" is not tracked through "progress_queue", Only "total" and
                    # "progress".
                    # {'downloaded': 0, 'total': 621120, 'progress': 0.0}
                    # {'downloaded': 55424, 'total': 621120, 'progress': 0.08923235445646574}
                    if current_progress[1] != 0 and current_progress[2]:
                        self.progress_var.set(current_progress[2] * 100)

                    # Set Progress to 100 if download has completed and Steam reverted all
                    # download values back to 0 and Item_State is 5 (installed).
                    # {'downloaded': 0, 'total': 0, 'progress': 0.0}
                    elif current_progress[3] == 5:
                        self.progress_var.set(100)

                    # Reset progress bar when switching to next mod
                    elif self.progress_var.get() == 100:
                        self.progress_var.set(0)
                        refresh_server_mod_info()

                else: # Unsubscribing
                    self.progress_label_var.set(f'Unsubscribing from "{current_progress[0]}"...')

                    if current_progress[1] == 13:
                        self.progress_var.set(50)

                    elif current_progress[1] == 4:
                        self.progress_var.set(100)

        else:
            if not error_queue.empty():
                self.MessageBoxError(error_queue.get())
            else:
                self.after(waitTime, refresh_server_mod_info)

            if self.steamworks_popup.winfo_exists():
                self.steamworks_popup.after(1000, self.steamworks_popup.destroy)

            self.steamworks_running = False

        if open_steam_downloads:
            self.after(2000, lambda: self.open_url('steam://nav/downloads'))

    def modRequests(self, treeview, request, waitTime, onlyMissingMods=False):
        """
        Subscribes/Unsubscribes to Steam Workshop mods using Steamworks.
        """
        # Had a random occurance where Steamworks would partially load even when Steam was closed
        # but wouldn't throw any exceptions. It would only complain later on during subscribing
        # or unsubscribing that Steamworks hadn't fully initiallized. Adding this as an extra failsafe.
        if not check_steam_process():
            error_message = f"Steam isn't running (failsafe check). Can't {request} to mod(s)."
            logging.error(f'{error_message}')
            print(error_message)
            self.MessageBoxError(error_message)
            return

        if self.steamworks_running:
            error_message = (
                'Previous Steamworks request appears to be running. '
                'Try again once it completes or restart DayZ Py Launcher.'
            )
            logging.error(error_message)
            print(error_message)
            self.MessageBoxError(error_message)
            return

        if request == 'Unsubscribe':
            ask_message = 'Are you sure you want to "Unsubscribe" from selected mod(s)?'
            answer = app.MessageBoxAskYN(message=ask_message)
            debug_message = f'Unsubscribe?: {answer}'
            logging.debug(debug_message)
            print(debug_message)
            if not answer:
                return

        # User clicked "Subscribe All" or "Join Server" button
        if onlyMissingMods:
            treeview_list = self.server_mods_tv.get_children()
        else: # User choose option from right click menu
            treeview_list = treeview.selection()

        if not treeview_list:
            self.MessageBoxError('No mods were selected.')
            return

        mod_list = []
        for item_id in treeview_list:
            mod_values = treeview.item(item_id, 'values')
            if onlyMissingMods and mod_values[3] == 'Missing':
                mod_name = mod_values[0]
                workshop_id = int(mod_values[1])
            elif not onlyMissingMods and treeview == self.server_mods_tv:
                mod_name = mod_values[0]
                workshop_id = int(mod_values[1])
            elif not onlyMissingMods and treeview == self.installed_mods_tv:
                mod_name = mod_values[1]
                workshop_id = int(mod_values[2])

            if (mod_name, workshop_id) not in mod_list:
                mod_list.append((mod_name, workshop_id))

        # Set up a queue for communication with Steamworks processes
        error_queue = multiprocessing.Queue()
        progress_queue = multiprocessing.Queue()
        print_queue = multiprocessing.Queue()

        self.SteamworksBox()

        steamworks_process = multiprocessing.Process(
            target=CallSteamworksApi,
            args=(request, mod_list, error_queue, progress_queue, print_queue),
            name='SteamworksPy'
        )
        steamworks_process.daemon = True
        steamworks_process.start()

        self.steamworks_running = True

        # Periodically check if the steamworks_process is still alive and update popup
        self.after(100, lambda: self.checkProcess(steamworks_process, error_queue, waitTime, progress_queue, print_queue))

    def verifyGameIntegrity(self):
        """
        Verifies the Integrity of the DayZ installation. This is the same as going into the
        properties of DayZ in your Steam Library. Then going to "Installed Files" and "Verify
        integrity of game files"
        """
        ask_message = 'Use Steam to verify the integrity of your DayZ installation files? This may take several minutes.'
        answer = app.MessageBoxAskYN(message=ask_message)
        debug_message = f'Verify DayZ Install: {answer}'
        logging.debug(debug_message)
        print(debug_message)
        if answer:
            self.open_url(f'steam://validate/{app_id}')

    def selectAllItemsText(self, widget):
        """
        Highlight/Select all items or text in a widget
        """
        treeviews_list = [self.treeview, self.server_mods_tv, self.installed_mods_tv]

        if widget in treeviews_list:
            widget.selection_add(widget.get_children())
        elif widget == self.console:
            self.console.tag_add(tk.SEL, '1.0', 'end-1c')

        return 'break'

    def remove_selected_history(self):
        """
        Removes the currently selected treeview item from the History if it exist.
        """
        global rightClickItem
        ip, _, queryPort = get_selected_ip(rightClickItem)

        removed = settings['history'].pop(f'{ip}:{queryPort}', None)
        if removed:
            logInfo = f'{self.treeview.item(rightClickItem)["values"][1]} - {ip}:{queryPort}'
            logMessage = f'{logInfo} - Removed from History'
            logging.info(logMessage)
            print(logMessage)
            save_settings_to_json()

    def toggle_favorite(self):
        """
        Adds or Removes the currently selected item in the Server List Treeview to
        or from the Favorites list stored in the dayz_py.json.
        """
        fav_state = self.favorite_var.get()

        if self.treeview.selection():
            ip, _, queryPort = get_selected_ip(self.treeview.selection()[0])
            serverDict_info = serverDict.get(f'{ip}:{queryPort}')
            logInfo = f'{serverDict_info.get("name")} - {ip}:{queryPort}'

            if fav_state:
                logMessage = f'{logInfo} - Added to Favorites'
                logging.info(logMessage)
                print(logMessage)

                settings['favorites'][f'{ip}:{queryPort}'] = {'name': serverDict_info.get('name')}
            else:
                logMessage = f'{logInfo} - Removed from Favorites'
                logging.info(logMessage)
                print(logMessage)

                settings['favorites'].pop(f'{ip}:{queryPort}', None)
                filter_treeview()
            save_settings_to_json()

        else:
            error_message = (
                f'No server is currently selected to add or remove from favorites. '
                f'Please select a server first.'
            )
            logging.error(error_message)
            print(error_message)
            self.favorite_var.set(value=False)
            self.MessageBoxError(message=error_message)

    def get_ip_port_prompt(self):
        """
        Loads popup that allows you to add a server by IP and QueryPort.
        """
        def ok():
            nonlocal popup, ip_entry, port_entry, port_label
            try:
                port = int(port_entry.get())
                if port < 1 or port > 65535:
                    raise ValueError('Port can not be lower than 1 or higher than 65,535.')

                ip = ipaddress.ip_address(ip_entry.get())
                popup.result = (ip_entry.get(), port)
                popup.destroy()
            except ValueError as error:
                error = str(error)
                # Invalid IP
                if 'address' in error:
                    message = 'Invalid IP Address.'
                # Invalid Port - Not a number
                elif 'literal' in error:
                    message = 'Invalid Port. Must be a number.'
                # Invalid Port - Not in Range 1-65,535
                elif '65,535' in error:
                    message = error
                port_label.config(text=message)

        popup = tk.Toplevel(self)
        popup.title('Add Server')
        popup.geometry('360x150')
        popup.result = None
        popup.columnconfigure(0, weight=1)
        popup.columnconfigure(1, weight=1)

        tk.Label(popup, text='Server IP address:').grid(row=0, column=0, padx=(10, 0), pady=5)
        tk.Label(popup, text='Server Query Port:').grid(row=1, column=0, padx=(10, 0), pady=5)

        ip_entry = tk.Entry(popup)
        port_entry = tk.Entry(popup)
        port_label = tk.Label(popup, text='(Query Port, not Game Port)')

        ip_entry.grid(row=0, column=1, padx=(0, 15), pady=5)
        port_entry.grid(row=1, column=1, padx=(0, 15), pady=5)
        port_label.grid(row=2, column=0, columnspan=2, pady=5)

        ok_button = ttk.Button(popup, text="OK", command=ok)
        ok_button.grid(row=3, column=0, columnspan=2, pady=10)
        popup.bind('<Return>', lambda e: ok_button.invoke())
        popup.bind('<KP_Enter>', lambda e: ok_button.invoke())

        ip_entry.focus_set()

        popup.wait_window()

        return popup.result

    def check_favorites(self, ip, queryPort):
        """
        Check if the currently selected treeview item is a favorite. If so,
        set the 'Add/Remove Favorite' checkbox appropriately.
        """
        if f'{ip}:{queryPort}' not in settings.get('favorites'):
            self.favorite_var.set(value=False)
        else:
            self.favorite_var.set(value=True)

    def add_history(self, ip, queryPort):
        """
        Adds server to the History stored in the users dayz_py.json upon joining
        the server. Updates the timestamp if the history already exist.
        """
        settings['history'][f'{ip}:{queryPort}'] = {
            'name': serverDict.get(f'{ip}:{queryPort}').get('name'),
            'last_joined': str(datetime.now().astimezone())
        }
        logInfo = f'{serverDict.get(f"{ip}:{queryPort}").get("name")} - {ip}:{queryPort}'
        logMessage = f'{logInfo} - Added to History'
        save_settings_to_json()

    def check_history(self, ip, queryPort):
        """
        Checks if the curently selected treeview item is in the History. If so,
        get the timestamp. Then format and return. Example format '2023-10-10 @ 14:09'.
        This is currently displayed as the Last Joined under the Server Info tab.
        """
        last_joined = 'Unknown'

        if f'{ip}:{queryPort}' in settings.get('history'):
            timestamp = settings.get('history').get(f'{ip}:{queryPort}').get('last_joined')
            dt_timestamp = datetime.strptime(
                settings.get('history').get(f'{ip}:{queryPort}').get('last_joined'),
                '%Y-%m-%d %H:%M:%S.%f%z'
            )
            last_joined = dt_timestamp.strftime('%Y-%m-%d @ %H:%M')

        return last_joined

    def clear_filters(self):
        """
        Resets filter/serach boxes back to default. Resets the treeview to an
        unfiltered state (Unhides/Reattaches 'detached' items). Removes treeview
        selection and restores checkboxs back to default.
        """
        # Clear Filter Boxes
        self.entry.delete('0', 'end')
        self.mod_text.set(self.default_mod_text)
        self.map_combobox.set(self.default_map_combobox_text)
        self.version_combobox.set(self.default_version_combobox_text)

        # Clear Server Info tab
        self.filter_server_mods_text.set('')
        self.server_info_text.set('')
        self.server_mods_tv.delete(*self.server_mods_tv.get_children())

        # Reset previous filters
        restore_treeview()

        # Unselect previously clicked treeview item & Checkboxes
        self.treeview.selection_set([])
        self.show_favorites_var.set(value=False)
        self.show_history_var.set(value=False)
        # self.show_sponsored_var.set(value=False)
        self.show_modded_var.set(value=False)
        self.show_not_modded_var.set(value=False)
        self.show_first_person_var.set(value=False)
        self.show_third_person_var.set(value=False)
        self.show_not_passworded_var.set(value=False)
        self.show_public_var.set(value=False)
        self.show_private_var.set(value=False)
        self.favorite_var.set(value=False)

    def map_combobox_focus_out(self):
        """
        Sets the default text/string ('Map') in the Map dropdown/combobox
        (visible only when there is no map selected) and also refreshes the
        Treeview filters
        """
        self.map_combobox.set(self.default_map_combobox_text)
        filter_treeview()

    def ver_combobox_focus_out(self):
        """
        Sets the default text/string ('Version') in the Version dropdown/combobox
        (visible only when there is no map selected) and also refreshes the
        Treeview filters
        """
        self.version_combobox.set(self.default_version_combobox_text)
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
            self.refresh_selected_button.grid(row=1, column=0, padx=5, pady=(0, 5), sticky='nsew')
            self.favorite.grid(row=2, column=0, padx=5, pady=0, sticky='ew')
            self.keypress_filter.grid(row=3, column=0, padx=5, pady=0, sticky='ew')
            self.entry.grid(row=4, column=0, padx=5, pady=(5, 4), sticky='ew')
            self.mod_entry.grid(row=5, column=0, padx=5, pady=(3, 4), sticky='ew')
            self.map_combobox.grid(row=6, column=0, padx=5, pady=(3, 4), sticky='ew')
            self.version_combobox.grid(row=7, column=0, padx=5, pady=(3, 5), sticky='ew')
            self.show_favorites.grid(row=8, column=0, padx=5, pady=0, sticky='ew')
            self.show_history.grid(row=9, column=0, padx=5, pady=0, sticky='ew')
            # self.show_sponsored.grid(row=10, column=0, padx=5, pady=0, sticky='ew')
            self.show_first_person.grid(row=10, column=0, padx=5, pady=0, sticky='ew')
            self.show_third_person.grid(row=11, column=0, padx=5, pady=0, sticky='ew')
            self.show_modded.grid(row=12, column=0, padx=5, pady=0, sticky='ew')
            self.show_not_modded.grid(row=13, column=0, padx=5, pady=0, sticky='ew')
            self.show_not_passworded.grid(row=14, column=0, padx=5, pady=0, sticky='ew')
            self.show_public.grid(row=15, column=0, padx=5, pady=0, sticky='ew')
            self.show_private.grid(row=16, column=0, padx=5, pady=0, sticky='ew')
            self.clear_filter.grid(row=17, column=0, padx=5, pady=5, sticky='nsew')
            self.separator.grid(row=18, column=0, padx=(20, 20), pady=2, sticky='ew')
            self.add_server_button.grid(row=19, column=0, padx=5, pady=(5, 0), sticky='nsew')
            self.join_server_button.grid(row=20, column=0, padx=5, pady=(5, 3), sticky='nsew')

            # Hide widgets from all tabs except tab_1
            self.hide_tab_widgets(self.tab_1_widgets)

        elif selected_tab == 1:
            # If "Server Info" tab is selected
            # Hide widgets from all tabs except tab_2
            self.hide_tab_widgets(self.tab_2_widgets)

            self.server_mods_entry.grid(row=0, column=0, padx=5, pady=(0, 10), sticky='nsew')
            self.refresh_info_button.grid(row=1, column=0, padx=5, pady=(0, 10), sticky='nsew')
            self.manual_label.grid(row=2, column=0, padx=5, pady=(0, 10), sticky='nsew')
            self.load_workshop_label.grid(row=3, column=0, padx=5, pady=(0, 10), sticky='nsew')
            self.refresh_info_label.grid(row=4, column=0, padx=5, pady=(0, 10), sticky='nsew')
            self.method_separator.grid(row=5, column=0, padx=(20, 20), pady=(0, 10), sticky='ew')
            self.auto_label.grid(row=6, column=0, padx=5, pady=(0, 10), sticky='nsew')
            self.auto_sub_button.grid(row=7, column=0, padx=5, pady=(0, 10), sticky='nsew')
            self.auto_sub_label.grid(row=8, column=0, padx=5, pady=(0, 10), sticky='nsew')
            self.steam_download_button.grid(row=9, column=0, padx=5, pady=(0, 10), sticky='nsew')
            self.steam_download_label.grid(row=10, column=0, padx=5, pady=(0, 10), sticky='nsew')
            self.method_separator2.grid(row=11, column=0, padx=(20, 20), pady=(0, 15), sticky='ew')
            self.force_mod_update_server_button.grid(row=12, column=0, padx=5, pady=(0, 10), sticky='nsew')

        elif selected_tab == 2:
            # If "Installed Mods" tab is selected
            # Hide widgets from all tabs except tab_3
            self.hide_tab_widgets(self.tab_3_widgets)

            self.installed_mods_entry.grid(row=0, column=0, padx=5, pady=(0, 10), sticky='nsew')
            self.refresh_mod_button.grid(row=1, column=0, padx=5, pady=(0, 10), sticky='nsew')
            self.total_label.grid(row=2, column=0, padx=5, pady=10, sticky='nsew')
            self.verify_separator.grid(row=3, column=0, padx=(20, 20), pady=(0, 10), sticky='ew')
            self.verify_integrity_button.grid(row=4, column=0, padx=5, pady=(5 , 10), sticky='nsew')
            self.force_mod_update_installed_button.grid(row=5, column=0, padx=5, pady=(5 , 10), sticky='nsew')

        elif selected_tab == 3:
            # If "Console" tab is selected
            # Hide widgets from all tabs
            self.hide_tab_widgets(self.tab_4_widgets)

        elif selected_tab == 4:
            # If "Settings" tab is selected
            # Hide widgets from all tabs except tab_5
            self.hide_tab_widgets(self.tab_5_widgets)

            self.version_label.grid(row=0, column=0, padx=5, pady=(0, 10), sticky='nsew')
            self.open_install_button.grid(row=1, column=0, padx=5, pady=(0, 10), sticky='nsew')

    def hide_tab_widgets(self, tab_list):
        """
        Used in the on_tab_change function to hide widgets when
        switching to a tab where the widget is not needed.
        """
        for grid_item in self.grid_list:
            if grid_item not in tab_list:
                grid_item.grid_forget()

    def open_url(self, url):
        """
        Opens the mod in the Steam Workshop. Used for subscribing/downloading
        missing mods.
        """
        if linux_os:
            open_cmd = ['xdg-open', url]
        elif windows_os:
            open_cmd = ['cmd', '/c', 'start', url]

        try:
            if windows_os:
                subprocess.Popen(open_cmd, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.Popen(open_cmd)
        except subprocess.CalledProcessError as e:
            error_message = f'Failed to open URL.\n\n{e}'
            logging.error(error_message)
            print(error_message)
            self.MessageBoxError(error_message)

    def open_mod_dir(self):
        """
        Opens the mod directory in the file browser/explorer.
        """
        global rightClickItem
        steamWorkshopId = str(self.installed_mods_tv.item(rightClickItem)["values"][2])
        dayzWorkshop = os.path.join(settings.get('steam_dir'), 'content', app_id)
        mod_dir = os.path.realpath(os.path.join(dayzWorkshop, steamWorkshopId))

        if linux_os:
            open_cmd = ['xdg-open', mod_dir]
        elif windows_os:
            open_cmd = ['explorer', mod_dir]

        try:
            subprocess.Popen(open_cmd)
        except subprocess.CalledProcessError as e:
            error_message = f'Failed to open mod directory.\n\n{e}'
            logging.error(error_message)
            print(error_message)
            self.MessageBoxError(error_message)

    def open_sym_dir(self):
        """
        Opens file browser/explorer and select/hightlight the symlink.
        """
        global rightClickItem
        symlinkName = str(self.installed_mods_tv.item(rightClickItem)["values"][0])
        symlinkDir = os.path.join(settings.get('dayz_dir'), sym_folder)
        symlink = os.path.normpath(os.path.join(symlinkDir, symlinkName))

        dbus_command = (
            "dbus-send",
            "--session",
            "--print-reply",
            "--dest=org.freedesktop.FileManager1",
            "--type=method_call",
            "/org/freedesktop/FileManager1",
            "org.freedesktop.FileManager1.ShowItems",
            f"array:string:file://{symlink}",
            "string:''"
        )

        if linux_os:
            # open_cmd = ['xdg-open', symlinkDir]
            open_cmd = dbus_command
        elif windows_os:
            open_cmd = ['explorer', '/select,', symlink]

        try:
            subprocess.Popen(open_cmd)
        except subprocess.CalledProcessError as e:
            error_message = f'Failed to open symlink directory.\n\n{e}'
            logging.error(error_message)
            print(error_message)
            self.MessageBoxError(error_message)

    def open_install_dir(self):
        """
        Opens the DayZ Py Launcher installation or current working directory.
        """
        global app_directory
        if linux_os:
            open_cmd = ['xdg-open', app_directory]
        elif windows_os:
            open_cmd = ['explorer', app_directory]

        try:
            subprocess.Popen(open_cmd)
        except subprocess.CalledProcessError as e:
            error_message = f'Failed to open install directory.\n\n{e}'
            logging.error(error_message)
            print(error_message)
            self.MessageBoxError(error_message)

    def toggle_filter_on_keypress(self):
        """
        Enable or Disable filter on keypress. If disabled, enable filter on
        'FocusOut'
        """
        if self.keypress_filter_var.get():
            self.keypress_trace_id = self.filter_text.trace_add("write", lambda *args: filter_treeview())
            self.entry.unbind('<Tab>', self.focus_trace_id)
        else:
            self.filter_text.trace_remove("write", self.keypress_trace_id)
            self.focus_trace_id = self.entry.bind('<Tab>', lambda e: filter_treeview())

    def setup_widgets(self):
        # Create a Frame for input widgets
        self.widgets_frame = ttk.Frame(self, padding=(0, 0, 0, 10))
        self.widgets_frame.grid(
            row=0, column=1, padx=(0, 0), pady=(20, 5), sticky='nsew', rowspan=3
        )
        self.widgets_frame.columnconfigure(index=0, weight=1)

        # Notebook to hold the Tabs
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=0, column=0, padx=(25, 10), pady=(15, 5), sticky='nsew', rowspan=3)
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

        cols = ('Map', 'Name', 'Players', 'Max', 'Gametime', 'IP:GamePort', 'QueryPort', 'Ping')
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
        self.treeview.bind('<Control-a>', lambda e: self.selectAllItemsText(self.treeview))
        self.treeview.bind('<<TreeviewSelect>>', self.OnSingleClick)
        # Right Click Menu
        self.treeview.bind("<Button-3>", self.rightClick_selection)
        self.treeview.context_menu = tk.Menu(self.treeview, tearoff=0, bd=4, relief='groove')
        self.treeview.context_menu.add_command(label='Copy IP', command=self.copyIP)
        self.treeview.context_menu.add_command(label='Copy Name', command=self.copyName)
        self.treeview.context_menu.add_command(label='Copy Game Port', command=self.copyGamePort)
        self.treeview.context_menu.add_command(label='Copy Query Port', command=self.copyQueryPort)
        self.treeview.context_menu.add_command(label='Copy IP:GamePort', command=self.copyIP_GamePort)
        self.treeview.context_menu.add_command(label='Copy IP:QueryPort', command=self.copyIP_QueryPort)
        self.treeview.context_menu.add_command(label='Copy Mod List', command=self.copyModList)
        self.treeview.context_menu.add_command(label='Copy All Info', command=self.copyAllInfo)
        self.treeview.context_menu.add_separator()
        self.treeview.context_menu.add_command(label='Join Server', command=launch_game)
        self.treeview.context_menu.add_separator()
        self.treeview.context_menu.add_command(label='Remove From History', command=self.remove_selected_history)
        root.bind('<Button-1>', self.close_menu)

        self.scrollbar.config(command=self.treeview.yview)

        # Treeview columns - Set default width
        self.treeview.column('Map', width=110)
        self.treeview.column('Name', width=440)
        self.treeview.column('Players', width=60)
        self.treeview.column('Max', width=30)
        self.treeview.heading('Gametime', anchor='center')
        self.treeview.column('Gametime', width=85, anchor='center')
        self.treeview.column('IP:GamePort', width=145)
        self.treeview.column('QueryPort', width=65)
        self.treeview.column('Ping', width=50)

        # Download Servers Accentbutton
        self.refresh_all_button = ttk.Button(
            self.widgets_frame, text='Download Servers', style='Accent.TButton', command=refresh_servers
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
            self.widgets_frame, text='Filter on Keypress', style='Small.TCheckbutton', variable=self.keypress_filter_var, command=self.toggle_filter_on_keypress
        )

        # Filter/Search Entry Box
        self.filter_text = tk.StringVar()

        self.entry = ttk.Entry(self.widgets_frame, textvariable=self.filter_text)

        self.entry.bind('<Return>', lambda e: filter_treeview())
        self.entry.bind('<KP_Enter>', lambda e: filter_treeview())
        # Add 'trace' to filter on keypress. Store 'trace_id' in order to disable it
        # if the user wants to turn it off. When enabled, can cause lag when typing
        # when searching a large server list.
        # self.keypress_trace_id = self.filter_text.trace_add("write", lambda *args: filter_treeview())
        self.focus_trace_id = self.entry.bind('<Tab>', lambda e: filter_treeview())

        # Filter/Search Entry Box
        self.mod_text = tk.StringVar()
        self.default_mod_text = 'Mods'

        self.mod_entry = ttk.Entry(self.widgets_frame, textvariable=self.mod_text)
        self.mod_entry.insert(0, self.default_mod_text)
        self.mod_entry.bind('<FocusIn>', lambda e: (self.mod_entry.delete('0', 'end')) if self.mod_entry.get() == self.default_mod_text else None)
        self.mod_entry.bind('<FocusOut>', lambda e: (self.mod_entry.insert(0, self.default_mod_text)) if self.mod_entry.get() == '' else None)
        self.mod_entry.bind('<Return>', lambda e: filter_treeview())
        self.mod_entry.bind('<KP_Enter>', lambda e: filter_treeview())

        # Map List Combobox
        self.default_map_combobox_text = 'Map'
        self.map_combobox = ttk.Combobox(self.widgets_frame, values=self.dayz_maps)
        self.map_combobox.set(self.default_map_combobox_text)

        self.map_combobox.bind('<FocusIn>', lambda e: (
            self.map_combobox.set('') if self.map_combobox.get() == self.default_map_combobox_text else None)
        )
        self.map_combobox.bind('<FocusOut>', lambda e: self.map_combobox_focus_out() if self.map_combobox.get() == '' else app.map_combobox.selection_clear())
        self.map_combobox.bind('<Return>', lambda e: filter_treeview())
        self.map_combobox.bind('<KP_Enter>', lambda e: filter_treeview())
        self.map_combobox.bind('<<ComboboxSelected>>', lambda e: filter_treeview())

        # Version List Combobox
        self.default_version_combobox_text = 'Version'
        self.version_combobox = ttk.Combobox(self.widgets_frame, values=self.dayz_versions)
        self.version_combobox.set(self.default_version_combobox_text)

        self.version_combobox.bind('<FocusIn>', lambda e: (
            self.version_combobox.set('') if self.version_combobox.get() == self.default_version_combobox_text else None)
        )
        self.version_combobox.bind('<FocusOut>', lambda e: self.ver_combobox_focus_out() if self.version_combobox.get() == '' else app.version_combobox.selection_clear())
        self.version_combobox.bind('<Return>', lambda e: filter_treeview())
        self.version_combobox.bind('<KP_Enter>', lambda e: filter_treeview())
        self.version_combobox.bind('<<ComboboxSelected>>', lambda e: filter_treeview())

        # Show Only Favorites Filter Checkbutton
        self.show_favorites_var = tk.BooleanVar()
        self.show_favorites = ttk.Checkbutton(
            self.widgets_frame, text='Favorites', style='Small.TCheckbutton', variable=self.show_favorites_var, command=lambda: filter_treeview(self.show_favorites_var.get())
        )

        # Show Only History Filter Checkbutton
        self.show_history_var = tk.BooleanVar()
        self.show_history = ttk.Checkbutton(
            self.widgets_frame, text='History', style='Small.TCheckbutton', variable=self.show_history_var, command=lambda: filter_treeview(self.show_history_var.get())
        )

        # Show Only Sponsored Filter Checkbutton
        # self.show_sponsored_var = tk.BooleanVar()
        # self.show_sponsored = ttk.Checkbutton(
        #     self.widgets_frame, text='Sponsored', style='Small.TCheckbutton', variable=self.show_sponsored_var, command=lambda: filter_treeview(self.show_sponsored_var.get())
        # )

        # Show Only First Person Filter Checkbutton
        self.show_first_person_var = tk.BooleanVar()
        self.show_first_person = ttk.Checkbutton(
            self.widgets_frame, text='First Person Only', style='Small.TCheckbutton', variable=self.show_first_person_var, command=lambda: filter_treeview(self.show_first_person_var.get())
        )

        # Show Only Third Person Filter Checkbutton
        self.show_third_person_var = tk.BooleanVar()
        self.show_third_person = ttk.Checkbutton(
            self.widgets_frame, text='Third Person Only', style='Small.TCheckbutton', variable=self.show_third_person_var, command=lambda: filter_treeview(self.show_third_person_var.get())
        )

        # Show Only Modded Filter Checkbutton
        self.show_modded_var = tk.BooleanVar()
        self.show_modded = ttk.Checkbutton(
            self.widgets_frame, text='Modded', style='Small.TCheckbutton', variable=self.show_modded_var, command=lambda: filter_treeview(self.show_modded_var.get())
        )

        # Show Only Not Modded Filter Checkbutton
        self.show_not_modded_var = tk.BooleanVar()
        self.show_not_modded = ttk.Checkbutton(
            self.widgets_frame, text='Not Modded', style='Small.TCheckbutton', variable=self.show_not_modded_var, command=lambda: filter_treeview(self.show_not_modded_var.get())
        )

        # Show Only Not Passworded Filter Checkbutton
        self.show_not_passworded_var = tk.BooleanVar()
        self.show_not_passworded = ttk.Checkbutton(
            self.widgets_frame, text='Hide Passworded', style='Small.TCheckbutton', variable=self.show_not_passworded_var, command=lambda: filter_treeview(self.show_not_passworded_var.get())
        )

        # Show Only Public Servers Filter Checkbutton
        self.show_public_var = tk.BooleanVar()
        self.show_public = ttk.Checkbutton(
            self.widgets_frame, text='Public', style='Small.TCheckbutton', variable=self.show_public_var, command=lambda: filter_treeview(self.show_public_var.get())
        )

        # Show Only Private Servers Filter Checkbutton
        self.show_private_var = tk.BooleanVar()
        self.show_private = ttk.Checkbutton(
            self.widgets_frame, text='Private', style='Small.TCheckbutton', variable=self.show_private_var, command=lambda: filter_treeview(self.show_private_var.get())
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
            self.widgets_frame, text='Add/Remove Favorite', style='Small.TCheckbutton', variable=self.favorite_var, command=self.toggle_favorite
        )

        # Manually Add Server Button
        self.add_server_button = ttk.Button(
            self.widgets_frame, text='Manually Add Server', command=manually_add_server
        )

        # Tab #2 (Server Info)
        self.tab_2 = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_2, text='Server Info')

        self.tab_2.columnconfigure(0, weight=1)
        self.tab_2.rowconfigure(0, weight=5)
        self.tab_2.rowconfigure(1, weight=3)

        # Filter/Search Server Mods Entry Box
        self.filter_server_mods_text = tk.StringVar()
        self.server_mods_entry = ttk.Entry(self.widgets_frame, textvariable=self.filter_server_mods_text)
        self.filter_server_mods_text.trace_add("write", lambda *args: filter_server_mods_treeview())

        # Refresh Info Accentbutton
        self.refresh_info_button = ttk.Button(
            self.widgets_frame, text='Refresh Info', style='Accent.TButton', command=refresh_server_mod_info
        )

        # Manual Method Label
        self.manual_label = ttk.Label(
            self.widgets_frame,
            text='*** Manual Method ***',
            justify='center',
            anchor='n',
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

        # Separator
        self.method_separator = ttk.Separator(self.widgets_frame)

        # Auto Method Label
        self.auto_label = ttk.Label(
            self.widgets_frame,
            text='*** Auto Method ***',
            justify='center',
            anchor='n',
        )

        # Auto Subscribe All Accentbutton
        self.auto_sub_button = ttk.Button(
            self.widgets_frame, text='Subscribe All', style='Accent.TButton', command=lambda: self.modRequests(self.server_mods_tv, 'Subscribe', 3000, True)
        )

        # Auto Subscribe All Instruction Label
        self.auto_sub_label = ttk.Label(
            self.widgets_frame,
            text='Uses Steamworks API to\ninstall all missing mods\nfor selected server.',
            justify='center',
            anchor='n',
        )

        # Separator
        self.method_separator2 = ttk.Separator(self.widgets_frame)

        # Open Steam Downloads Accentbutton
        self.steam_download_button = ttk.Button(
            self.widgets_frame, text='Steam Downloads', style='Accent.TButton', command=lambda: self.open_url('steam://nav/downloads')
        )

        # Open Steam Downloads Label
        self.steam_download_label = ttk.Label(
            self.widgets_frame,
            text="Open Steam's Download\n status page.",
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

        self.server_mods_tv.grid(row=0, column=0, padx=(0, 0), pady=(0, 0), sticky='nsew')
        self.server_mods_tv.bind('<Double-1>', self.OnDoubleClick)
        self.server_mods_tv.bind('<Control-a>', lambda e: self.selectAllItemsText(self.server_mods_tv))
        # Right Click Menu
        self.server_mods_tv.bind("<Button-3>", self.rightClick_selection)
        self.server_mods_tv.context_menu = tk.Menu(
            self.server_mods_tv, tearoff=0, bd=4, relief='groove'
        )
        self.server_mods_tv.context_menu.add_command(
            label='Open Workshop URL',
            command=lambda: self.open_url(
                self.server_mods_tv.item(rightClickItem)["values"][2]
            )
        )
        self.server_mods_tv.context_menu.add_command(
            label='Subscribe',
            command=lambda: Thread(
                target=self.modRequests(self.server_mods_tv, 'Subscribe', 3000),
                daemon=True
            ).start()
        )
        self.server_mods_tv.context_menu.add_command(
            label='Unsubscribe',
            command=lambda: Thread(
                target=self.modRequests(self.server_mods_tv, 'Unsubscribe', 10000),
                daemon=True
            ).start()
        )
        self.server_mod_scrollbar.config(command=self.server_mods_tv.yview)

        # Server Mods Treeview columns
        self.server_mods_tv.column('Name', width=360)
        self.server_mods_tv.column('Workshop ID', width=175)
        self.server_mods_tv.column('Steam Workshop / Download URL', width=365)
        self.server_mods_tv.column('Status', width=125)

        # Server Info Label & Textvariable (Below Server Mods Treeview)
        self.server_info_text = tk.StringVar()
        self.server_info_text.set('')

        self.label = ttk.Label(
            self.tab_2,
            textvariable=self.server_info_text,
            justify='center',
            wraplength=920,
        )
        self.label.grid(row=1, column=0, padx=(75, 0), sticky='nsew')

        # Attempt to force Steam to update selected mod(s)
        self.force_mod_update_server_button = ttk.Button(
            self.widgets_frame,
            text='Force Mod Update',
            style='Accent.TButton',
            command=lambda: Thread(
                target=self.modRequests(self.server_mods_tv, 'ForceUpdate', 3000),
                daemon=True
            ).start()
        )

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
        self.installed_mods_tv.bind('<Control-a>', lambda e: self.selectAllItemsText(self.installed_mods_tv))
        # Right Click Menu
        self.installed_mods_tv.bind("<Button-3>", self.rightClick_selection)
        self.installed_mods_tv.context_menu = tk.Menu(
            self.installed_mods_tv, tearoff=0, bd=4, relief='groove'
        )
        self.installed_mods_tv.context_menu.add_command(
            label='Open Mod Directory',
            command=self.open_mod_dir
        )
        self.installed_mods_tv.context_menu.add_command(
            label='Open Symlink Directory',
            command=self.open_sym_dir
        )
        self.installed_mods_tv.context_menu.add_command(
            label='Open Workshop URL',
            command=lambda: self.open_url(
                self.installed_mods_tv.item(rightClickItem)["values"][3]
            )
        )
        self.installed_mods_tv.context_menu.add_command(
            label='Unsubscribe',
            command=lambda: Thread(
                target=self.modRequests(self.installed_mods_tv, 'Unsubscribe', 10000),
                daemon=True
            ).start()
        )
        self.mod_scrollbar.config(command=self.installed_mods_tv.yview)

        # # Installed Mods Treeview columns
        self.installed_mods_tv.column('Symlink', width=50)
        self.installed_mods_tv.column('Name', width=240)
        self.installed_mods_tv.column('Workshop ID', width=100)
        self.installed_mods_tv.column('Steam Workshop / Download URL', width=325)
        self.installed_mods_tv.column('Size (MBs)', width=75)

        # Filter/Search Installed Mod Entry Box
        self.filter_installed_mods_text = tk.StringVar()
        self.installed_mods_entry = ttk.Entry(self.widgets_frame, textvariable=self.filter_installed_mods_text)
        self.filter_installed_mods_text.trace_add("write", lambda *args: filter_installed_mods_treeview())

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

        # Separator
        self.verify_separator = ttk.Separator(self.widgets_frame)

        # Verify DayZ Integrity Accentbutton
        self.verify_integrity_button = ttk.Button(
            self.widgets_frame, text='Verify DayZ', style='Accent.TButton', command=self.verifyGameIntegrity
        )

        # Attempt to force Steam to update selected mod(s)
        self.force_mod_update_installed_button = ttk.Button(
            self.widgets_frame,
            text='Force Mod Update',
            style='Accent.TButton',
            command=lambda: Thread(
                target=self.modRequests(self.installed_mods_tv, 'ForceUpdate', 3000),
                daemon=True
            ).start()
        )

        # Tab #4 (Console)
        self.tab_4 = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_4, text='Console')

        self.console_scrollbar = ttk.Scrollbar(self.tab_4)
        self.console_scrollbar.pack(side='right', fill='y')

        self.console = tk.Text(self.tab_4, wrap='word', state='disabled', yscrollcommand=self.console_scrollbar.set)
        self.console.pack(expand=True, fill='both')
        self.console_scrollbar.config(command=self.console.yview)
        self.console.tag_configure('stderr', foreground='red')
        self.console.bind('<Control-a>', lambda e: self.selectAllItemsText(self.console))

        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = ConsoleGuiOutput(self.console, 'stdout', original_stdout)
        sys.stderr = ConsoleGuiOutput(self.console, 'stderr', original_stderr)

        # Tab #5 (Settings)
        self.tab_5 = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_5, text='Settings')

        SettingsMenu(self.tab_5)

        # Version Label
        self.version_label = ttk.Label(
            self.widgets_frame,
            text=f'Version {version}',
            justify='center',
            anchor='n'
        )

        # Open DayZ Py Launcher installtion directory Accentbutton
        self.open_install_button = ttk.Button(
            self.widgets_frame, width=19, text='Install Directory', style='Accent.TButton', command=self.open_install_dir
        )

        # Switch (Toggle Dark/Light Mode)
        self.switch = ttk.Checkbutton(
            self.widgets_frame, style='Switch.TCheckbutton', command=change_theme
        )
        self.switch.grid(row=99, column=0, padx=0, pady=0, sticky='se')
        # Force Theme Switch to the bottom of the window
        self.widgets_frame.grid_rowconfigure(21, weight=5)

        # Sizegrip (Resize Window icon located at bottom right)
        self.sizegrip = ttk.Sizegrip(self)
        self.sizegrip.grid(row=100, column=100, padx=(0, 5), pady=(0, 5))

        # Button list Used to disable while server list populates
        self.button_list = [
            self.refresh_all_button,
            self.refresh_selected_button,
            self.clear_filter,
            self.join_server_button,
            self.add_server_button
        ]
        # List of grid used for enabling/disabling between Tab selection
        self.grid_list = [
            self.refresh_all_button,
            self.refresh_selected_button,
            self.keypress_filter,
            self.clear_filter,
            self.join_server_button,
            self.add_server_button,
            self.show_favorites,
            self.show_history,
            # self.show_sponsored,
            self.show_modded,
            self.show_not_modded,
            self.show_first_person,
            self.show_third_person,
            self.show_not_passworded,
            self.show_public,
            self.show_private,
            self.favorite,
            self.entry,
            self.mod_entry,
            self.map_combobox,
            self.version_combobox,
            self.separator,
            self.refresh_mod_button,
            self.server_mods_entry,
            self.refresh_info_button,
            self.total_label,
            self.verify_separator,
            self.verify_integrity_button,
            self.refresh_info_label,
            self.manual_label,
            self.load_workshop_label,
            self.method_separator,
            self.auto_label,
            self.auto_sub_button,
            self.auto_sub_label,
            self.method_separator2,
            self.steam_download_button,
            self.steam_download_label,
            self.version_label,
            self.open_install_button,
            self.force_mod_update_server_button,
            self.force_mod_update_installed_button,
            self.installed_mods_entry
        ]
        # Widgets to display on Tab 1
        self.tab_1_widgets = [
            self.refresh_all_button,
            self.refresh_selected_button,
            self.keypress_filter,
            self.entry,
            self.mod_entry,
            self.map_combobox,
            self.version_combobox,
            self.show_favorites,
            self.show_history,
            # self.show_sponsored,
            self.show_modded,
            self.show_not_modded,
            self.show_first_person,
            self.show_third_person,
            self.show_not_passworded,
            self.show_public,
            self.show_private,
            self.clear_filter,
            self.separator,
            self.join_server_button,
            self.add_server_button,
            self.favorite
        ]
        # Widgets to display on Tab 2
        self.tab_2_widgets = [
            self.server_mods_entry,
            self.refresh_info_button,
            self.manual_label,
            self.load_workshop_label,
            self.refresh_info_label,
            self.method_separator,
            self.auto_label,
            self.auto_sub_button,
            self.auto_sub_label,
            self.method_separator2,
            self.steam_download_button,
            self.steam_download_label,
            self.force_mod_update_server_button
        ]
        # Widgets to display on Tab 3
        self.tab_3_widgets = [
            self.refresh_mod_button,
            self.total_label,
            self.verify_separator,
            self.verify_integrity_button,
            self.force_mod_update_installed_button,
            self.installed_mods_entry
        ]

        # Widgets to display on Tab 4
        self.tab_4_widgets = []

        # Widgets to display on Tab 5
        self.tab_5_widgets = [
            self.version_label,
            self.open_install_button
        ]


class ConsoleGuiOutput(object):
    def __init__(self, widget, tag, original_stream):
        self.widget = widget
        self.tag = tag
        self.max_lines = 1001
        self.original_stream = original_stream

    def write(self, stdstr):
        self.widget.config(state='normal')
        # Print to GUI Console Tab
        self.widget.insert('end', stdstr, (self.tag,))
        # scroll to end
        self.widget.see('end')

        # Limit Console tab scrollback
        lines = self.widget.get('0.0', 'end-1c').split('\n')
        if len(lines) > self.max_lines:
            # Delete the first line
            self.widget.delete('1.0', '2.0')

        self.widget.config(state='disabled')

        # Print to console/terminal
        if not disable_console_writes:
            if self.tag == 'stdout':
                sys.__stdout__.write(stdstr)
            else:
                sys.__stderr__.write(stdstr)

    def flush(self):
        self.original_stream.flush()


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
        directories. Set "normalized" directory to prevent issues
        when running Windows commands through subprocess. Ran into
        instances where Windows would interpret directories with
        forward slashes as command switches.
        """
        global settings
        directory = filedialog.askdirectory()
        debug_message = f'User chose directory: {directory}'
        logging.debug(debug_message)
        print(debug_message)

        if (directory and os.path.exists(directory)) or directory == '':
            normalized = os.path.normpath(directory)
            var.set(normalized)
            settings[str(var)] = normalized

            debug_message = f'Normalized directory: {normalized}'
            logging.debug(debug_message)
            print(debug_message)

            save_settings_to_json()
        elif directory != ():
            error_message = 'Warning: The selected directory does not exist.'
            logging.error(f'{error_message} - {str(var)} - {directory}')
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
            logging.error(f'{event.widget} - {error_message} - {tclerror}')
            print(error_message, tclerror)
            app.MessageBoxError(message=error_message)

    def on_install_change(self):
        """
        Save users settings whenever they change their Steam install type.
        Update gameExecutable to corresponding steam/flatpak command.
        """
        global settings, gameExecutable
        install_type = self.install_var.get()
        print(f'Steam Install Type: {install_type}')
        settings['install_type'] = install_type
        if linux_os:
            if 'flatpak' in install_type:
                gameExecutable = 'flatpak run com.valvesoftware.Steam'
            else:
                gameExecutable = 'steam'

        print(f'Game Executable: {gameExecutable}')
        save_settings_to_json()

    def on_theme_change(self):
        """
        Save users settings whenever they change the Theme.
        """
        global settings
        print(f'Default Theme/Mode: {self.theme_var.get()}')
        root.tk.call('set_theme', self.theme_var.get())
        settings['theme'] = self.theme_var.get()
        save_settings_to_json()

    def load_favs_startup_change(self):
        """
        Save users settings whenever they change the option to enable
        or disable loading Favorites and History on App Startup.
        """
        global settings
        print(f'Load Favorites/History on Startup: {self.load_favs_var.get()}')
        settings['load_favs_on_startup'] = self.load_favs_var.get()
        save_settings_to_json()

    def check_updates(self):
        """
        Check repo for updates to DayZ Py Launcher.
        """
        global settings
        print(f'Check for Launcher Updates: {self.check_updates_var.get()}')
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


def load_settings_from_file(settings):
    """
    Load settings to json configuation file. Alert user if corrupted.
    """
    if os.path.exists(settings_json):
        with open(settings_json, 'r') as json_file:
            try:
                settings.update(json.load(json_file))
                # print(json.dumps(settings, indent=4))
                logging.info(f'Load Settings: {json.dumps(settings, indent=4)}')
            except json.decoder.JSONDecodeError as err:
                error_message = (
                    'Error: Unable to load Settings file. Not in valid json format.\n\n'
                    'Try reconfiguring settings.'
                )
                logging.error(f'{error_message} - {err}')
                print(error_message)
                messagebox.showerror(message=error_message)


def server_pings(id, server_info):
    """
    Attempted to ping the server using the ping command. If that fails,
    since some servers block normal pings, perform an a2s query and use
    it's ping/response time.
    """
    ip, gamePort = server_info[5].split(':')
    queryPort = server_info[6]
    ping = get_ping_cmd(ip)

    if not ping and gamePort:
        ping = get_ping_gameport(ip, int(gamePort))

    if not ping:
        ping, _ = a2s_query(ip, queryPort)
    app.treeview.item(id, text='', values=server_info + (ping,))


def filter_treeview(chkbox_not_toggled: bool=True):
    """
    Used to filter out servers in the Server List tab.
    """
    global hidden_items

    # Gets values from Entry box
    filter_text = app.entry.get()
    # Gets values from Map combobox
    filter_map = app.map_combobox.get()
    # Gets values from Version combobox
    filter_version = app.version_combobox.get()
    # Gets values from Mods Entry box
    filter_mods = app.mod_entry.get()

    # Reset previous filters. If turned on, treeview is reset after every
    # filter update. Without it, you can 'stack' filters and search within
    # the current filtered view. If chkbox_not_toggled is false, which occurs
    # whenever a search/filter checkbox is toggled from On to Off, then we need
    # to restore the entries that were previously hidden.
    if app.keypress_filter_var.get() or not chkbox_not_toggled:
        restore_treeview()

    # Checks if entry and combobox values exist and are not the
    # default prefilled strings/text. i.e. Like 'Map' in the combobox
    text_entered = False
    if filter_text != '':
        text_entered = True

    map_selected = False
    if filter_map != '' and filter_map != app.default_map_combobox_text:
        map_selected = True

    version_selected = False
    if filter_version != '' and filter_version != app.default_version_combobox_text:
        version_selected = True

    mods_entered = False
    if filter_mods != '' and filter_mods != app.default_mod_text:
        # Convert user entered comma separated string/text to list
        mods_list = [x.strip() for x in filter_mods.split(',')]
        mods_entered = True

    # Gets values from Filter checkboxes
    show_favorites = app.show_favorites_var.get()
    show_history = app.show_history_var.get()
    # show_sponsored = app.show_sponsored_var.get()
    show_modded = app.show_modded_var.get()
    show_not_modded = app.show_not_modded_var.get()
    show_first_person = app.show_first_person_var.get()
    show_third_person = app.show_third_person_var.get()
    show_not_passworded = app.show_not_passworded_var.get()
    show_public = app.show_public_var.get()
    show_private = app.show_private_var.get()

    # Check if ANY of the bools above are true. Then hides/detaches Treeview items
    # that do not match. Stores hidden items in the global 'hidden_items' list.
    bool_filter_list = [
        text_entered, map_selected, version_selected, mods_entered, show_favorites, show_history, show_modded, #show_sponsored,
        show_not_modded, show_first_person, show_third_person, show_not_passworded, show_public, show_private
    ]
    if any(bool_filter_list):
        # Clear Server Info tab
        app.server_info_text.set('')
        app.server_mods_tv.delete(*app.server_mods_tv.get_children())

        # Unselect previously clicked treeview item
        app.treeview.selection_set([])
        app.favorite_var.set(value=False)

        for item_id in app.treeview.get_children():
            server_values = app.treeview.item(item_id, 'values')
            map_name = server_values[0]
            server_name = server_values[1]
            ip = server_values[5].split(':')[0]
            ip_port = server_values[5]
            queryPort = server_values[6]

            if text_entered and filter_text.startswith('!'):
                if filter_text.lower()[1:] in server_name.lower() or filter_text[1:] in ip_port:
                    hide_treeview_item(item_id)
            elif text_entered and filter_text.lower() not in server_name.lower() and filter_text not in ip_port:
                hide_treeview_item(item_id)

            if map_selected and filter_map.lower() not in map_name.lower():
                hide_treeview_item(item_id)

            if version_selected and filter_version.lower() not in serverDict[f'{ip}:{queryPort}'].get('version'):
                hide_treeview_item(item_id)

            if mods_entered:
                # Generate list of mods from server info in serverDict
                mod_names = [mod['name'] for mod in serverDict[f'{ip}:{queryPort}'].get('mods')]
                # Make sure ALL mods user entered have a match in the server's mod list (case insensitive).
                if not all(any(elem.lower() in mod.lower() for mod in mod_names) for elem in mods_list):
                    hide_treeview_item(item_id)

            if show_favorites and not settings.get('favorites').get(f'{ip}:{queryPort}'):
                hide_treeview_item(item_id)

            if show_history and not settings.get('history').get(f'{ip}:{queryPort}'):
                hide_treeview_item(item_id)

            # if show_sponsored and not serverDict[f'{ip}:{queryPort}'].get('sponsor'):
            #     hide_treeview_item(item_id)

            if show_first_person and not serverDict[f'{ip}:{queryPort}'].get('firstPersonOnly'):
                hide_treeview_item(item_id)

            if show_third_person and (serverDict[f'{ip}:{queryPort}'].get('firstPersonOnly') == None or serverDict[f'{ip}:{queryPort}'].get('firstPersonOnly')):
                hide_treeview_item(item_id)

            if show_modded and not serverDict[f'{ip}:{queryPort}'].get('mods'):
                hide_treeview_item(item_id)

            if show_not_modded and (serverDict[f'{ip}:{queryPort}'].get('mods') or not serverDict[f'{ip}:{queryPort}'].get('map')):
                hide_treeview_item(item_id)

            if show_not_passworded and serverDict[f'{ip}:{queryPort}'].get('password'):
                hide_treeview_item(item_id)
                # print('Hiding Passworded Server:', serverDict[f'{ip}:{queryPort}'].get('name'))

            if show_public and (not serverDict[f'{ip}:{queryPort}'].get('shard') or serverDict[f'{ip}:{queryPort}'].get('shard') == 'private'):
                hide_treeview_item(item_id)

            if show_private and (not serverDict[f'{ip}:{queryPort}'].get('shard') or serverDict[f'{ip}:{queryPort}'].get('shard') == 'public'):
                hide_treeview_item(item_id)


def filter_server_mods_treeview():
    """
    Used to filter out mod in the Server Mods tab.
    """
    global hidden_items_server_mods

    filter_text = app.server_mods_entry.get()

    text_entered = False
    if filter_text != '':
        text_entered = True

    restore_server_mods_treeview()

    # Check if ANY of the bools above are true. Then hides/detaches Treeview items
    # that do not match. Stores hidden items in the global 'hidden_items_server_mods' list.
    bool_filter_list = [text_entered]

    if any(bool_filter_list):

        for item_id in app.server_mods_tv.get_children():
            mod_values = app.server_mods_tv.item(item_id, 'values')
            mod_name = mod_values[0]
            workshop_id = mod_values[1]

            if text_entered and filter_text.lower() not in mod_name.lower() and filter_text not in workshop_id:
                hide_server_mods_treeview_item(item_id)


def filter_installed_mods_treeview():
    """
    Used to filter out mod in the Installed Mods tab.
    """
    global hidden_items_installed_mods

    filter_text = app.installed_mods_entry.get()

    text_entered = False
    if filter_text != '':
        text_entered = True

    restore_installed_mods_treeview()

    # Check if ANY of the bools above are true. Then hides/detaches Treeview items
    # that do not match. Stores hidden items in the global 'hidden_items_installed_mods' list.
    bool_filter_list = [text_entered]

    if any(bool_filter_list):

        for item_id in app.installed_mods_tv.get_children():
            mod_values = app.installed_mods_tv.item(item_id, 'values')
            mod_name = mod_values[1]
            workshop_id = mod_values[2]

            if text_entered and filter_text.lower() not in mod_name.lower() and filter_text not in workshop_id:
                hide_installed_mods_treeview_item(item_id)


def hide_treeview_item(item_id):
    """
    This hides/detaches Treeview items that do not match.
    Stores hidden items in the global 'hidden_items' list.
    """
    global hidden_items
    app.treeview.detach(item_id)
    hidden_items.add(item_id)


def hide_server_mods_treeview_item(item_id):
    """
    This hides/detaches Installed Mods items that do not match.
    Stores hidden items in the global 'hidden_items_server_mods' list.
    """
    global hidden_items_server_mods
    app.server_mods_tv.detach(item_id)
    hidden_items_server_mods.add(item_id)


def hide_installed_mods_treeview_item(item_id):
    """
    This hides/detaches Installed Mods items that do not match.
    Stores hidden items in the global 'hidden_items_installed_mods' list.
    """
    global hidden_items_installed_mods
    app.installed_mods_tv.detach(item_id)
    hidden_items_installed_mods.add(item_id)


def restore_treeview():
    """
    This hides/detaches Treeview items that do not match.
    Stores hidden items in the global 'hidden_items' list.
    """
    global hidden_items
    for item_id in hidden_items:
        app.treeview.reattach(item_id, '', 'end')

    treeview_sort_column(app.treeview, 'Players', True)
    hidden_items.clear()


def restore_server_mods_treeview():
    """
    This hides/detaches Installed Mods items that do not match.
    Stores hidden items in the global 'hidden_items_server_mods' list.
    """
    global hidden_items_server_mods
    for item_id in hidden_items_server_mods:
        app.server_mods_tv.reattach(item_id, '', 'end')

    hidden_items_server_mods.clear()


def restore_installed_mods_treeview():
    """
    This hides/detaches Installed Mods items that do not match.
    Stores hidden items in the global 'hidden_items_installed_mods' list.
    """
    global hidden_items_installed_mods
    for item_id in hidden_items_installed_mods:
        app.installed_mods_tv.reattach(item_id, '', 'end')

    hidden_items_installed_mods.clear()


def generate_serverDict(servers):
    """
    Generate the serverDict from the DZSA API. Also, adds each map
    to the dayz_maps list which is used to populate the Map combobox
    """
    server_to_exclude = []
    for index, server in enumerate(servers):
        ip = server.get("endpoint").get("ip")
        if ip == '0.0.0.0':
            server_to_exclude.append(index)
            print(f'Removed server due to invalid IP: {server}')
            continue
        queryPort = server.get("endpoint").get("port")
        server_map = server.get('map').title() if server.get('map').lower() != 'pnw' else 'PNW'
        dayz_version = server.get('version')

        serverDict[f'{ip}:{queryPort}'] = {
            'sponsor': server.get('sponsor'),
            'profile': server.get('profile'),
            'nameOverride': server.get('nameOverride'),
            'mods': server.get('mods'),
            'game': server.get('game'),
            "endpoint": {
                "ip": ip,
                "port": queryPort
            },
            'name': server.get('name'),
            'map': server_map,
            'mission': server.get('mission'),
            'players': server.get('players'),
            'maxPlayers': server.get('maxPlayers'),
            'environment': server.get('environment'),
            'password': server.get('password'),
            'version': dayz_version,
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

        # Generate Version list for Filter Combobox
        if dayz_version not in app.dayz_versions and dayz_version != '':
            app.dayz_versions.append(dayz_version)

    # Sort and set values for the dayzmap list ignoring case
    app.dayz_maps = sorted(app.dayz_maps, key=str.casefold)
    app.map_combobox['values'] = app.dayz_maps

    # Sort and set values for the dayz_versions list
    app.dayz_versions = sorted(app.dayz_versions, key=str.casefold)
    app.version_combobox['values'] = app.dayz_versions

    for server in server_to_exclude:
        servers.pop(server)


def refresh_servers():
    """
    This downloads the Server List from DayZ Standalone launcher API.
    Only ran when user clicks the Download Servers button.
    """
    # Disable buttons while Querying the API and Treeview Populates
    for button in app.button_list:
        button.configure(state='disabled')

    # Clear search filters and Server Info tab
    app.clear_filters()

    # Clear Treeview.
    app.treeview.delete(*app.treeview.get_children())

    # DayZ SA Launcher API. Set the inital Treeview sort to be by total
    # players online. From Highest to Lowest.
    dzsa_response = get_dzsa_data(dzsa_api_servers)
    if not dzsa_response:
        # Enable buttons now that API has failed. Allow user to try again
        for button in app.button_list:
            button.configure(state='enabled')
        return

    sort_column = 'players'
    servers = sorted(dzsa_response['result'], key=lambda x: x[sort_column], reverse=True)

    generate_serverDict(servers)

    # Loops through all the servers from DZSA API and return the info that is
    # being inserted into the treeview
    treeview_list = format_server_list_dzsa(servers)

    # This allows the user to only show the number of servers they want. Can
    # also help with performance since not have to unnecessarily load and ping
    # all servers. If set to 2,000, that would only display the top 2,000
    # highest populated servers. From testing, the API tends to return over 10,000
    # servers, but only about 2,500 tend to have players on them. Putting a limit
    # could also cause a server that just rebooted to be excluded/hidden from the
    # Treeview Server List. And another 'Download Servers' would need to be
    # performed once the server had time to regain it's population.'
    MAX_TREEVIEW_LENGTH = settings.get('max_servers_display')
    print(f'Max Servers to Display: {MAX_TREEVIEW_LENGTH}')

    for i, tuple in enumerate(treeview_list):
        app.treeview.insert('', tk.END, values=tuple)
        # Subtract 1 from MAX_TREEVIEW_LENGTH to account for Python starting count at 0
        if MAX_TREEVIEW_LENGTH and i == MAX_TREEVIEW_LENGTH - 1:
            break

    # Get the current list of treeview items before adding Favorites/History. Used to
    # get the pings in the thread below.
    treeview_children = app.treeview.get_children()

    # Insert Favorites/History if they don't exist in the server list from DZSAL
    load_fav_history()

    # Enable buttons now that Treeview is Populated
    for button in app.button_list:
        button.configure(state='enabled')

    # Start a new thread and pass the arguments.
    # server_pings is the function that each thread will run.
    # app.treeview.get_children() is a list/tuple of all the Treeview Item numbers
    # treeview_list is the tuple values for each Treeview item.
    if any([linux_os, windows_os]):
        thread = Thread(target=thread_pool, args=(server_pings, treeview_children, treeview_list), daemon=True)
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

    except tk.TclError as te:
        error_message = f'User probably pressed "Download Servers" again before first one completed: {te}'
        logging.error(error_message)
        print(error_message)


def refresh_selected():
    """
    For the currently selected server in the 'Server List' tab_1, directly query
    the server for an info, mod and ping update. Then update the existing
    treeview item
    """
    items = app.treeview.selection()

    # Start thread to query each server selected
    thread = Thread(target=query_item_list, args=(items,), daemon=True)
    thread.start()


def mod_meta_info(metaFile):
    """
    Reads the mods meta.cpp file to get/return the
    mod's name and workshop ID.
    """
    with open(metaFile) as f:
        contents = f.read()

        lines = contents.strip().split('\n')

        for line in lines:
            if 'name' in line:
                key, value = map(str.strip, line.split('='))
                name = value[1:-2]
            if 'publishedid' in line:
                key, value = map(str.strip, line.split('='))
                id = value[:-1]

    return name, id


def is_junction(path):
    """
    Used to check if a link/path is a Junction in Windows. Junctions don't appear
    to be supported in os.path.islink or is_symlink. Python only supports junctions
    starting with Python 3.12    
    """
    if windows_os:
        attributesW = ctypes.windll.kernel32.GetFileAttributesW(path)
        return (attributesW != -1) and (attributesW & 0x400) == 0x400


def ntfs_check(os_path_object):
    """
    Used to check if a drive is NTFS in order to create junctions in Windows OS.    
    """
    is_ntfs = True
    drive_root = os.path.splitdrive(os_path_object)[0] + '\\'
    drive_info = win32api.GetVolumeInformation(drive_root)
    name = drive_info[0]
    filesys = drive_info[4]
    
    if filesys.lower() != 'ntfs':
        is_ntfs = False
        error_message = (
            f'The drive DayZ is installed on ({name}) does not appear to be "NTFS". '
            'This will limit the ability to install mods. Filesystem is currently '
            f'detected as "{filesys}".'
        )
        logging.error(error_message)
        print(error_message)
        app.MessageBoxError(error_message)
        
    return is_ntfs


def start_steam():
    """
    Start Steam on Windows.
    """
    open_cmd = ['cmd', '/c', 'start', 'steam:']

    try:
        subprocess.Popen(open_cmd, creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(5)
    except subprocess.CalledProcessError as e:
        error_message = f'Failed to launch Steam.\n\n{e}'
        logging.error(error_message)
        print(error_message)
        app.MessageBoxError(error_message)


def remove_broken_symlinks(symlink_dir):
    """
    Removes old symlinks created by earlier version of the app.
    Removes symlinks to mods that have been uninstalled.
    Generate the hashDict which stores the mod ID, name and first 5
    characters of the sha1 hash of the mod ID (can be more than 5 characters
    if a collision is detected with another mod). In this function, it will
    just store the symlink name minus the @ which is the sha1[:5] generated
    when the symlink was originally created.
    
    is_symlink() does not support Windows Junctions. Use the is_junction 
    function on Windows. Also, is_dir() doesn't properly work on Windows, so 
    we use os.path.isdir().
    
    Sample dict format - modID: {'name': mod_name, 'hash': sha1[:5]}
    """
    hashDict.clear()
    # Remove old symlinks
    # with os.scandir(settings.get('dayz_dir')) as entries:
    #     for entry in entries:
    #         # Remove broken symlinks
    #         if entry.name.startswith('@'):
    #             logging.debug(f'Removing old symlink: {entry.name}')
    #             print(f'Removing old symlink: {entry.name}')
    #             os.unlink(entry.path)
                
    with os.scandir(symlink_dir) as entries:
        for entry in entries:
            if entry.name.startswith('@') and (entry.is_symlink() or is_junction(entry.path)) and not os.path.isdir(entry.path):
                logging.debug(f'Removing broken symlink: {entry.name}')
                print(f'Removing broken symlink: {entry.name}')
                os.unlink(entry.path)
            elif entry.name.startswith('@') and (entry.is_symlink() or is_junction(entry.path)) and os.path.isdir(entry.path):
                # mod_path = os.path.join(directory, folder_name)
                meta_path = os.path.join(entry, 'meta.cpp')
                if os.path.isfile(meta_path):
                    name, id = mod_meta_info(meta_path)
                    hashDict[id] = {'name': name, 'hash': entry.name[1:]}


def create_symlinks(directory, symlink_dir):
    """
    Creates symlinks to mods that have been installed from the Steam
    Workshop. Generates/updates the hashDict which will be used to
    load the mods and to prevent collisions since shorting the length
    of the stored hash and moving the symlinks to a subdirectory.
    This is due to the current bug/limitation in the Linux Steam client
    https://github.com/ValveSoftware/steam-for-linux/issues/5753.
    Moved the symlinks to a subdirectory to keep things more organized
    and to prevent clutter in the DayZ game directory.
    
    Windows requires elevated privileges to create symlinks. So, instead,
    we use Junctions. islink() does not support Windows Junctions. Use the 
    is_junction function on Windows.
    """
    # Get a sorted list of folder names
    #folder_names = [f.name for f in os.scandir(directory) if f.is_dir()]
    folder_names = [f.name for f in os.scandir(directory) if f.is_dir() and os.path.isfile(os.path.join(f.path, 'meta.cpp'))]
    # print(f'First Hash Dict: {json.dumps(hashDict, indent=4)}')
    for folder_name in folder_names:
        # seen_hashes = [mod['hash'] for mod in hashDict.values()]
        # print(f'{seen_hashes=}')
        mod_path = os.path.join(directory, folder_name)
        meta_path = os.path.join(mod_path, 'meta.cpp')

        name, id = mod_meta_info(meta_path)

        if not hashDict.get(id):

            # Calculate the SHA-1 hash for the mod id
            original_hash = hashlib.sha1(id.encode()).hexdigest()

            hash_length = 5  # Start with a minimum hash length

            while hash_length <= 40:
                # Get the hash using the current length
                current_hash = original_hash[:hash_length]

                symlink = os.path.join(symlink_dir, f'@{current_hash}')

                # Create symlink if it doesn't exist
                if (not os.path.islink(symlink) or not is_junction(symlink)) and not os.path.exists(symlink):
                    debug_message = f'Creating Symlink for: {name} - {symlink}'
                    logging.debug(debug_message)
                    print(debug_message)
                    hashDict[id] = {'name': name, 'hash': current_hash}
                    if linux_os:
                        os.symlink(mod_path, symlink)
                    if windows_os:
                        subprocess.Popen(f'mklink /J "{symlink}" "{mod_path}"', shell=True)
                    break

                # Check for collision
                elif current_hash in [mod['hash'] for mod in hashDict.values()]:
                    print(f"Collision found for hash prefix {current_hash} with mod '{name}' and '{id}'. Increasing hash length.")
                    hash_length += 1

                else:
                    # Log if no contitions met.
                    error_message = f'Possible issues creating Symlink for: {name} - {symlink}'
                    logging.error(error_message)
                    print(error_message)
                    break


def format_server_list_dzsa(servers):
    """
    Loops through all the servers and appends each server tuple to the
    list which will then be used to create the Treeview.
    """
    # print(servers)
    # Use set to catch/handle duplicate server listing in DZSA API
    treeview_list = []
    server_count = len(servers)
    for server in servers:
        map_name = server.get('map').title() if server.get('map').lower() != 'pnw' else 'PNW'
        name = server.get('name')
        players = server.get('players')
        max_players = server.get('maxPlayers')
        ip = server.get('endpoint').get('ip')
        queryPort = server.get('endpoint').get('port')
        port = server.get('gamePort')
        ip_port = f'{ip}:{port}'
        time = server.get('time')

        server_info = (map_name, name, players, max_players, time, ip_port, queryPort)

        if server_count > 1 and server_info not in treeview_list:
            treeview_list.append(server_info)
        elif server_count == 1:
            treeview_list = server_info

    return treeview_list


def get_mod_name(file):
    """
    Opens the file passed, in this case the Steam Mod meta.cpp file, which
    contains the mod info. Used to get the Name of the Mod when generating
    the modDict
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
    generate the modDict which stores all the locally installed mod's
    Steam Workshop ID, Mod Name and the size of the mod. Also, gets the
    total size of the Mod directory and is displayed on the right side
    of Tab 3 (Installed Mods)
    """
    global modDict
    # Loop through all items in the directory. Add to list if dir and name of dir begins with @. Sort the list and ignore case
    # symlinks = [f.name for f in os.scandir(directory) if f.is_dir() and f.name.startswith('@')]
    modDict = {f.name: {} for f in os.scandir(directory) if f.is_dir() and os.path.isfile(os.path.join(f.path, 'meta.cpp'))}
    total_size = 0

    for mod in modDict.keys():
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
        modDict[mod] = {
            'name': mod_name,
            'size': f'{round(mod_size / (1024 ** 2), 2):,}',  # Size in MBs
            # 'size': round(mod_size / (1024 ** 2), 2),
            'url': f'{workshop_url}{mod}'
        }

    # modDict['total_size'] = round(total_size / (1024 ** 3), 2)
    # modDict['total_size'] = total_size # Size in bytes

    # Convert to GB or MB based on the size
    if total_size >= 1024**3:  # If size is >= 1 GB
        total_size = f'{round(total_size / (1024**3), 2)} GBs'
    else:  # If size is < 1 GB
        total_size = f'{round(total_size / (1024**2), 2)} MBs'

    app.total_size_var.set(f'Total Size of Installed Mods\n{total_size}')
    # print(json.dumps(modDict, indent=4))


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
        # print(modDict)
        if modDict.get(str(workshop_id)):
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
    dayzWorkshop = os.path.join(settings.get('steam_dir'), 'content', app_id)
    symlink_dir = os.path.join(settings.get('dayz_dir'), sym_folder)

    # Check if dayzWorkshop exists, if not log and return
    if not os.path.exists(dayzWorkshop):
        debug_message = f"Either wrong directory set for Steam Workshop or no mods installed."
        logging.debug(debug_message)
        print(debug_message)
        app.MessageBoxInfo(debug_message)
        return

    # Make sure DayZ is on an NTFS drive if running in Windows. Else, we won't be able to 
    # create Junctions
    if windows_os and not ntfs_check(symlink_dir):
        return

    # Check if symlink_dir exists, if not create it
    if not os.path.exists(symlink_dir):
        os.makedirs(symlink_dir)
        debug_message = f"Symlink Directory created: {symlink_dir}"
        logging.debug(debug_message)
        print(debug_message)

    if any([linux_os, windows_os]):
        remove_broken_symlinks(symlink_dir)
        create_symlinks(dayzWorkshop, symlink_dir)

    app.installed_mods_tv.delete(*app.installed_mods_tv.get_children())
    get_installed_mods(dayzWorkshop)

    for mod, info in modDict.items():
        app.installed_mods_tv.insert('', tk.END, values=(
            # f'@{encode(mod)}',
            f'@{hashDict.get(mod).get("hash")}',
            info.get('name'),
            mod,
            info.get('url'),
            info.get('size')
            )
        )


def compare_modlist(server_mods, installed_mods):
    """
    Check if all mods on server are installed locally
    """
    missing_mods = False
    for id, name in server_mods.items():
        # print(id, name)
        if str(id) not in installed_mods:
            debug_message = f'Missing Mod: {name}'
            print(debug_message)
            logging.debug(debug_message)
            missing_mods = True

    return missing_mods


def generate_mod_param_list(server_mods):
    """
    Generates the ';' separated mod directory/symlink list that is
    appended to the Launch Command
    """
    mod_symlink_list = []
    # Loop through the server mods IDs and append encoded ID to list. This encoded ID
    # is the same one used to create the symlink and is used in the DayZ launch parameters
    # to tell it where to locate the installed mod.
    for id in server_mods.keys():
        mod_symlink_list.append(f'{sym_folder}/@{hashDict.get(str(id)).get("hash")}')

    # Convert the encoded mod list into a string. Each mod is separted by ';'.
    mod_str_list = ';'.join(mod_symlink_list)
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
    queryPort = item_values[6]

    return ip, port, queryPort


def launch_game():
    """
    Executed when user selects a server and clicks the Join Server button
    """
    # Check if 'Profile Name' is blank. If so, alert user. Some servers will
    # kick you for using the default 'Survivor' profile name. So, I'm leaving
    # the default blank in order to force the user to set one.
    global gameExecutable
    if not settings.get('profile_name'):
        error_message = 'No Profile Name is currently set.\nCheck the Settings tab, then try again.'
        logging.error(error_message)
        app.MessageBoxError(message=error_message)
        return

    steam_running = check_steam_process()
    debug_message = f'Steam Running: {steam_running}'
    logging.debug(debug_message)
    print(debug_message)
    if not steam_running:
        ask_message = "Steam isn't running.\nStart it?"
        answer = app.MessageBoxAskYN(message=ask_message)
        debug_message = f'Start Steam: {answer}'
        logging.debug(debug_message)
        print(debug_message)
        if not answer:
            error_message = 'Steam is required for DayZ.\nCancelling "Join Server"'
            logging.error(error_message)
            app.MessageBoxError(message=error_message)
            return
        elif answer and windows_os:
            start_steam()

    dayz_running = check_dayz_process()
    debug_message = f'DayZ Running: {dayz_running}'
    logging.debug(debug_message)
    print(debug_message)
    if dayz_running:
        warn_message = 'DayZ is already running.\nClose the game and try again'
        logging.warning(warn_message)
        app.MessageBoxWarn(message=warn_message)
        return

    if linux_os and not check_max_map_count():
        error_message = 'Unable to update max_map_count.\nCancelling "Join Server"'
        logging.error(error_message)
        app.MessageBoxError(message=error_message)
        return

    # Get currently selected treeview item/server
    item = app.treeview.selection()[0]
    # Get IP and Ports info
    ip, port, queryPort = get_selected_ip(item)
    serverName = app.treeview.item(item, 'values')[1]

    # Make sure we have at least the IP and Game Port
    if not all([ip, port]):
        error_message = 'Unable to get IP and/or Game Port.\nServer may be down'
        logging.error(error_message)
        app.MessageBoxError(message=error_message)
        return

    # Make sure Installed mods are up to date
    generate_mod_treeview()

    dayzWorkshop = os.path.join(settings.get('steam_dir'), 'content', app_id)
    # Get list of installed mod ID from the Steam Workshop directory. Handle case where either
    # no mods installed or wrong mod directory is configured. This could be a valid scenario
    # in the event the user has no mods and plays on an unmodded server.
    installed_mods = []
    if os.path.exists(dayzWorkshop):
        installed_mods = sorted([f.name for f in os.scandir(dayzWorkshop) if f.is_dir() and os.path.isfile(os.path.join(f.path, 'meta.cpp'))])

    # Query the server directly for current mods.
    server_mods = a2s_mods(ip, queryPort)

    # If failed to get mods directly from the server, fail over to using the mods
    # previously stored in the serverDict
    if not server_mods:
        warn_message = f'Failed getting mods directly from server ({ip}, {queryPort}. Using existing serverDict mod list.)'
        logging.warning(warn_message)
        print(warn_message)
        server_mods = get_serverDict_mods(ip, queryPort)

    # Alert user that mods are missing
    missing_mods = compare_modlist(server_mods, installed_mods)
    if missing_mods:
        ask_message = "Would you like to install all the missing mods for this server?"
        answer = app.MessageBoxAskYN(message=ask_message)
        debug_message = f'Install missing mods: {answer}'
        logging.debug(debug_message)
        print(debug_message)
        app.notebook.select(1)
        if answer:
            app.modRequests(app.server_mods_tv, 'Subscribe', 3000, True)
        else:
            error_message = 'Unable to join server. Check the "Server Info" tab for missing mods'
            logging.error(error_message)
            app.MessageBoxError(message=error_message)
        return

    # Create the list of commands/parameters that will be passed to subprocess to load the game with mods
    # required by the server along with any additional parameters input by the user
    if linux_os:
        default_params = [
            gameExecutable,
            '-applaunch',
            app_id,
            f'-connect={ip}:{port}',
            f'-name={settings.get("profile_name")}',
            '-nolauncher',
            '-nosplash',
            '-skipintro',
        ]
    elif windows_os:
        dayz_exe = 'DayZ_x64.exe' if '64bit' in architecture else 'DayZ.exe'
        if not get_dayz_version(dayz_exe, serverDict[f'{ip}:{queryPort}'].get('version')):
            return
        default_params = [
                gameExecutable,
                '0',
                '1',
                '1',
                '-exe',
                dayz_exe,
                f'-connect={ip}',
                f'-port={port}',
                f'-name={settings.get("profile_name")}',
                '-nolauncher',
                '-nosplash',
                '-skipintro',
            ]

    launch_cmd = default_params
    logging.debug(f'Initial launch_cmd: {launch_cmd}')

    # Append Additional parameters input by the user to launch command.
    if settings.get('launch_params'):
        print('Setting additional parameters.')
        steam_custom_params = settings.get('launch_params').strip().split(' ')
        logging.debug(f'Additional launch params: {steam_custom_params}')
        launch_cmd = launch_cmd + steam_custom_params

    # Generate mod parameter list and append to launch command
    if server_mods and not missing_mods:
        print('Setting mod parameter list.')
        mod_params = generate_mod_param_list(server_mods)
        # Append mod param to launch command
        logging.debug(f'Server mods params: {mod_params}')
        launch_cmd = launch_cmd + mod_params

    # launch_cmd = default_params + steam_custom_params + [mod_params]
    debug_message = f'{launch_cmd=}'
    logging.debug(debug_message)
    # print(debug_message)

    str_command = " ".join(launch_cmd)
    debug_message = f'Using launch command: {str_command}'
    logging.debug(debug_message)
    print(debug_message)

    try:
        if linux_os:
            subprocess.Popen(launch_cmd)
        elif windows_os:
            subprocess.Popen(str_command)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        error_message = f'Failed to launch DayZ.\n\n{e}'
        logging.error(error_message)
        print(error_message)
        app.MessageBoxError(error_message)

    # Add server to user's History'
    app.add_history(ip, queryPort)

    # Start the Loading Popup
    app.LoadingBox(ip, port, serverName)


def check_steam_process():
    """
    Check if Steam is running
    """
    try:
        if linux_os:
            output = subprocess.check_output(['pgrep', '-f', 'Steam/ubuntu12_'])
            # print(output.decode())
        elif windows_os:
            output = subprocess.check_output(['powershell', 'Get-Process "steam" | Select-Object -ExpandProperty Id'], creationflags=subprocess.CREATE_NO_WINDOW, text=True)
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
        elif windows_os:
            output = subprocess.check_output(['powershell', 'Get-Process "DayZ" | Select-Object -ExpandProperty Id'], creationflags=subprocess.CREATE_NO_WINDOW, text=True)
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
        debug_message = f'Current vm.max_map_count: {value}'
        logging.debug(debug_message)
        print(debug_message)

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
                    # Redirect stderr manually for GUI Console
                    sys.stderr.write(f'{result.stderr}\n')

                    debug_message = f'Output: {result}'
                    logging.debug(debug_message)
                    print(debug_message)
                    return True
                except subprocess.CalledProcessError as e:
                    error_code = f'Command failed with exit status: {e.returncode}'
                    logging.error(error_code)
                    print(error_code)
                    error_output = f'Error output: {e.stderr}'
                    logging.error(error_output)
                    print(error_output)
                    app.MessageBoxError(message='Command failed. Check your password.')
                    return False

    except subprocess.CalledProcessError as e:
        error_message = f'Error checking vm.max_map_count: {e}'
        logging.error(error_message)
        print(error_message)
        app.MessageBoxError(message='Failed to get max_map_count')
        return False


def a2s_query(ip, queryPort, update: bool=True):
    """
    Use the a2s module to query the server 'info' directly using the server's
    IP and Query Port (separte from the game port). Update the serverDict with
    latest info and get the ping response time.

    If this is an 'update' to an existing serverDict entry, then only update the
    dict else, create the entry (like when loading favorites and history from
    user's settings/config)

    Source: https://github.com/Yepoleb/python-a2s
    """
    try:
        info = a2s.info((ip, int(queryPort)))
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
                'port': int(queryPort)
            },
        }

        if update:
            serverDict[f'{ip}:{queryPort}'].update(server_update)
        else:
            serverDict[f'{ip}:{queryPort}'] = (server_update)
            serverDict[f'{ip}:{queryPort}']['name'] = info.server_name
            serverDict[f'{ip}:{queryPort}']['mods'] = []

        # Convert ping from seconds to milliseconds
        ping = round(info.ping * 1000)

    except TimeoutError:
        with stdout_lock:
            debug_message = f'Timed out getting info/ping from Server {ip} using QueryPort {queryPort}'
            logging.debug(debug_message)
            print(debug_message)
            ping = ''
            info = None
    except OSError as osError:
        with stdout_lock:
            # This error is raised on Windows if the server IP is 0.0.0.0
            error_message = f'OSError getting info/ping from Server {ip} using QueryPort {queryPort} - {osError}'
            logging.error(error_message)
            print(error_message)
            ping = ''
            info = None
    except IndexError as ie:
        with stdout_lock:
            error_message = f'IndexError from Server {ip} using QueryPort {queryPort} - Info: {info} - {ie}'
            logging.error(error_message)
            print(info)
            ping = ''
            info = None
    except KeyError as ke:
        with stdout_lock:
            error_message = f'KeyError from Server {ip} using QueryPort {queryPort} - Info: {info} - {ke}'
            logging.error(error_message)
            print(info)
            print(ip, queryPort)
            ping = ''
            info = None
            print(json.dumps(server_update, indent=4))

    return ping, info


def a2s_mods(ip, queryPort):
    """
    Queries the server directly to get the mods it's currently running.
    Updates the serverDict in the DZSA format (List of Dictionaries).
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
        # print(ip, port, queryPort)
        mods = dayzquery.dayz_rules((ip, int(queryPort))).mods
        mods_dict = {}
        server_mod_list = []

        api_mod_list = serverDict[f'{ip}:{queryPort}']['mods']
        # print(json.dumps(serverDict[f'{ip}:{queryPort}']['mods'], indent=4))

        for mod in mods:
            # print(mod)
            mods_dict[mod.workshop_id] = mod.name
            server_mod_list.append({'name': mod.name, 'steamWorkshopId': mod.workshop_id})

        # api_mod_list = update_mod_list(api_mod_list, server_mod_list)
        # print(json.dumps(mods_dict, indent=4))    w
        serverDict[f'{ip}:{queryPort}']['mods'] = update_mod_list(api_mod_list, server_mod_list)

    except TimeoutError:
        debug_message = f'Timed out getting mods from Server {ip} using QueryPort {queryPort}'
        logging.debug(debug_message)
        print(debug_message)
        # Use DZSAL Single Server Query API as a backup.
        get_dzsa_mods(ip, queryPort)
        mods_dict = None

    return mods_dict


def a2s_players(ip, queryPort):
    """
    Queries the server directly to get total number of players.
    Some servers began "spoofing" the player_count entry in the
    "a2s_info" queries.

    Source: https://github.com/Yepoleb/python-a2s
    """
    serverDict_info = serverDict.get(f'{ip}:{queryPort}')
    server_name = serverDict_info.get('name')
    reported_players = serverDict_info.get('players')
    max_players = serverDict_info.get('maxPlayers')

    try:
        actual_player_count = len(a2s.players((ip, int(queryPort))))
        debug_message = None
        if (reported_players > max_players) or (abs(reported_players - actual_player_count) > 10 and reported_players > actual_player_count):
            # Disabled printing in this function due to calling ThreadPoolExecutor in
            # Main thread and redirecting print/stdout to the GUI. This caused the
            # Executor to hang.
            debug_message = (
                f'Server is reporting an inaccurate player count or proxy cache is out of sync. '
                f'Claims: {reported_players} vs Actual: {actual_player_count} - {ip} - {queryPort} - {server_name}'
            )
    except TimeoutError:
        debug_message = f'Timed out getting player count from Server {ip} using QueryPort {queryPort}'
        actual_player_count = reported_players if reported_players < max_players else 0

    logging.debug(debug_message)
    serverDict[f'{ip}:{queryPort}']['players'] = actual_player_count

    return actual_player_count, debug_message


def get_dzsa_mods(ip, queryPort):
    """
    Use DZSAL Single Server Query API as a backup in the event a2s_mods
    fails. I've come across servers that always times out getting dayzquery.
    Believe it may be an MTU/ISP issue. Example: Packet Captures shows a
    1507 MTU from server 172.111.51.131 QueryPort 27017. Performing the query
    from a different ISP works.
    """
    debug_message = f'Failed over to getting mods from DZSAL for Server {ip} using QueryPort {queryPort}'
    logging.debug(debug_message)
    print(debug_message)

    url = f'https://dayzsalauncher.com/api/v1/query/{ip}/{queryPort}'
    dzsa_response = get_dzsa_data(url)
    if dzsa_response:
        serverDict[f'{ip}:{queryPort}']['mods'] = dzsa_response['result']['mods']


def get_ping_cmd(ip):
    """
    Run the ping command and capture the output
    """
    try:
        if linux_os:
            command = ['ping', '-c', '1', '-W', '1', ip]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        elif windows_os:
            command = ['ping', ip, '-n', '1', '-w', '1000']
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW, text=True)

        # Check if the command was successful
        if result.returncode == 0:
            # Use regular expressions to extract ping time in milliseconds
            ping_time_match = re.search(r'time=([\d.]+) ms', result.stdout)
            # print(ping_time_match)
            if ping_time_match:
                ping = ping_time_match.group(1)
                # print(ping)
                return round(float(ping))
            else:
                return None
        else:
            return None
            error_message = f'Ping command Error: {result.stderr}'
            logging.error(error_message)
            print(error_message)
    except Exception as e:
        error_message = f'Ping command Exception: {str(e)}'
        logging.error(error_message)
        print(error_message)
        return None


def get_ping_gameport(ip, gamePort):
    """
    Get the response time of an initial query to the server's Game Port.
    Many servers are now behind proxies, cache the Steam Queries, (which
    is why you appear to have low pings to servers in other countries)
    and they also block normal ICMP pings. This will give us a more
    accurate "Ping" time to those servers.
    """
    byte_data =  (
        b' \x00\x01\x08\x0e\xdc\xff\x1f\x01\x00\x00\x00\x01\x00\x00'
        b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\xae\x91\xe1\xeeDayZ` '
    )

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(1)
        try:
            s.connect((ip, gamePort))

            start_time = time.time()
            s.sendall(byte_data)
            response = s.recv(1024)
            end_time = time.time()

            ping = round((end_time - start_time) * 1000)

        except ConnectionRefusedError:
            end_time = time.time()
            ping = round((end_time - start_time) * 1000)
            print(f'({ip}, {gamePort}) - Connection Refused GamePort Ping: {ping} ms')

        except socket.timeout:
            ping = ''

        except OSError as e:
            error_message = f'(OS Error: {ip}, {gamePort}) - {e}'
            logging.error(error_message)
            print(error_message)
            ping = ''

    return ping


def CallSteamworksApi(request, mod_list, error_queue, progress_queue, print_queue):
    """
    Used to Subscribe or Unsubscribe to mods in Steam's Workshop.
    """
    steamworks = STEAMWORKS(_libs=steamworks_libraries)
    open_steam_downloads = False
    try:
        # Try to start Steamworks
        steamworks.initialize()

        attempts = 1
        while not steamworks.loaded() and attempts <= 30:
            time.sleep(0.5)
            attempts += 1
        if not steamworks.loaded():
            error_message = 'Failed to Initialize Steamworks. Verify Steam is working and try again.'
            logging.error(error_message)
            # print(error_message)
            print_queue.put(error_message)
            error_queue.put(error_message)
            return
    except Exception as error:
        error_message = f"Steam isn't running. Can't {request} to mod(s)."
        logging.error(f'{error_message} - {error}')
        # print(error_message)
        print_queue.put(error_message)
        error_queue.put(error_message)
        return

    def start_callbacks():
        while not stop_callbacks:
            steamworks.run_callbacks()
            time.sleep(0.1)

    # Define callback functions
    def cbSubItem(*args, **kwargs):
        # print('Item subscribed', args[0].result, args[0].publishedFileId)
        print_queue.put(('Item subscribed', args[0].result, args[0].publishedFileId))

    def cbUnsubItem(*args, **kwargs):
        # print('Item unsubscribed', args[0].result, args[0].publishedFileId)
        print_queue.put(('Item unsubscribed', args[0].result, args[0].publishedFileId))

    # Create a variable to signal the thread to stop
    stop_callbacks = False

    callback_thread = threading.Thread(target=start_callbacks, daemon=True)
    callback_thread.start()

    # Perform Steamworks Request
    # Item states/flags...
    # <EItemState.NONE: 0>
    # <EItemState.INSTALLED: 4>
    # <EItemState.SUBSCRIBED|INSTALLED: 5>
    # <EItemState.SUBSCRIBED|INSTALLED|NEEDS_UPDATE: 13>
    # <EItemState.SUBSCRIBED|NEEDS_UPDATE|DOWNLOADING: 25>
    if request == 'Unsubscribe' or request == 'ForceUpdate':
        steamworks.Workshop.SetItemUnsubscribedCallback(cbUnsubItem)
        for mod in mod_list:
            mod_name = mod[0]
            workshop_id = mod[1]
            # print(f'Unsubscribing to: {mod_name}')
            print_queue.put(f'Unsubscribing to: {mod_name}')
            item_state = steamworks.Workshop.GetItemState(workshop_id)
            while item_state != 4 and item_state != 0:
                UnsubscribeItem = steamworks.Workshop.UnsubscribeItem(workshop_id)
                time.sleep(1)
                item_state = steamworks.Workshop.GetItemState(workshop_id)
                # print(f'{(item_state,)}')
                print_queue.put(f'{(item_state,)}')
                progress_queue.put((mod_name, item_state))

    if request == 'Subscribe' or request == 'ForceUpdate':
        steamworks.Workshop.SetItemSubscribedCallback(cbSubItem)
        for mod in mod_list:
            mod_name = mod[0]
            workshop_id = mod[1]
            # print(f'Subscribing to: {mod_name}')
            print_queue.put(f'Subscribing to: {mod_name}')
            item_state = steamworks.Workshop.GetItemState(workshop_id)
            steamworks.Workshop.SubscribeItem(workshop_id)
            download_info = steamworks.Workshop.GetItemDownloadInfo(workshop_id)

            while item_state != 5:
                if item_state == 4 or item_state == 0:
                    steamworks.Workshop.SubscribeItem(workshop_id)
                # Steam doesn't seem to download updates while Steamworks is running.
                # Break and signal to open Steam Downloads page. Mod should begin
                # downloading or have the option to start the download.
                if request == 'ForceUpdate' and item_state == 13:
                    open_steam_downloads = True
                    break
                download_info = steamworks.Workshop.GetItemDownloadInfo(workshop_id)
                item_state = steamworks.Workshop.GetItemState(workshop_id)
                # print(f'{download_info}')
                # print_queue.put(download_info)
                # print(f'{(item_state,)}')
                print_queue.put(f'{(item_state,)}')
                progress_queue.put(
                    (mod_name, download_info.get('total'), download_info.get('progress'), item_state)
                )
                time.sleep(1)

    stop_callbacks = True
    steamworks.unload()
    if open_steam_downloads:
        print_queue.put('Open Steam Downloads')
    time.sleep(1)


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
            warn_message = f'DZSA API Timeout has occured. Try again.\n{url}'
            logging.warning(warn_message)
            print(warn_message)
            app.MessageBoxWarn(message=warn_message)
            return None

        if response.status_code == 200:
            return json.loads(response.content)
        else:
            error_message = f'HTTP Status Code: {response.status_code}'
            logging.error(error_message)
            print(error_message)
            return None

    except requests.exceptions.ConnectionError as e:
        error_message = f'Error connecting to DZSA API:\n{e}'
        logging.error(error_message)
        print(error_message)
        app.MessageBoxError(message=error_message)
        return None

    except json.decoder.JSONDecodeError as e:
        error_message = f'Invalid response from DZSA API:\n{e}\n\nTry again shortly.'
        logging.error(error_message)
        print(error_message)
        app.MessageBoxError(message=error_message)
        return None


def load_fav_history():
    """
    This will parse the saved settings json and add them to the Server List
    treeview when the app starts. Then start the thread to query each server.
    Allows you to use the app without the need of downloading all the servers
    from DZSA if you don't need them.
    """
    # Get all IP:QueryPorts & server 'names' from Favorites and History
    # Merge favorites and history into one dict.
    fav_history = settings.get('favorites') | settings.get('history')

    # Add to Server List treeview. If treeview is empty, create a list that has
    # a single entry ([0]) for one loop iteration in order to add Favorites
    # during the inital app launch
    treeview_ids = app.treeview.get_children() or [0]
    inserted_list = []
    for server, values in fav_history.items():
        for item_id in treeview_ids:
            ip, queryPort = server.split(':')
            stored_name = values.get('name')
            if item_id != 0:
                item_values = app.treeview.item(item_id, 'values')
                item_ip = item_values[5].split(':')[0]
                item_queryPort = item_values[6]
            else:
                item_ip, item_queryPort = '', ''

            if ip == item_ip and queryPort == item_queryPort:
                break
        else:
            # Insert row since IP & QueryPort not found in Treeview
            treeview_values = ('', stored_name, '', '', '', f'{ip}:', queryPort, '')
            id = app.treeview.insert('', tk.END, values=treeview_values)
            inserted_list.append(id)

    # Sort by name but on on initial loading of Favorites/History
    if treeview_ids == [0]:
        treeview_sort_column(app.treeview, 'Name', False)
    # Start new thread to query each server
    thread = Thread(target=query_item_list, args=(inserted_list, True), daemon=True)
    thread.start()


def manually_add_server():
    """
    Allows user to manually add a server to the Server List.
    """
    response = app.get_ip_port_prompt()

    if not response:
        return

    ip, queryPort = response

    treeview_ids = app.treeview.get_children() or [0]
    inserted_list = []

    for item_id in treeview_ids:
        if item_id != 0:
            item_values = app.treeview.item(item_id, 'values')
            item_ip = item_values[5].split(':')[0]
            item_queryPort = int(item_values[6])
        else:
            item_ip, item_queryPort = '', ''

        if ip == item_ip and queryPort == item_queryPort:
            # Select Item in Treeview and move into view
            app.treeview.selection_set(item_id)
            app.treeview.see(item_id)

            info_message = f'Server is already in the List: {ip}:{queryPort}'
            print(info_message)
            logging.info(info_message)
            app.MessageBoxInfo(message=info_message)
            break
    else:
        # Insert row since IP & QueryPort not found in Treeview
        treeview_values = ('', '', '', '', '', f'{ip}:', queryPort, '')
        id = app.treeview.insert('', tk.END, values=treeview_values)
        inserted_list.append(id)
        # Add to Favorites
        settings['favorites'][f'{ip}:{queryPort}'] = {'name': ''}
        save_settings_to_json()
        # Add to serverDict
        serverDict[f'{ip}:{queryPort}'] = {'name': '', 'mods': [], 'version': 'Unknown'}
        # Select Item in Treeview and move into view
        app.treeview.selection_set(id)
        app.treeview.see(id)

    if inserted_list:
        # Start new thread to query each server
        thread = Thread(target=query_item_list, args=(inserted_list,), daemon=True)
        thread.start()


def query_item_list(itemList, loading_favs=False):
    """
    Directly query each server in Favorites/History then update the
    Server List treeview and serverDict. Updated Favorite/History name
    if changed.
    """
    MAX_WORKERS = settings.get('max_sim_pings')
    if MAX_WORKERS < 1:
        MAX_WORKERS = 1

    # Make the querying of each server multithreaded
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Create a dict to store the futures
        futures_dict = {}
        for id in itemList:
            item_values = app.treeview.item(id, 'values')
            ip = item_values[5].split(':')[0]
            queryPort = item_values[6]

            # Submit the a2s_query function to the thread pool and store the future
            # Specify 'False' for the update argument in order to trigger an insert
            # into the serverDict instead of an update. Also, creates necessary keys
            # in the serverDict for future query updates
            future = executor.submit(a2s_query, ip, queryPort, False)
            futures_dict[future] = {'id': id, 'values': item_values}

    try:
        # Loop through completed futures and update treeview with server info
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            dayz_maps_updated = False
            version_updated = False
            fav_updated = False
            # Add delays when also performing a2s player query. Seems we may be getting
            # rate limited when rapidly querying the server multiple times.
            delay_mod_query = False
            for future in as_completed(futures_dict):
                id = futures_dict[future].get('id')
                item_values = futures_dict[future].get('values')
                ip, gamePort = item_values[5].split(':')
                queryPort = item_values[6]
                stored_name = item_values[1]
                ping, info = future.result()
                if info:
                    server_map = info.map_name.title() if info.map_name.lower() != 'pnw' else 'PNW'
                    server_name = info.server_name
                    players = info.player_count
                    maxPlayers = info.max_players
                    gamePort = info.port
                    gametime = info.keywords[-5:]
                    dayz_version = info.version

                    # Only perform player query and add delays when not loading favorites
                    # Makes load times much faster and most people probably aren't favoriting
                    # those servers anyway. If they are, then they probably don't care about
                    # the fake count. They can still find out if the use "Refresh Selected".
                    if players > maxPlayers or (players > 20 and not loading_favs):
                        time.sleep(0.25)
                        delay_mod_query = True
                        players, message = a2s_players(ip, queryPort)
                        serverDict[f'{ip}:{queryPort}']['players'] = players
                        if message:
                            print(message)

                    gamePortPing = get_ping_gameport(ip, gamePort) if ping < 60 else None
                    if gamePortPing:
                        print(f'Query Port Ping = {ping}. Using Game Port Ping: {gamePortPing} - {server_name}')
                        ping = gamePortPing

                    treeview_values = (server_map, server_name, players, maxPlayers, gametime, f'{ip}:{gamePort}', queryPort, ping)
                    app.treeview.item(id, text='', values=treeview_values)

                    # Generate Map list for Filter Combobox
                    if server_map not in app.dayz_maps and server_map != '':
                        app.dayz_maps.append(server_map)
                        dayz_maps_updated = True

                    # Generate Version list for Filter Combobox
                    if dayz_version not in app.dayz_versions and dayz_version != '':
                        app.dayz_versions.append(dayz_version)
                        version_updated = True

                    # Update stored server name if needed
                    if stored_name != server_name:
                        if settings['favorites'].get(f'{ip}:{queryPort}'):
                            settings['favorites'][f'{ip}:{queryPort}'] = {'name': server_name}
                        if settings['history'].get(f'{ip}:{queryPort}'):
                            settings['history'][f'{ip}:{queryPort}']['name'] = server_name
                        fav_updated = True

                    # Add server to executer to query server mods
                    if delay_mod_query:
                        time.sleep(0.25)
                    mod_future = executor.submit(a2s_mods, ip, queryPort)

                elif not serverDict.get(f'{ip}:{queryPort}'):
                    serverDict[f'{ip}:{queryPort}'] = {'name': stored_name, 'mods': [], 'version': 'Unknown'}

                # Update ping if server is down or connection timed out
                elif serverDict.get(f'{ip}:{queryPort}'):
                    # Some servers block both pings and Query Port. Try pinging this way
                    if gamePort:
                        ping = get_ping_gameport(ip, int(gamePort))
                        if ping:
                            print(f'Other pings failed. Using Game Port Ping: {ping} - {ip}:{queryPort}')
                    item_values = list(item_values)
                    item_values[7] = ping
                    app.treeview.item(id, text='', values=item_values)

        # Sort and set values for the dayzmap list ignoring case
        if dayz_maps_updated:
            app.dayz_maps = sorted(app.dayz_maps)
            app.map_combobox['values'] = app.dayz_maps

        # Sort and set values for the dayz_versions list
        if version_updated:
            app.dayz_versions = sorted(app.dayz_versions, key=str.casefold)
            app.version_combobox['values'] = app.dayz_versions

        if fav_updated:
            save_settings_to_json()

        # Force a refresh of currently selected item
        app.OnSingleClick('')

    except tk.TclError as te:
        error_message = f'User probably pressed "Download Servers" before Favorites completed: {te}'
        logging.error(error_message)
        print(error_message)


def get_serverDict_mods(ip, queryPort):
    """
    Returns Dictionary from the serverDict of all mods where the key
    is the Steam workshop ID and the value is the name of the mod.
    { "1559212036": "Community Framework" }
    """
    mods_dict = {}
    for mod in serverDict[f'{ip}:{queryPort}']['mods']:
        mods_dict[mod.get('steamWorkshopId')] = mod.get('name')

    return mods_dict


def bool_to_yes_no(bool):
    """
    This just returns Yes or No depending if bool was True or False.
    Used for populating the Server Info and displaying Yes/No instead
    of True/False.
    """
    if bool is None:
        return 'Unknown'

    bools = ('No','Yes')
    return bools[bool]


def treeview_sort_column(tv, col, reverse):
    """
    This Sorts a column when a user clicks on a column heading in a treeview.
    Convert treeview values to float before sorting columns where needed.
    https://stackoverflow.com/questions/67209658/treeview-sort-column-with-float-number
    """
    neg_inf_cols = ['Players', 'Max']
    pos_inf_cols = ['Ping']

    # Used for sorting numerically. Mainly to handle the mod size column and other int columns.
    # Also handles numeric columns that may have empty stings in the event the server is down.
    # In that case, use negative or positive infinity to force them to the top or bottom of the
    # sort.
    def column_key(item):
        value = item[0]
        val_is_dec = value.isdecimal()

        if col in neg_inf_cols and not val_is_dec:
            return -float('inf')
        elif col in pos_inf_cols and not val_is_dec:
            return float('inf')
        else:
            return float(value.replace(",", ""))

    def ip_column_key(item):
        ip_str, port_str = item[0].split(':')
        ip = ipaddress.IPv4Address(ip_str)
        port = int(port_str) if port_str else 0
        return ip, port

    # Use casefold to make the sorting case insensitive
    l = [(tv.set(k, col).casefold(), k) for k in tv.get_children('')]

    try:
        if col != 'IP:GamePort':
            # l.sort(key=lambda t: float(t[0].replace(",", "")), reverse=reverse)
            l.sort(key=column_key, reverse=reverse)
        else:
            l.sort(key=ip_column_key, reverse=reverse)
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


def parse_vdf(data, target_app_id):
    """
    Parse Steam VDF to get game directory
    """
    path = None
    apps_section = False

    for line in data:
        line = line.strip()

        if line.startswith('"path"'):
            path = line.split('"')[3]
        elif line == '"apps"':
            apps_section = True
        elif line.startswith("}"):
            apps_section = False
        elif apps_section and line.startswith(f'"{target_app_id}"'):
            return path

    return None


def get_dayz_version(exe, server_version):
    """
    Gets the version of the DayZ exe file.
    https://stackoverflow.com/questions/580924/how-to-access-a-files-properties-on-windows
    """
    dayz_exe = f'{os.path.join(settings.get("dayz_dir"), exe)}'
    language, codepage = win32api.GetFileVersionInfo(dayz_exe, '\\VarFileInfo\\Translation')[0]
    # Returns version in this format... "1.23.0.157045"
    product_version = win32api.GetFileVersionInfo(dayz_exe, '\\StringFileInfo\%04x%04x\ProductVersion' % (language, codepage))
    # Convert product_version to format used in DayZ... "1.23.157045"
    dayz_version = '.'.join(product_version.split('.')[:2] + product_version.split('.')[3:])
    
    print(f'Local DayZ Version: {dayz_version}')
    print(f'Server DayZ Version: {server_version}')

    join_server = True
    if dayz_version != server_version:
        error_message = (
            f'Your DayZ version ({dayz_version}) does not match the one on the server ({server_version}). '
            'Try checking for updates in Steam. Also, verify your DayZ install from the "Installed Mods" tab or '
            'from the DayZ properties in your Steam Library. Continue Joining Server anyways?'
        )
        logging.error(error_message)
        print(error_message)
        join_server = app.MessageBoxAskYN(error_message)
        
    return join_server


def detect_install_directories():
    """
    Fairly basic attempt at automatically detecting and settings the users DayZ
    and Steam Workshop mod directories. Parses Steam's vdf file which stores the
    workshop folders for each game.
    """
    # Set default directories for Linux
    if linux_os:
        home_dir = os.path.expanduser('~')
        default_steam_dir = f'{home_dir}/.local/share/Steam'
        flatpak_steam_dir = f'{home_dir}/.var/app/com.valvesoftware.Steam/data/Steam'

        if os.path.isdir(default_steam_dir):
            vdfDir = f'{default_steam_dir}/steamapps/'

        elif os.path.isdir(flatpak_steam_dir):
            vdfDir = f'{flatpak_steam_dir}/steamapps/'

        else:
            logging.error('Unable to detect Linux Steam install directories')
            return

        logging.debug(f'Steam libraryfolders directory set to: {vdfDir}')

    # Set default directories for Windows
    elif windows_os:
        import winreg

        if '64bit' in architecture:
            steam_key = r'SOFTWARE\Wow6432Node\Valve\Steam'
        else:
            steam_key = r'SOFTWARE\Valve\Steam'

        try:
            hklm_steam = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, steam_key)
            default_steam_dir = winreg.QueryValueEx(hklm_steam, "InstallPath")[0]
        except FileNotFoundError as e:
            error_message = f'Steam Reg Install Path not found: {e}'
            logging.error(error_message)
            print(error_message)
            default_steam_dir = r'C:\Program Files (x86)\Steam'

        vdfDir = f'{default_steam_dir}\\config\\'
        logging.debug(f'Steam libraryfolders directory set to: {vdfDir}')

    else:
        print('Unsupported OS. Skipping Install Check...')
        return

    # Use Steam's 'libraryfolders.vdf' to find DayZ and Steam Workshop directories
    # Idea from https://github.com/aclist/dztui
    vdfFile = os.path.join(vdfDir, 'libraryfolders.vdf')

    if (settings.get('dayz_dir') == '' or not os.path.exists(settings.get('dayz_dir'))) and os.path.isfile(vdfFile):

        path = None
        with open(vdfFile, 'r') as vdfData:
            path = parse_vdf(vdfData, app_id)

            if path:
                settings['dayz_dir'] = os.path.join(path, 'steamapps', 'common', 'DayZ')
                settings['steam_dir'] = os.path.join(path, 'steamapps', 'workshop')
                logging.debug(f'Setting DayZ directory as: {settings["dayz_dir"]}')
                logging.debug(f'Setting Steam directory as: {settings["steam_dir"]}')
                # save_settings_to_json()

    else:
        error_message = 'Unable to detect DayZ & Workshop directories'
        logging.error(error_message)
        print(error_message)


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
    global linux_os, windows_os, architecture

    system_os = platform.system()
    architecture = platform.architecture()[0]

    if system_os.lower() == 'linux':
        linux_os = True
    elif system_os.lower() == 'windows':
        windows_os = True
    
    logging.debug(f'Platform: {system_os}')
    logging.debug(f'Architecture: {architecture}')


def get_latest_release(url):
    """
    Used to download files from GitLab to be used for checking the latest version
    or downloading the latest install/upgrade script.
    """
    try:
        session = requests.Session()
        retry = Retry(connect=5, backoff_factor=1.0)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('https://', adapter)

        response = session.get(url, headers=headers)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as err:
        error_message = f'Error connecting to GitLab for Updates: {url}\n\n{err}'
        logging.error(error_message)
        print(error_message)
        app.MessageBoxError(error_message)
        return None


def update_check():
    """
    Check for latest updates directly from the dayz_py_launcher.py on GitLab
    """
    # Download the raw dayz_py_launcher.py
    py_raw = get_latest_release(main_branch_py)

    if py_raw:
        # Get version from download
        latest_version = py_raw.split("version = '")[1].split("'\n")[0]

        # Check if local version differs from GitLab version.
        logging.info(f'Installed version: {version} - Latest version: {latest_version}')
        return version != latest_version


def install_update():
    """
    Download the latest installer script, add executable permission and run
    """
    # Download the script
    if linux_os:
        script = 'dayz_py_installer.sh'
        install_script = get_latest_release(main_branch_sh)
    elif windows_os:
        script = 'dayz_py_installer.ps1'
        install_script = get_latest_release(main_branch_ps1)

    if install_script:
        with open(script, 'w') as script_file:
            script_file.write(install_script)
    else:
        error_message = 'Failed to download the script.'
        logging.error(error_message)
        print(error_message)
        app.MessageBoxError(error_message)
        return

    if linux_os:
        # Make the script executable
        os.chmod(script, 0o755)

    # Run script
    try:
        if linux_os:
            subprocess.run(['./' + script], check=True)
        elif windows_os:
            subprocess.run(['powershell', '-ExecutionPolicy', 'Unrestricted', '-File', script], check=True)
        info_message = 'Install complete. Restart the Launcher to apply changes.'
        logging.info(info_message)
        app.MessageBoxInfo(message=info_message)
    except subprocess.CalledProcessError as e:
        error_message = f'Failed to run the Upgrade Script.\n\n{e}'
        logging.error(error_message)
        print(error_message)
        app.MessageBoxError(error_message)


def app_updater():
    """
    Function to combine update check, download and install if user chooses to accept
    """
    is_installed = is_app_installed()
    print(f'Installed: {is_installed}')
    updated = update_check()

    if updated and is_installed:
        ask_message = 'Update Available. Would you like to install it now?'
        answer = app.MessageBoxAskYN(message=ask_message)
        print('Update App:', answer)
        if answer and (linux_os or windows_os):
            install_update()

    elif updated:
        ask_message = 'There is an update available in the Gitlab repo. Would you like to download it?'
        answer = app.MessageBoxAskYN(message=ask_message)
        print('Open Gitlab Repo?:', answer)
        if answer:
            app.open_url('https://gitlab.com/tenpenny/dayz-py-launcher')


def is_app_installed():
    """
    Function to check if DayZ Py Launcher is installed or just running from
    a "portable" directory
    """
    if linux_os:
        home_dir = os.path.expanduser('~')
        os_install_dir = f'{home_dir}/.local/share/dayz_py'
    elif windows_os:
        os_install_dir = f'{os.getenv("APPDATA")}\\dayz_py'

    return os_install_dir == app_directory


def set_initial_geometry():
    """
    Should help resolve issues with all widgets not fitting the
    default windows size on different OS's and desktop environments
    when manually setting geometry. If you don't hard code the
    geometry, TKinter resizes the window every time a widget is
    added or removed. Like when switching between Notebook tabs.
    """
    # Get the initial geometry of the main window
    initial_geometry = root.winfo_geometry().split('+')[0]
    # width, height = map(int, initial_geometry.split('x'))
    # modified_geometry = f'{width}x{height - 10}'
    # Set the geometry permanently
    root.geometry(initial_geometry)


if __name__ == '__main__':

    # Check user's platform
    check_platform()

    # Load Launcher Settings
    load_settings_from_file(settings)

    if linux_os and settings.get('install_type') == 'flatpak':
        gameExecutable = 'flatpak run com.valvesoftware.Steam'

    root = tk.Tk()
    root.title(appName)

    iconFile = os.path.join(app_directory, 'dayz_icon.png')
    img = PhotoImage(file=iconFile)

    if (settings.get('dayz_dir') == '' or not os.path.exists(settings.get('dayz_dir'))):
        detect_install_directories()

    if windows_os:
        import ctypes
        import win32api
        apply_windows_gui_fixes()
        sym_folder = '_pyw'
        gameExecutable = f'{os.path.join(settings.get("dayz_dir"), "DayZ_BE.exe")}'

        disable_console_writes = 'pythonw.exe' in sys.executable.lower()

    root.iconphoto(True, img)

    # Set the theme/mode configured in the settings
    # Source: https://github.com/rdbende/Azure-ttk-theme/tree/gif-based/
    themeFile = os.path.join(app_directory, 'azure.tcl')
    root.tk.call('source', themeFile)
    root.tk.call('set_theme', settings.get('theme'))

    app = App(root)
    app.pack(fill='both', expand=True)

    # Set initial window size
    # root.geometry('1280x690')
    app.after(1000, set_initial_geometry)

    # Warn user if not running on linux_os:
    if not linux_os and not windows_os:
        warn_message = 'Unsupported Operating Sytem.'
        print(warn_message)
        app.MessageBoxWarn(message=warn_message)

    # Generate Installed Mods treeview if DayZ directory in settings
    if settings.get('dayz_dir') != '':
        app.after(100, generate_mod_treeview)

    # Load Favorites and History on Startup unless disabled by user
    if settings.get('load_favs_on_startup'):
        app.after(500, load_fav_history)

    # Check for Updates. Delay it until after GUI is up to force popup
    # to center of the app.
    if settings.get('check_updates') and (linux_os or windows_os):
        app.after(3000, lambda: Thread(target=app_updater, daemon=True).start())

    root.mainloop()
