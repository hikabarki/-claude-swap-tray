# cswap-tray

A Windows system-tray front-end for [claude-swap](https://github.com/realiti4/claude-swap).

claude-swap ships a menu-bar app for macOS but nothing equivalent for Windows.
`cswap-tray` fills that gap: a tray icon that shows your active account's usage
at a glance and lets you switch accounts, toggle auto-switch, and open the live
dashboard — all from a click, no terminal.

It drives the real CLI under the hood (`python -m claude_swap ... --json`), so
it never keeps its own state and always matches what `cswap` itself would do.

## Features

- **Usage at a glance** — the tray icon is colour-coded by the active account's
  worst window: green < 50 %, amber < 80 %, red otherwise (grey when nothing
  managed is active). Hover for the exact 5h / 7d percentages.
- **Click to switch** — every managed account is listed with its usage; click
  one to switch to it.
- **Switch to best pick** — jump to the account with the most quota left.
- **Rotate to next** — cycle to the next account.
- **Auto-switch toggle** — start/stop the `cswap auto` engine, which switches
  for you as you approach a rate limit.
- **Open live dashboard** — launches `cswap watch` in a terminal.

## Requirements

- Windows
- Python 3.12+
- [claude-swap](https://github.com/realiti4/claude-swap) (installed
  automatically as a dependency)

## Install

Using [uv](https://docs.astral.sh/uv/) (recommended):

```powershell
uv tool install .
```

This installs a windowed `cswap-tray` command (no console window). Then run it:

```powershell
cswap-tray
```

The icon appears in the system tray (click the `^` overflow arrow if hidden).

### Start automatically at login

Press `Win+R`, type `shell:startup`, Enter, and drop a shortcut to
`cswap-tray` (or to [`scripts/start-tray.vbs`](scripts/start-tray.vbs)) into
that folder.

## Development

```powershell
uv venv
uv pip install -e .
python -m cswap_tray                 # run from source
scripts\start-tray-debug.bat         # run with a visible console for logs
```

## How it works

`cswap-tray` polls `cswap list --json` every 30 seconds (and on demand) to read
account usage, renders the icon and menu from that, and calls `cswap switch` /
`cswap auto` for actions. Because every operation goes through the installed
`claude-swap` CLI, the tray and the CLI can never disagree.

## License

MIT
