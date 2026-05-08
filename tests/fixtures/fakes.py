from __future__ import annotations


class FakeClock:
    """Deterministic sleep replacement that advances a virtual clock and
    optionally mutates the filesystem at scheduled tick counts."""

    def __init__(self, on_tick=None):
        self.elapsed = 0.0
        self.calls = 0
        self._on_tick = on_tick or (lambda n: None)

    def __call__(self, secs: float) -> None:
        self.calls += 1
        self.elapsed += secs
        self._on_tick(self.calls)


class FakeTmux:
    """Records every (pane, keys) tuple sent."""

    def __init__(self, raise_on_call: bool = False):
        self.sent: list[tuple[str, str]] = []
        self.raise_on_call = raise_on_call

    def __call__(self, pane: str, keys: str) -> None:
        if self.raise_on_call:
            raise RuntimeError("pane gone")
        self.sent.append((pane, keys))
