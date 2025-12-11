from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class TransportConfig:
    mode: str  # "local" or "ssh"
    host: Optional[str] = None
    user: Optional[str] = None
    port: int = 22
    identity_file: Optional[str] = None
    password: Optional[str] = None


class Transport:
    """Abstract transport for running commands and basic file ops."""

    cfg: TransportConfig

    def run(self, command: List[str], capture: bool = True) -> subprocess.CompletedProcess:
        raise NotImplementedError

    def exists(self, path: str) -> bool:
        raise NotImplementedError


class LocalTransport(Transport):
    def __init__(self) -> None:
        self.cfg = TransportConfig(mode="local")

    def run(self, command: List[str], capture: bool = True) -> subprocess.CompletedProcess:
        kwargs = {"check": False}
        if capture:
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.PIPE
            kwargs["text"] = True
        return subprocess.run(command, **kwargs)  # type: ignore[arg-type]

    def exists(self, path: str) -> bool:
        return Path(path).exists()


class SSHTransport(Transport):
    def __init__(
        self,
        host: str,
        user: Optional[str] = None,
        port: int = 22,
        identity_file: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.cfg = TransportConfig(
            mode="ssh",
            host=host,
            user=user,
            port=port,
            identity_file=identity_file,
            password=password,
        )

    def _ssh_prefix(self) -> List[str]:
        user_host = f"{self.cfg.user + '@' if self.cfg.user else ''}{self.cfg.host}"
        prefix = ["ssh", "-p", str(self.cfg.port)]
        if self.cfg.identity_file:
            prefix += ["-i", self.cfg.identity_file]
        prefix.append(user_host)
        return prefix

    def run(self, command: List[str], capture: bool = True) -> subprocess.CompletedProcess:
        ssh_cmd = self._ssh_prefix() + command
        kwargs = {"check": False}
        if capture:
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.PIPE
            kwargs["text"] = True
        return subprocess.run(ssh_cmd, **kwargs)  # type: ignore[arg-type]

    def exists(self, path: str) -> bool:
        cp = self.run(["test", "-e", path])
        return cp.returncode == 0


class UnknownTransport(Transport):
    """Fallback when we can't determine or connect."""

    def __init__(self) -> None:
        self.cfg = TransportConfig(mode="unknown")

    def run(self, command: List[str], capture: bool = True) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, returncode=1, stdout="", stderr="unknown transport")

    def exists(self, path: str) -> bool:
        return False


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"1", "true", "yes", "on"}


def _probe_ssh(host: str, user: Optional[str], port: int, identity: Optional[str]) -> bool:
    """Lightweight probe to see if ssh is reachable without prompting."""
    if not host:
        return False
    user_host = f"{user + '@' if user else ''}{host}"
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=5",
        "-p",
        str(port),
    ]
    if identity:
        cmd += ["-i", identity]
    cmd += [user_host, "true"]
    cp = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return cp.returncode == 0


def detect_transport(base: str, estates: str, cfg: TransportConfig | None = None) -> Transport:
    """Decide whether to use local or SSH, with env overrides."""
    if _env_bool("VG_FORCE_SSH"):
        host = os.environ.get("VG_REMOTE_HOST", "")
        user = os.environ.get("VG_REMOTE_USER")
        port = int(os.environ.get("VG_REMOTE_PORT", "22"))
        ident = os.environ.get("VG_REMOTE_KEY")
        pwd = os.environ.get("VG_REMOTE_PASSWORD")
        if host and (ident or pwd):
            if ident and _probe_ssh(host, user, port, ident):
                return SSHTransport(host=host, user=user, port=port, identity_file=ident, password=pwd)
        return UnknownTransport()

    if _env_bool("VG_FORCE_LOCAL"):
        return LocalTransport()

    # Heuristic: if BASE and ESTATES exist locally and tmux is present, stay local.
    tmux_available = shutil.which("tmux") is not None
    base_exists = Path(base).exists()
    estates_exists = Path(estates).exists()
    if tmux_available and base_exists and estates_exists:
        return LocalTransport()

    # Fallback to SSH using env vars or provided cfg.
    host = cfg.host if cfg else os.environ.get("VG_REMOTE_HOST", "")
    user = cfg.user if cfg else os.environ.get("VG_REMOTE_USER")
    port = cfg.port if cfg else int(os.environ.get("VG_REMOTE_PORT", "22"))
    ident = cfg.identity_file if cfg else os.environ.get("VG_REMOTE_KEY")
    pwd = cfg.password if cfg else os.environ.get("VG_REMOTE_PASSWORD")
    if host and (ident or pwd):
        # If credentials are provided, prefer ssh mode; actual command exec will surface errors.
        return SSHTransport(host=host, user=user, port=port, identity_file=ident, password=pwd)
    return UnknownTransport()
