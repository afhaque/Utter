"""Recording overlay — frameless, always-on-top, NON-focus-stealing (BUILD_PLAN §12.7).

Tkinter has no no-activate flag, so we apply Win32 extended styles via ctypes:
WS_EX_NOACTIVATE (never takes focus), WS_EX_TRANSPARENT (click-through) and
WS_EX_TOOLWINDOW (hidden from Alt-Tab). Show/hide use ShowWindow(SW_SHOWNOACTIVATE)
instead of deiconify(), which would activate the window and break the paste flow.

Threading (ADR 0001): one dedicated thread owns the Tk root and mainloop. Other threads
never touch Tk — they put state changes on a queue that the animation tick consumes.
"""

from __future__ import annotations

import ctypes
import logging
import math
import queue
import threading
import tkinter as tk
from collections import deque
from collections.abc import Callable

log = logging.getLogger(__name__)

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
SW_SHOWNOACTIVATE = 4
SW_HIDE = 0
GA_ROOT = 2

# Palette from the otter logo: chocolate pill, amber waveform, orange recording dot
WIDTH, HEIGHT = 196, 36
BARS = 20
BG = "#2a1a10"
ACCENT = "#d98e3f"
DOT = "#e87722"
MAGIC = "#010203"  # color-keyed fully transparent (rounded corners)
TICK_MS = 40
HIDDEN_TICK_MS = 200  # command-poll cadence while invisible (no redraws)
LEVEL_GAIN = 4.0  # display gain over the recorder's raw peak


class Overlay:
    def __init__(self) -> None:
        self._commands: queue.Queue[tuple[str, object]] = queue.Queue()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="utter-overlay", daemon=True)
        self._hwnd: int | None = None
        self._state = "hidden"
        self._level_getter: Callable[[], float] | None = None
        self._levels: deque[float] = deque([0.0] * BARS, maxlen=BARS)
        self._spin = 0
        self._otter = None

    # -- public API (thread-safe: only touches the queue / user32) ----------------------
    def start(self) -> None:
        self._thread.start()
        if not self._ready.wait(timeout=10):
            raise RuntimeError("overlay thread failed to start")

    def show_recording(self, level_getter: Callable[[], float]) -> None:
        self._commands.put(("recording", level_getter))

    def show_transcribing(self) -> None:
        self._commands.put(("transcribing", None))

    def hide(self) -> None:
        self._commands.put(("hidden", None))

    @property
    def hwnd(self) -> int | None:
        """Toplevel hwnd — used by verification probes."""
        return self._hwnd

    # -- overlay thread ------------------------------------------------------------------
    @staticmethod
    def _load_otter_badge(size: int = 26):
        """Circular otter-face badge; None if the asset is unavailable."""
        try:
            from PIL import ImageTk

            from utter.ui.branding import otter_face

            return ImageTk.PhotoImage(otter_face(size))
        except Exception:
            log.warning("otter badge unavailable — overlay renders without it")
            return None

    def _run(self) -> None:
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        # color-key transparency for rounded corners (mutually exclusive with -alpha)
        root.attributes("-transparentcolor", MAGIC)
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = (screen_w - WIDTH) // 2
        y = screen_h - HEIGHT - 90
        root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")
        root.configure(bg=MAGIC)
        canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT, bg=MAGIC, highlightthickness=0)
        canvas.pack()
        self._otter = self._load_otter_badge()  # PhotoImage needs the Tk root to exist
        root.update_idletasks()

        user32 = ctypes.windll.user32
        hwnd = user32.GetAncestor(canvas.winfo_id(), GA_ROOT)
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
        )
        user32.ShowWindow(hwnd, SW_HIDE)  # start hidden, never activated
        self._hwnd = hwnd
        self._ready.set()
        log.info("overlay ready (hwnd=%s)", hwnd)

        def tick() -> None:
            # visibility is DERIVED from state here, on the Tk thread — the command
            # queue is the single channel, so show/hide can never interleave badly
            while True:
                try:
                    state, payload = self._commands.get_nowait()
                except queue.Empty:
                    break
                if state == self._state:
                    continue
                if state == "hidden":
                    user32.ShowWindow(hwnd, SW_HIDE)
                elif self._state == "hidden":
                    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
                self._state = state
                if state == "recording":
                    self._level_getter = payload
                    self._levels.extend([0.0] * BARS)
            if self._state == "hidden":
                root.after(HIDDEN_TICK_MS, tick)  # idle: no redraw, slow poll
                return
            self._draw(canvas)
            root.after(TICK_MS, tick)

        root.after(TICK_MS, tick)
        root.mainloop()

    def _draw(self, canvas: tk.Canvas) -> None:
        canvas.delete("all")
        self._pill(canvas)
        mid = HEIGHT / 2
        if self._otter is not None:
            canvas.create_image(WIDTH - 19, mid, image=self._otter)
        if self._state == "recording":
            if self._level_getter:
                try:
                    self._levels.append(min(1.0, self._level_getter() * LEVEL_GAIN))
                except Exception:
                    self._levels.append(0.0)
            self._spin += 1
            pulse = 1.0 + 0.35 * math.sin(self._spin * 0.18)
            r = 3.2 * pulse
            canvas.create_oval(14 - r, mid - r, 14 + r, mid + r, fill=DOT, outline="")
            bar_w, gap, x0 = 3, 3, 28
            for i, level in enumerate(self._levels):
                h = max(2.0, level * (HEIGHT - 14))
                x = x0 + i * (bar_w + gap)
                canvas.create_rectangle(
                    x, mid - h / 2, x + bar_w, mid + h / 2, fill=ACCENT, outline=""
                )
        elif self._state == "transcribing":
            self._spin += 1
            for i in range(3):
                phase = math.sin((self._spin * 0.25) - i * 0.9)
                r = 2.2 + 1.3 * (phase + 1)
                cx = WIDTH / 2 - 28 + i * 18
                canvas.create_oval(cx - r, mid - r, cx + r, mid + r, fill=ACCENT, outline="")

    @staticmethod
    def _pill(canvas: tk.Canvas) -> None:
        """Rounded-rect background — corners are color-keyed away."""
        radius = HEIGHT / 2
        canvas.create_oval(0, 0, HEIGHT, HEIGHT, fill=BG, outline="")
        canvas.create_oval(WIDTH - HEIGHT, 0, WIDTH, HEIGHT, fill=BG, outline="")
        canvas.create_rectangle(radius, 0, WIDTH - radius, HEIGHT, fill=BG, outline="")
