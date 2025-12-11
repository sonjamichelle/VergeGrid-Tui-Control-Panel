from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from .transport import LocalTransport, Transport


@dataclass
class SystemSnapshot:
    cpu_pct: Optional[float] = None
    ram: Optional[str] = None
    disk: Optional[str] = None
    note: str = ""


def _read_cpu_pct(tr: Optional[Transport] = None) -> Optional[float]:
    tr = tr or LocalTransport()
    cp = tr.run(["grep", "^cpu ", "/proc/stat"])
    if cp.returncode != 0 or not cp.stdout:
        return None
    try:
        parts = cp.stdout.split()
        user, nice, system, idle, iowait, irq, softirq, steal = map(int, parts[1:9])
        total = user + nice + system + idle + iowait + irq + softirq + steal
        used = total - idle - iowait
        return round(100 * used / total, 2)
    except Exception:
        return None


def static_snapshot(tr: Optional[Transport] = None) -> SystemSnapshot:
    tr = tr or LocalTransport()
    snapshot = SystemSnapshot()
    snapshot.cpu_pct = _read_cpu_pct(tr=tr)

    ram_expr = (
        r'/MemTotal/ {t=$2} /MemAvailable/ {a=$2} END {u=(t-a)/1024/1024; '
        r'tt=t/1024/1024; printf "%.1fG / %.1fG", u, tt}'
    )
    ram_cp = tr.run(["awk", ram_expr, "/proc/meminfo"])
    snapshot.ram = ram_cp.stdout.strip() if ram_cp.returncode == 0 else None

    disk_cp = tr.run(["df", "-h", "/"])
    if disk_cp.returncode == 0 and disk_cp.stdout:
        try:
            snapshot.disk = disk_cp.stdout.splitlines()[1].split()[2:5]
        except Exception:
            snapshot.disk = None
    else:
        snapshot.disk = None
    return snapshot
