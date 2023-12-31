$appName = 'DayZ Py Launcher'
$mainBranch = 'dayz-py-launcher-main'
$zipUrl = "https://gitlab.com/tenpenny/dayz-py-launcher/-/archive/main/$mainBranch.zip"

# Set local directory paths
$tempDirectory = [System.IO.Path]::GetTempPath()
$installFolder = [System.IO.Path]::Combine($env:APPDATA, 'dayz_py')
$zipFilePath = [System.IO.Path]::Combine($tempDirectory, "$appName.zip")

# Create the full path to the subfolder within the destination folder
$destinationSubfolder = Join-Path -Path $installFolder -ChildPath $mainBranch

# Download the zip file
Invoke-WebRequest -Uri $zipUrl -OutFile $zipFilePath

# Extract the contents of the specified subfolder
Expand-Archive -Path $zipFilePath -DestinationPath $installFolder -Force

# Move the contents of the subfolder to the destination folder
Move-Item -Path (Join-Path -Path $destinationSubfolder -ChildPath "*") -Destination $installFolder -Force -ErrorAction SilentlyContinue

# Remove the now-empty subfolder
Remove-Item -Path $destinationSubfolder -Force -Recurse

# Remove the zip file
Remove-Item -Path $zipFilePath -Force

# Create a shortcut in the Start Menu
$pythonScriptPath = [System.IO.Path]::Combine($installFolder, "dayz_py_launcher.py")
$shortcutPath = [System.IO.Path]::Combine($env:APPDATA, 'Microsoft\Windows\Start Menu\Programs', "$appName.lnk")

# Create a shortcut
$WScriptShell = New-Object -ComObject WScript.Shell
$Shortcut = $WScriptShell.CreateShortcut($shortcutPath)
$Shortcut.Description = $appName
$Shortcut.IconLocation = "$installFolder\dayz_icon.ico"
$Shortcut.TargetPath = 'pythonw.exe'
$Shortcut.Arguments = "`"$pythonScriptPath`""
$Shortcut.WorkingDirectory = $installFolder
$Shortcut.Save()
