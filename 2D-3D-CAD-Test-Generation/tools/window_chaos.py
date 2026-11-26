"""Deliberately switch focus between unrelated applications while a SolidWorks recording runs (acceptance test for window-only capture).

    python tools/window_chaos.py --wait-for <.../solidworks_recording.json> --log chaos.json [--cycles 4] [--dwell 3.5]

Opens, with LOUD distinctive content so a leak is unmistakable: an isolated Chrome (solid red page, throw-away profile), VS Code (new window on a temp folder),
Explorer (C:\\Windows) and Notepad.  Waits until the recording manifest says "recording", then brings each window over SolidWorks in turn (always-on-top + maximized,
plus a partial-overlap move), logging every switch with epoch timestamps, until the recording is finished.  Closes only the windows it opened.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import win32api
import win32con
import win32gui
import win32process

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def windows() -> dict[int, tuple[str, str, int]]:
    out = {}

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h):
            out[h] = (win32gui.GetWindowText(h), win32gui.GetClassName(h), win32process.GetWindowThreadProcessId(h)[1])
    win32gui.EnumWindows(cb, None)
    return out


def wait_new(before: set, match, timeout=25.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        for h, (title, cls, pid) in windows().items():
            if h not in before and match(title, cls):
                return h
        time.sleep(0.3)
    return None


def cover(h: int, maximize=True) -> None:
    try:
        win32gui.ShowWindow(h, win32con.SW_MAXIMIZE if maximize else win32con.SW_SHOWNORMAL)
        win32gui.SetWindowPos(h, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        win32api.keybd_event(0x12, 0, 0, 0)                      # a tapped ALT lets SetForegroundWindow succeed
        win32api.keybd_event(0x12, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32gui.SetForegroundWindow(h)
    except Exception:                                            # noqa: BLE001
        pass


def uncover(h: int) -> None:
    try:
        win32gui.SetWindowPos(h, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        win32gui.ShowWindow(h, win32con.SW_SHOWNORMAL)
    except Exception:                                            # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait-for", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--cycles", type=int, default=4)
    ap.add_argument("--dwell", type=float, default=3.5)
    ap.add_argument("--timeout", type=float, default=600)
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="sf_chaos_"))
    (tmp / "LEAK_MARKER_NOTEPAD.txt").write_text(("LEAK MARKER NOTEPAD\n" * 40), encoding="utf-8")
    (tmp / "LEAK_MARKER_VSCODE.txt").write_text(("LEAK MARKER VSCODE\n" * 40), encoding="utf-8")
    (tmp / "leak.html").write_text("<html><body style='background:#ff0000;margin:0'><h1 style='color:white;font-size:120px'>LEAK MARKER CHROME</h1></body></html>", encoding="utf-8")
    opened: dict[str, int] = {}
    procs = []
    before = set(windows())
    # Chrome: an isolated throw-away profile, never the user's
    procs.append(subprocess.Popen([CHROME, f"--user-data-dir={tmp / 'chrome_profile'}", "--no-first-run", "--new-window", (tmp / "leak.html").as_uri()]))
    h = wait_new(before, lambda t, c: c == "Chrome_WidgetWin_1" and "LEAK" in t.upper() or "leak.html" in t.lower())
    if h:
        opened["chrome"] = h
    before = set(windows())
    procs.append(subprocess.Popen(["cmd", "/c", "code", "-n", str(tmp / "LEAK_MARKER_VSCODE.txt")], creationflags=0x08000000))
    h = wait_new(before, lambda t, c: "LEAK_MARKER_VSCODE" in t, timeout=40)
    if h:
        opened["vscode"] = h
    before = set(windows())
    procs.append(subprocess.Popen(["explorer.exe", r"C:\Windows"]))
    h = wait_new(before, lambda t, c: c == "CabinetWClass")
    if h:
        opened["explorer"] = h
    before = set(windows())
    procs.append(subprocess.Popen(["notepad.exe", str(tmp / "LEAK_MARKER_NOTEPAD.txt")]))
    h = wait_new(before, lambda t, c: "LEAK_MARKER_NOTEPAD" in t)
    if h:
        opened["notepad"] = h
    print("opened:", {k: v for k, v in opened.items()}, flush=True)
    for h in opened.values():                                    # park them away from SolidWorks until the recording is running
        try:
            win32gui.ShowWindow(h, win32con.SW_MINIMIZE)
        except Exception:                                        # noqa: BLE001
            pass

    def status() -> str:
        try:
            return json.loads(Path(a.wait_for).read_text(encoding="utf-8")).get("status", "")
        except Exception:                                        # noqa: BLE001
            return ""
    t0 = time.time()
    while status() != "recording" and time.time() - t0 < a.timeout:
        time.sleep(0.2)
    events = [{"event": "recording_seen", "t": time.time()}]
    print("recording started; switching applications now", flush=True)
    order = ["chrome", "vscode", "explorer", "notepad"]
    done = False
    for cycle in range(a.cycles):
        for name in order:
            h = opened.get(name)
            if not h:
                continue
            if status() != "recording":
                done = True
                break
            ev = {"event": "cover", "app": name, "hwnd": h, "cycle": cycle, "t_start": time.time(), "mode": "maximized"}
            cover(h, True)
            time.sleep(a.dwell)
            ev["t_end"] = time.time()
            uncover(h)
            win32gui.ShowWindow(h, win32con.SW_MINIMIZE)
            events.append(ev)
            time.sleep(0.6)
            if name == "notepad":                                # a partial overlap: a normal-size window dragged over part of SolidWorks
                try:
                    sw = [x for x, (t, c, p) in windows().items() if t.startswith("SOLIDWORKS")]
                    if sw:
                        l, t_, r, b = win32gui.GetWindowRect(sw[0])
                        ev2 = {"event": "partial_overlap", "app": name, "hwnd": h, "cycle": cycle, "t_start": time.time(), "mode": "moved over the viewport"}
                        win32gui.ShowWindow(h, win32con.SW_SHOWNORMAL)
                        win32gui.SetWindowPos(h, win32con.HWND_TOPMOST, l + 250, t_ + 150, 420, 360, win32con.SWP_SHOWWINDOW)
                        time.sleep(a.dwell)
                        ev2["t_end"] = time.time()
                        uncover(h)
                        win32gui.ShowWindow(h, win32con.SW_MINIMIZE)
                        events.append(ev2)
                except Exception:                                # noqa: BLE001
                    pass
        if done:
            break
    while status() == "recording" and time.time() - t0 < a.timeout:
        time.sleep(0.5)
    events.append({"event": "recording_finished", "t": time.time(), "status": status()})
    for name, h in opened.items():                               # close ONLY what this script opened
        try:
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        except Exception:                                        # noqa: BLE001
            pass
    Path(a.log).write_text(json.dumps({"opened": opened, "events": events, "tmp": str(tmp)}, indent=1), encoding="utf-8")
    print("chaos done; events:", len(events), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
