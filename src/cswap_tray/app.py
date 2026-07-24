"""
Windows system-tray front-end for claude-swap.

The Windows counterpart to claude-swap's macOS menu-bar app. It shells out to
the CLI (``python -m claude_swap ... --json``) to read account usage and to
switch accounts, so it always stays in sync with whatever ``cswap`` would do.

Left- or right-click the tray icon:
  * each managed account, with its 5h / 7d usage — click one to switch to it
  * Switch to best pick  (most quota left)
  * Rotate to next
  * Auto-switch  (toggle the ``cswap auto`` engine on/off)
  * Refresh now
  * Open live dashboard  (``cswap watch``, in a new terminal window)
  * Quit

The icon colour tracks the active account's worst window: green < 50 %,
amber < 80 %, red otherwise (grey when nothing is active or usage is unknown).
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import pystray
from PIL import Image, ImageDraw, ImageFont
from pystray import Menu, MenuItem

# --------------------------------------------------------------------------- #
# Locating the claude-swap CLI
# --------------------------------------------------------------------------- #
# ``claude-swap`` is a declared dependency, so it lives in the same environment
# as this package and ``python -m claude_swap`` resolves to it. sys.executable
# is that interpreter. On Windows, CREATE_NO_WINDOW keeps every CLI call silent
# (no console window flashing on each poll).
PYTHON = sys.executable
# The Textual dashboard needs a real console, which pythonw.exe detaches from;
# resolve the sibling python.exe for that one case.
CONSOLE_PYTHON = str(Path(PYTHON).with_name("python.exe"))
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
POLL_SECONDS = 30

# Icon colours (R, G, B).
GREEN = (46, 160, 67)
AMBER = (210, 153, 34)
RED = (218, 54, 51)
GREY = (110, 118, 129)


# --------------------------------------------------------------------------- #
# CLI plumbing
# --------------------------------------------------------------------------- #
def _run(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "claude_swap", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=_NO_WINDOW,
    )


def _run_json(args: list[str], *, timeout: int = 60):
    """Run a cswap command with --json and return the parsed object, or None."""
    try:
        proc = _run([*args, "--json"], timeout=timeout)
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------- #
# Icon rendering
# --------------------------------------------------------------------------- #
def _load_font(size: int):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_icon(color: tuple[int, int, int], label: str) -> Image.Image:
    """A rounded square in `color` with a short white label (e.g. account #)."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, size - 3, size - 3], radius=14, fill=color)
    font = _load_font(38)
    # centre the label
    try:
        bbox = d.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]), label,
               fill=(255, 255, 255), font=font)
    except Exception:
        d.text((18, 12), label, fill=(255, 255, 255), font=font)
    return img


def usage_color(pct5: float | None, pct7: float | None) -> tuple[int, int, int]:
    vals = [p for p in (pct5, pct7) if p is not None]
    if not vals:
        return GREY
    worst = max(vals)
    if worst >= 80:
        return RED
    if worst >= 50:
        return AMBER
    return GREEN


# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #
class CswapTray:
    def __init__(self) -> None:
        self.icon = pystray.Icon(
            "cswap",
            make_icon(GREY, "cs"),
            "claude-swap",
            menu=Menu(self._menu_items),  # callable → rebuilt on every open
        )
        self._state = {"accounts": [], "active": None, "error": None}
        self._auto_proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()

    # ---- data ----------------------------------------------------------- #
    def refresh(self) -> None:
        data = _run_json(["list"])
        with self._lock:
            if data is None:
                self._state["error"] = "cswap unavailable"
            else:
                self._state["error"] = None
                self._state["accounts"] = data.get("accounts", [])
                self._state["active"] = data.get("activeAccountNumber")
        self._apply_icon()
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def _active_account(self) -> dict | None:
        with self._lock:
            for a in self._state["accounts"]:
                if a.get("active"):
                    return a
        return None

    def _apply_icon(self) -> None:
        acct = self._active_account()
        if acct is None:
            self.icon.icon = make_icon(GREY, "cs")
            self.icon.title = "claude-swap — no managed account active"
            return
        usage = acct.get("usage") or {}
        p5 = (usage.get("fiveHour") or {}).get("pct")
        p7 = (usage.get("sevenDay") or {}).get("pct")
        self.icon.icon = make_icon(usage_color(p5, p7), f"{acct['number']}")
        email = acct.get("email", "?")
        if p5 is None and p7 is None:
            tip = f"claude-swap — active: {email} (usage unknown)"
        else:
            tip = f"claude-swap — active: {email}  5h {p5 or 0:.0f}%  7d {p7 or 0:.0f}%"
        self.icon.title = tip[:127]  # Windows tooltip limit

    # ---- menu ----------------------------------------------------------- #
    def _account_label(self, a: dict) -> str:
        dot = "● " if a.get("active") else "   "
        name = a.get("email", "?")
        status = a.get("usageStatus")
        usage = a.get("usage") or {}
        p5 = (usage.get("fiveHour") or {}).get("pct")
        p7 = (usage.get("sevenDay") or {}).get("pct")
        if status == "relogin_required":
            tail = "⚠ re-login needed"
        elif status == "api_key":
            tail = "API key"
        elif p5 is not None or p7 is not None:
            tail = f"5h {p5 or 0:.0f}% · 7d {p7 or 0:.0f}%"
        else:
            tail = "usage unknown"
        return f"{dot}{name}   {tail}"

    def _menu_items(self):
        with self._lock:
            accounts = list(self._state["accounts"])
            error = self._state["error"]

        if error:
            yield MenuItem(f"⚠ {error}", None, enabled=False)
            yield Menu.SEPARATOR
        elif not accounts:
            yield MenuItem("No managed accounts", None, enabled=False)
            yield MenuItem("Run `cswap add` to add one", None, enabled=False)
            yield Menu.SEPARATOR
        else:
            for a in accounts:
                yield MenuItem(
                    self._account_label(a),
                    self._make_switch_action(a["number"]),
                    checked=self._make_checked(a),
                    radio=True,
                )
            yield Menu.SEPARATOR

        yield MenuItem("Switch to best pick", lambda _i, _it: self._switch_best())
        yield MenuItem("Rotate to next", lambda _i, _it: self._switch_next())
        yield MenuItem(
            "Auto-switch",
            lambda _i, _it: self._toggle_auto(),
            checked=lambda _it: self._auto_running(),
        )
        yield Menu.SEPARATOR
        yield MenuItem("Refresh now", lambda _i, _it: self._async(self.refresh))
        yield MenuItem("Open live dashboard", lambda _i, _it: self._open_dashboard())
        yield MenuItem("Quit", self._quit)

    # ---- actions -------------------------------------------------------- #
    # pystray inspects each action's argcount, so per-account callbacks must be
    # clean 2-arg (action) / 1-arg (checked) closures — no default-arg binding.
    def _make_switch_action(self, number: int):
        def action(icon, item):
            self._switch_to(number)
        return action

    def _make_checked(self, account: dict):
        def checked(item):
            return bool(account.get("active"))
        return checked

    def _async(self, fn, *a) -> None:
        threading.Thread(target=fn, args=a, daemon=True).start()

    def _switch_to(self, number: int) -> None:
        self._async(self._do, ["switch", str(number)])

    def _switch_best(self) -> None:
        self._async(self._do, ["switch", "--strategy", "best"])

    def _switch_next(self) -> None:
        self._async(self._do, ["switch"])

    def _do(self, args: list[str]) -> None:
        try:
            _run(args, timeout=120)
        except Exception:
            pass
        self.refresh()

    # ---- auto-switch engine --------------------------------------------- #
    def _auto_running(self) -> bool:
        return self._auto_proc is not None and self._auto_proc.poll() is None

    def _toggle_auto(self) -> None:
        if self._auto_running():
            try:
                self._auto_proc.terminate()
            except Exception:
                pass
            self._auto_proc = None
        else:
            try:
                self._auto_proc = subprocess.Popen(
                    [PYTHON, "-m", "claude_swap", "auto"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=_NO_WINDOW,
                )
            except Exception:
                self._auto_proc = None
        try:
            self.icon.update_menu()
        except Exception:
            pass

    # ---- dashboard ------------------------------------------------------ #
    def _open_dashboard(self) -> None:
        # A visible terminal is required for the Textual TUI, so this one
        # intentionally opens a window.
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "claude-swap watch",
                 "cmd", "/k", CONSOLE_PYTHON, "-m", "claude_swap", "watch"],
            )
        except Exception:
            pass

    # ---- lifecycle ------------------------------------------------------ #
    def _quit(self, _icon=None, _item=None) -> None:
        self._stop.set()
        self._wake.set()
        if self._auto_running():
            try:
                self._auto_proc.terminate()
            except Exception:
                pass
        self.icon.stop()

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            self.refresh()
            self._wake.wait(POLL_SECONDS)
            self._wake.clear()

    def _setup(self, icon: pystray.Icon) -> None:
        icon.visible = True
        threading.Thread(target=self._poll_loop, daemon=True).start()

    def run(self) -> None:
        self.icon.run(setup=self._setup)


def main() -> None:
    """Console/GUI entry point (see ``[project.gui-scripts]`` in pyproject)."""
    CswapTray().run()


if __name__ == "__main__":
    main()
