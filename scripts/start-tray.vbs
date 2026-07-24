' Launches the cswap tray app silently — no console window at all.
' Requires the package to be installed (see README): `uv tool install .`
' installs a windowed `cswap-tray` command that this script starts.
Set sh = CreateObject("WScript.Shell")
sh.Run "cswap-tray", 0, False
