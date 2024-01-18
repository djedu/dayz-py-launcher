# Changelog
## 2.3.0 (2024-01-18)
### Added
* Check local DayZ version against server version on Windows.
* Force Mod Update button/option for when Steam isn't detecting any available Workshop mod updates.

### Fixed
* Saved servers (Favorite/History) that are down not being filtered when selecting First/Third Person or Public/Private.
* Server pings not updating when server is down or connection timed out
#

## 2.2.0 (2024-01-06)
### Added
* 5 new filter options for Public & Private Servers, First and Third Person perspective and Hiding servers with passwords

### Changed
* Size and padding of various widgets to minimize window size due to additional filter options.

### Fixed
* Missing flush() method on the file-like object (ConsoleGuiOutput) used for redirecting stdout & stderr to GUI.
#

## 2.1.0 (2024-01-05)
### Added
* Console tab for displaying terminal/console output in the GUI.
* NTFS check on Windows to make sure the Filesystem supports creating junctions
* CTRL + A to select all items/text in the Server Info, Installed Mods and Console tab.

### Changed
* Increased the auto refresh timer after unsubscribing to mods.

### Fixed
* Issue with global vaiable access on Windows when multiprocessing during Steamworks subscriptions.
* Issue with CMD and PowerShell windows opening when using "subprocess" and launching app using "pythonw.exe" on Windows
* Issue with "sys.__stdout__.write" and "sys.__stderr__.write" throwing exceptions or crashing when using "pythonw.exe" on Windows
#

## 2.0.0 (2023-12-29)
### Added
* Steamworks API to allow managing Steam Workshop mod subscriptions/installation. Subscribe or unsubscribe to individual mods or install all missing mods for a selected server.
* Button to open Steam Downloads (Server Info tab).
* Button to verify DayZ installtion integrity through Steam. Performs the same operations as "Verify integrity of game files" from DayZ properties in your Steam Library (Installed Mods tab).
* Button to open the DayZ Py Launcher installation or current working directory (Settings tab).

### Changed
* Made the Thread that watches for the DayZ process to start after "Joining a Server" a daemon.
* Right clicking preserves multi-selection in the "Server Info" and "Installed Mods" treeviews as long as you right click one of the selected items. This allows Subscribing/Unsubscribing to multiple mods in the same request.
#

## 1.8.1 (2023-12-12)
### Added
* Logging/displaying the URL that failed DZSAL's server check.

### Changed
* Adjust Server Mods treeview to allow longer names to be displayed.

### Fixed
* Removed unused modules (Queue).
#

## 1.8.0 (2023-11-24)
### Added
* Popup Notification when Joining a server. Will wait for the DayZ exe to be found before closing, else alert the user after 30 seconds that something may be wrong.

### Changed
* Made "Refresh Selected" threaded.

### Fixed
* Bug that did not use serverDict mods in the event the a2s query failed.
* Bug that prevented messages from popping up in the event setting the vm.max_map_count failed
#

## 1.7.0 (2023-11-21)
### Added
* Reinsert Favorites/History in the DZSAL server list if they don't exist
* Backup for getting server mods in the event dayzquery timed out. Failover to DZSAL's "Check Server" query.
* Option to "Copy IP:QueryPort" to clipboard in the Right Click menu (Server List)

### Changed
* Refactored the Load Favorites and History on Startup. Should be faster now and scale better as you add more Favorites and History to your list.
* Centered the time column

### Fixed
* Bug when filtering by "Version" in Favorites/History and the server was down. Caused a NoneType error for those servers.
* Bug when sorting numeric columns (Players, Max, etc) and the server was down. Caused it to sort as a string.
* Bug that allowed double-clicking on a column header to try opening a Steam Workshot URL
#

## 1.6.3 (2023-11-19)
### Added
* Right click menu to Server Info. More options to Installed mods right click
* Open Symlink Directory now highlights symlink folder on Linux

### Fixed
* Bug that prevented first single click on server in Server List from working when previous focus was in the filter entry box
#

## 1.6.0 (2023-11-15)
### Added
* Ability to Join a Server on Windows

### Changed
* Organize Symlinks for both Linux and Windows. Check of collisions in symlink names. Symlinks are now in a subdirectory inside the DayZ install directory. On Linux this will be "_py" and Windows will be "_pyw"

### Fixed
* Previous commit in issue #1 caused a new issue if the user selected the wrong Workshop directory. Mod Directory was then created in the wrong location. Now just alert the user to verify settings or wait for Steam to create the directory if it doesn't exist upon first Mod install.
* Using tkinters' built in askdirectory() would save directories with forward slashes on Windows, which would later result in subprocess commands with directories as parameters being interpreted as command switches.
#

## 1.5.0 (2023-11-09)
### Added
* Read Registry Keys to get Steam Install directory on Windows.
* Ability to "Select All" servers in the "Server List" using CTRL+A

### Changed
* Only ping servers during "Refresh All Servers" on Linux
* Only install updates on Linux
* New method for parsing Steam's libraryfolders.vdf
* Spacing in the Server Info label

### Fixed
* Missing license for modules/libraries
* Opening Mod directories on Windows
#

## 1.4.1 (2023-11-06)
### Added
* Right click context menu for Installed Mods. Allows you to open the Mod directory in a file browser/explorer.
#

## 1.4.0 (2023-11-06)
### Added
* Right click context menu for copying various server information, option to Join Server and Remove server from History
* Additional check during "Join Server" to make sure selected Server info contains IP and Game Port.

### Changed
* Only try to add/remove Symlinks on Linux
