from __future__ import annotations

from typing import Dict, List, Optional

from . import tmux
from .transport import LocalTransport, Transport


def login_status(target: str, tr: Optional[Transport] = None) -> str:
    """Capture a login status line from a tmux target."""
    tr = tr or LocalTransport()
    tmux.send_text(target, "login status", tr=tr)
    output = tmux.capture_output(target, lines=200, tr=tr)
    status = "UNKNOWN"
    for line in output.splitlines():
        lower = line.lower()
        if "logins" in lower and "enable" in lower:
            status = "ENABLED"
        if "logins" in lower and "disable" in lower:
            status = "DISABLED"
    return status


def login_status_all(targets: List[str], tr: Optional[Transport] = None) -> Dict[str, str]:
    tr = tr or LocalTransport()
    return {t: login_status(t, tr=tr) for t in targets}


def login_toggle(target: str, enable: bool, tr: Optional[Transport] = None) -> bool:
    tr = tr or LocalTransport()
    cmd = "login enable" if enable else "login disable"
    return tmux.send_text(target, cmd, tr=tr)


def login_set_level(target: str, level: str, tr: Optional[Transport] = None) -> bool:
    tr = tr or LocalTransport()
    return tmux.send_text(target, f"login level {level}", tr=tr)


def login_reset(target: str, tr: Optional[Transport] = None) -> bool:
    tr = tr or LocalTransport()
    return tmux.send_text(target, "login reset", tr=tr)


def login_set_text(target: str, text: str, tr: Optional[Transport] = None) -> bool:
    tr = tr or LocalTransport()
    return tmux.send_text(target, f"login text {text}", tr=tr)
