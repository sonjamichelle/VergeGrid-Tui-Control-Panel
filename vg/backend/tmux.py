from __future__ import annotations

from typing import Optional

from .transport import LocalTransport, Transport


def ensure_tmux(tr: Optional[Transport] = None) -> bool:
    """Return True if tmux is available."""
    tr = tr or LocalTransport()
    cp = tr.run(["tmux", "-V"])
    return cp.returncode == 0


def new_window(session: str, name: str, command: str, tr: Optional[Transport] = None) -> Optional[str]:
    """Create a tmux window and return its target (session:name)."""
    tr = tr or LocalTransport()
    if not ensure_tmux(tr):
        return None
    # Ensure session exists
    tr.run(["tmux", "new-session", "-d", "-s", session, "-x", "200", "-y", "50"])
    cp = tr.run(["tmux", "new-window", "-t", session, "-n", name, command])
    if cp.returncode != 0:
        return None
    return f"{session}:{name}"


def send_text(target: str, text: str, tr: Optional[Transport] = None) -> bool:
    tr = tr or LocalTransport()
    if not ensure_tmux(tr):
        return False
    cp = tr.run(["tmux", "send-keys", "-t", target, text, "C-m"])
    return cp.returncode == 0


def capture_output(target: str, lines: int = 200, tr: Optional[Transport] = None) -> str:
    tr = tr or LocalTransport()
    if not ensure_tmux(tr):
        return ""
    cp = tr.run(["tmux", "capture-pane", "-pt", target, "-S", f"-{lines}"])
    if cp.returncode != 0:
        return ""
    return cp.stdout or ""
