from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .transport import LocalTransport, Transport


def _is_valid_estate_local(path: Path) -> bool:
    if not path.is_dir():
        return False
    if not (path / "OpenSim.ini").exists():
        return False
    regions = list((path / "Regions").glob("*.ini"))
    return len(regions) > 0


def detect_estates(estates_root: str, tr: Optional[Transport] = None) -> List[str]:
    tr = tr or LocalTransport()
    if isinstance(tr, LocalTransport):
        root = Path(estates_root)
        if not root.exists():
            return []
        names = []
        for child in root.iterdir():
            if _is_valid_estate_local(child):
                names.append(child.name)
        return sorted(names)

    # Remote: use find and test to validate estate dirs.
    names: List[str] = []
    cp = tr.run(["find", estates_root, "-maxdepth", "1", "-type", "d"])
    if cp.returncode != 0 or not cp.stdout:
        return []
    for line in cp.stdout.splitlines():
        line = line.strip()
        if not line or line == estates_root.rstrip("/"):
            continue
        estate_path = line
        # validate presence of OpenSim.ini and Regions/*.ini
        ini_cp = tr.run(["test", "-f", f"{estate_path}/OpenSim.ini"], capture=False)
        if ini_cp.returncode != 0:
            continue
        regions_cp = tr.run(
            ["find", f"{estate_path}/Regions", "-maxdepth", "1", "-name", "*.ini", "-type", "f"]
        )
        if regions_cp.returncode != 0 or not regions_cp.stdout:
            continue
        names.append(Path(estate_path).name)
    return sorted(names)


def running_instance(estates_root: str, estate: str, tr: Optional[Transport] = None) -> bool:
    dir_path = Path(estates_root) / estate
    tr = tr or LocalTransport()
    cp = tr.run(["pgrep", "-f", f"inidirectory={dir_path}"], capture=False)
    return cp.returncode == 0


def start_instance(
    base: str,
    estates_root: str,
    estate: str,
    extra_args: str = "",
    tr: Optional[Transport] = None,
) -> bool:
    # TODO: wire to tmux backend with dotnet/mono command via transport.
    _ = (base, estates_root, estate, extra_args)
    _ = tr
    return False


def stop_instance(estates_root: str, estate: str, mode: str = "graceful", tr: Optional[Transport] = None) -> bool:
    # TODO: send shutdown or pkill similar to shell script via transport.
    _ = (estates_root, estate, mode, tr)
    return False


def load_estate_args(estates_root: str, estate: str, tr: Optional[Transport] = None) -> str:
    tr = tr or LocalTransport()
    path = Path(estates_root) / estate / "estate.args"
    if isinstance(tr, LocalTransport):
        if not path.exists():
            return ""
        return path.read_text()
    cp = tr.run(["cat", str(path)])
    if cp.returncode != 0:
        return ""
    return cp.stdout or ""


def save_estate_args(estates_root: str, estate: str, content: str, tr: Optional[Transport] = None) -> None:
    tr = tr or LocalTransport()
    path = Path(estates_root) / estate / "estate.args"
    if isinstance(tr, LocalTransport):
        path.write_text(content)
    else:
        # TODO: implement remote write (e.g., via sftp or ssh with stdin).
        pass
