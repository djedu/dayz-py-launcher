# Changelog
### Upcoming...
* Ability to Join a Server on Windows
* Organize Symlinks for both Linux and Windows. Check of collisions in symlink names

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
