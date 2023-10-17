#!/usr/bin/env bash

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
[[ -f $desktopFile ]] && rm $desktopFile
cat <<-END > "$desktopFile"
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
