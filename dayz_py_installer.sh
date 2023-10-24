#!/usr/bin/env bash

# Use DZGUI's check for Steam Deck & write desktop function(https://github.com/aclist/dztui)
cpu=$(cat /proc/cpuinfo | grep "AMD Custom APU 0405")
if [[ -n "$cpu" ]]; then
    is_steam_deck=1
else
    is_steam_deck=0

write_desktop_file(){
cat <<-END
[Desktop Entry]
Version=1.0
Type=Application
Terminal=false
Exec=python $dayz_py_file
Name=DayZ Py Launcher
Path=$share
Comment=DayZ Py Launcher
Icon=$share/dayz_icon.png
Categories=Game
	END
}

# Set paths
desktopFile="$HOME/.local/share/applications/dayz_py.desktop"
share="$HOME/.local/share/dayz_py"
dayz_py_file="$share/dayz_py_launcher.py"
tarDownload="https://gitlab.com/tenpenny/dayz-py-launcher/-/archive/main/dayz-py-launcher-main.tar.gz"

# Create the required directories
mkdir -p "$share"

# Download the app and save it to the desired location. Extract.
curl -L $tarDownload | tar zxf - --strip-components=1 -C "$share"

# Write the content to the desktopFile
write_desktop_file > "$desktopFile"
if [[ $is_steam_deck -eq 1 ]]; then
    write_desktop_file > "$HOME/Desktop/dzgui.desktop"
fi
