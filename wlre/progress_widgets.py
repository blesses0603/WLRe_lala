"""Lightweight, theme-independent progress presentation shared by startup views."""

ACCENT = '#56c8e9'
TRACK = '#293c50'


class CyanProgress:
    """Small canvas bar: identical colors under Windows native ttk themes.

    One 25 fps timer only while the stage has no known total. No image assets,
    native-theme overrides, or artificial whole-launch percentages are needed.
    """
    def __init__(self, parent, tk):
        self.canvas = tk.Canvas(parent, height=8, bg=TRACK,
                                highlightthickness=0, borderwidth=0)
        self.canvas.pack(fill='x', pady=(8, 0))
        self._fill = self.canvas.create_rectangle(0, 0, 0, 8,
                                                 fill=ACCENT, outline='')
        self._counts = None
        self._offset = 0
        self._timer = None
        self._running = False
        self._finished = False
        self._destroyed = False
        self.canvas.bind('<Configure>', lambda event: self._draw())
        self.canvas.bind('<Destroy>', self._on_destroy, add='+')
        self.set_counts(None)

    def _draw(self):
        if self._destroyed:
            return
        width = max(1, self.canvas.winfo_width())
        if self._counts is None:
            span = max(24, width * .18)
            left = (width - span) * (1 - abs(self._offset / 25 - 1))
            right = left + span
        else:
            done, total = self._counts
            left, right = 0, width * done / total
        self.canvas.coords(self._fill, left, 0, right, 8)

    def _tick(self):
        self._timer = None
        if self._running:
            self._offset = (self._offset + 1) % 50
            self._draw()
            self._timer = self.canvas.after(40, self._tick)

    def set_counts(self, counts):
        if self._finished or self._destroyed:
            return
        self._counts = counts
        if counts is not None:
            self.stop()
        elif not self._running:
            self._running = True
            self._tick()
        self._draw()

    def stop(self):
        self._running = False
        if self._timer is not None:
            self.canvas.after_cancel(self._timer)
            self._timer = None

    def finish(self):
        """Latch the terminal state; late progress cannot restart animation."""
        self._finished = True
        self.stop()

    def reset(self):
        """Only a new explicit check may leave the terminal state."""
        if self._destroyed:
            return
        self._finished = False
        self.set_counts(None)

    def _on_destroy(self, event=None):
        self._destroyed = True
        self.finish()
