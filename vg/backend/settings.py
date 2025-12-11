from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SETTINGS_FILE = Path.home() / ".vergegrid_settings"


@dataclass
class Settings:
    """User settings for BASE/ESTATES paths and optional SSH config."""

    base: str
    estates: str
    remote_host: str = ""
    remote_user: str = ""
    remote_port: int = 22
    remote_key: str = ""
    remote_password: str = ""
    path: Path = SETTINGS_FILE


def _parse_line(line: str) -> Optional[tuple[str, str]]:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "=" not in line:
        return None
    key, val = line.split("=", 1)
    key = key.strip()
    val = val.strip().strip('"').strip("'")
    return key, val


def load_settings() -> Settings:
    default_base = os.environ.get("VG_BASE", "/home/opensim/opensim/bin")
    default_estates = os.environ.get("VG_ESTATES", f"{default_base}/Estates")
    default_remote_host = os.environ.get("VG_REMOTE_HOST", "")
    default_remote_user = os.environ.get("VG_REMOTE_USER", "")
    default_remote_port = int(os.environ.get("VG_REMOTE_PORT", "22"))
    default_remote_key = os.environ.get("VG_REMOTE_KEY", "")
    default_remote_password = os.environ.get("VG_REMOTE_PASSWORD", "")

    base = default_base
    estates = default_estates
    remote_host = default_remote_host
    remote_user = default_remote_user
    remote_port = default_remote_port
    remote_key = default_remote_key
    remote_password = default_remote_password

    if SETTINGS_FILE.exists():
        for line in SETTINGS_FILE.read_text().splitlines():
            parsed = _parse_line(line)
            if not parsed:
                continue
            key, val = parsed
            if key == "VG_BASE":
                base = val
            elif key == "VG_ESTATES":
                estates = val
            elif key == "VG_REMOTE_HOST":
                remote_host = val
            elif key == "VG_REMOTE_USER":
                remote_user = val
            elif key == "VG_REMOTE_PORT":
                try:
                    remote_port = int(val)
                except ValueError:
                    remote_port = default_remote_port
            elif key == "VG_REMOTE_KEY":
                remote_key = val
            elif key == "VG_REMOTE_PASSWORD":
                remote_password = val

    return Settings(
        base=base,
        estates=estates,
        remote_host=remote_host,
        remote_user=remote_user,
        remote_port=remote_port,
        remote_key=remote_key,
        remote_password=remote_password,
        path=SETTINGS_FILE,
    )


def save_settings(settings: Settings) -> None:
    content = (
        f'VG_BASE="{settings.base}"\n'
        f'VG_ESTATES="{settings.estates}"\n'
        f'VG_REMOTE_HOST="{settings.remote_host}"\n'
        f'VG_REMOTE_USER="{settings.remote_user}"\n'
        f'VG_REMOTE_PORT="{settings.remote_port}"\n'
        f'VG_REMOTE_KEY="{settings.remote_key}"\n'
        f'VG_REMOTE_PASSWORD="{settings.remote_password}"\n'
    )
    SETTINGS_FILE.write_text(content)
