# Changelog
## 1.7.0 (2023-11-21)
### Added
* Reinsert Favorites/History in the DZSAL server list if they don't exist
* Backup for getting server mods in the event dayzquery timedout. Failover to DZSAL's "Check Server" query.
* Option to "Copy IP:QueryPort" to clipboard in the Right Click menu (Server List)

### Changed
* Refactored the Load Favorites and History on Startup. Should be faster now and scale better as your Favorites and History list grows.
* Centered the time column

### Fixed
* Bug when filtering by "Version" in Favorites/History and the server was down. Caused a NoneType error for those servers.
* Bug when sorting numeric columns (Players, Max, etc) and the server was down. Caused it to sort as a string.
* Bug that allowed double-clicking on a column header to try opening a Steam Workshot URL

## 1.6.3 (2023-11-19)
### Added
* Right click menu to Server Info. More options to Installed mods right click
* Open Symlink Directory now highlights symlink folder on Linux

### Fixed
* Bug that prevented first single click on server in Server List from working when previous focus was in the filter entry box 

## 1.6.0 (2023-11-15)
### Added
* Ability to Join a Server on Windows

### Changed
* Organize Symlinks for both Linux and Windows. Check of collisions in symlink names. Symlinks are now in a subdirectory inside the DayZ install directory. On Linux this will be "_py" and Windows will be "_pyw"

### Fixed
* Previous commit in issue #1 caused a new issue if the user selected the wrong Workshop directory. Mod Directory was then created in the wrong location. Now just alert the user to verify settings or wait for Steam to create the directory if it doesn't exist upon first Mod install.
* Using tkinters' built in askdirectory() would save directories with forward slashes on Windows, which would later result in subprocess commands with directories as parameters being interpreted as command switches.

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
