#!/usr/bin/env python3
"""
VergeGrid Control Panel - Working Textual TUI
Actually functional conversion with real backend implementation.
"""

import asyncio
import os
import platform
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psutil
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label, 
    ListItem, ListView, Log, ProgressBar, Static, TextArea
)

from vg.backend import settings
from vg.backend.transport import LocalTransport, detect_transport, TransportConfig

# Version info
VG_VERSION = "v0.9.0-alpha"
VG_DATE = time.strftime("%b %d %Y %H:%M")

@dataclass
class HostInfo:
    hostname: str
    os_info: str
    uptime: str

def get_host_info() -> HostInfo:
    hostname = socket.gethostname()
    os_info = platform.platform()
    
    # Get uptime using psutil
    try:
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        uptime = f"{days}d {hours}h {minutes}m"
    except:
        uptime = "unknown"
    
    return HostInfo(hostname, os_info, uptime)

def get_system_stats() -> Dict[str, str]:
    """Get system statistics using psutil."""
    stats = {}
    
    try:
        # CPU usage
        cpu_pct = psutil.cpu_percent(interval=0.1)
        stats['cpu'] = f"{cpu_pct:.1f}%"
        
        # Memory usage
        mem = psutil.virtual_memory()
        used_gb = mem.used / (1024**3)
        total_gb = mem.total / (1024**3)
        stats['memory'] = f"{used_gb:.1f}GB / {total_gb:.1f}GB ({mem.percent:.1f}%)"
        
        # Disk usage
        disk = psutil.disk_usage('/')
        used_gb = disk.used / (1024**3)
        total_gb = disk.total / (1024**3)
        pct = (disk.used / disk.total) * 100
        stats['disk'] = f"{used_gb:.1f}GB / {total_gb:.1f}GB ({pct:.1f}%)"
        
    except Exception:
        stats = {'cpu': 'N/A', 'memory': 'N/A', 'disk': 'N/A'}
    
    return stats

def detect_estates(estates_dir: str) -> List[str]:
    """Detect valid estates in the estates directory."""
    estates_path = Path(estates_dir)
    if not estates_path.exists():
        return []
    
    valid_estates = []
    for estate_dir in estates_path.iterdir():
        if not estate_dir.is_dir():
            continue
        
        # Check for OpenSim.ini
        if not (estate_dir / "OpenSim.ini").exists():
            continue
        
        # Check for Regions directory with .ini files
        regions_dir = estate_dir / "Regions"
        if not regions_dir.exists() or not regions_dir.is_dir():
            continue
        
        # Check for at least one .ini file in Regions
        ini_files = list(regions_dir.glob("*.ini"))
        if not ini_files:
            continue
        
        valid_estates.append(estate_dir.name)
    
    return sorted(valid_estates)

def is_estate_running(estates_dir: str, estate: str) -> bool:
    """Check if an estate is currently running."""
    estate_path = Path(estates_dir) / estate
    
    # Look for processes with inidirectory parameter
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and any(f"inidirectory={estate_path}" in arg for arg in cmdline):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    return False

def is_robust_running() -> bool:
    """Check if Robust is currently running."""
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and any("Robust" in arg for arg in cmdline):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

def ensure_tmux_session(session_name: str = "vgctl") -> bool:
    """Ensure tmux session exists."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True
    )
    
    if result.returncode != 0:
        # Create session
        result = subprocess.run([
            "tmux", "new-session", "-d", "-s", session_name, "-x", "200", "-y", "50"
        ], capture_output=True)
        return result.returncode == 0
    
    return True

def start_estate(base_dir: str, estates_dir: str, estate: str) -> Optional[str]:
    """Start an estate and return the tmux session name."""
    if is_estate_running(estates_dir, estate):
        return None
    
    estate_path = Path(estates_dir) / estate
    args_file = estate_path / "estate.args"
    extra_args = ""
    if args_file.exists():
        extra_args = args_file.read_text().strip()
    
    # Ensure tmux session exists
    if not ensure_tmux_session():
        return None
    
    # Create tmux window for estate
    session_name = f"estate-{estate}"
    command = (
        f'cd "{base_dir}"; '
        f'ulimit -s 262144; '
        f'exec dotnet OpenSim.dll --hypergrid=true --inidirectory="{estate_path}" {extra_args}'
    )
    
    result = subprocess.run([
        "tmux", "new-window", "-t", "vgctl", "-n", session_name, 
        "bash", "-c", command
    ], capture_output=True)
    
    if result.returncode == 0:
        full_session = f"vgctl:{session_name}"
        
        # Save session info
        session_file = Path.home() / ".gridstl_sessions" / f"estate_{estate}.session"
        session_file.parent.mkdir(exist_ok=True)
        session_file.write_text(full_session)
        
        return full_session
    
    return None

def stop_estate(estates_dir: str, estate: str, force: bool = False) -> bool:
    """Stop an estate."""
    session_file = Path.home() / ".gridstl_sessions" / f"estate_{estate}.session"
    
    if force:
        # Kill processes
        estate_path = Path(estates_dir) / estate
        killed = False
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmdline = proc.info['cmdline']
                if cmdline and any(f"inidirectory={estate_path}" in arg for arg in cmdline):
                    proc.terminate()
                    killed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Remove session file
        session_file.unlink(missing_ok=True)
        return killed
    
    # Graceful shutdown
    if session_file.exists():
        session = session_file.read_text().strip()
        result = subprocess.run([
            "tmux", "send-keys", "-t", session, "shutdown", "C-m"
        ], capture_output=True)
        return result.returncode == 0
    
    return False

def start_robust(base_dir: str) -> Optional[str]:
    """Start Robust server."""
    if is_robust_running():
        return None
    
    # Determine command based on available files
    base_path = Path(base_dir)
    if (base_path / "Robust.dll").exists():
        command = f'cd "{base_dir}"; dotnet Robust.dll -inifile=Robust.HG.ini'
    elif (base_path / "Robust.exe").exists():
        command = f'cd "{base_dir}"; mono --desktop -O=all Robust.exe -inifile=Robust.HG.ini'
    else:
        return None
    
    # Ensure tmux session exists
    if not ensure_tmux_session():
        return None
    
    # Create tmux window for Robust
    result = subprocess.run([
        "tmux", "new-window", "-t", "vgctl", "-n", "robust", 
        "bash", "-c", command
    ], capture_output=True)
    
    if result.returncode == 0:
        full_session = "vgctl:robust"
        
        # Save session info
        session_file = Path.home() / ".gridstl_sessions" / "robust.session"
        session_file.parent.mkdir(exist_ok=True)
        session_file.write_text(full_session)
        
        return full_session
    
    return None

def stop_robust(force: bool = False) -> bool:
    """Stop Robust server."""
    session_file = Path.home() / ".gridstl_sessions" / "robust.session"
    
    if force:
        # Kill Robust processes
        killed = False
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmdline = proc.info['cmdline']
                if cmdline and any("Robust" in arg for arg in cmdline):
                    proc.terminate()
                    killed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Remove session file
        session_file.unlink(missing_ok=True)
        return killed
    
    # Graceful shutdown
    if session_file.exists():
        session = session_file.read_text().strip()
        result = subprocess.run([
            "tmux", "send-keys", "-t", session, "shutdown", "C-m"
        ], capture_output=True)
        return result.returncode == 0
    
    return False

def send_command_to_session(session: str, command: str) -> bool:
    """Send a command to a tmux session."""
    result = subprocess.run([
        "tmux", "send-keys", "-t", session, command, "C-m"
    ], capture_output=True)
    return result.returncode == 0

def attach_to_session(session: str) -> None:
    """Attach to a tmux session (exits the TUI)."""
    os.system(f"tmux attach -t '{session}'")

class HeaderPanel(Static):
    """Top header with version and host info."""
    
    host_info: reactive[HostInfo] = reactive(get_host_info())
    
    def on_mount(self) -> None:
        self.set_interval(30, self.refresh_host_info)
    
    def refresh_host_info(self) -> None:
        self.host_info = get_host_info()
    
    def render(self) -> str:
        h = self.host_info
        return (f"VergeGrid Control Panel | Build: {VG_VERSION} ({VG_DATE}) | "
                f"Host: {h.hostname} | OS: {h.os_info} | Uptime: {h.uptime}")

class ConfirmModal(ModalScreen[bool]):
    """Modal for confirmation dialogs."""
    
    def __init__(self, message: str, title: str = "Confirm") -> None:
        super().__init__()
        self.message = message
        self.title = title
    
    def compose(self) -> ComposeResult:
        yield Container(
            Vertical(
                Label(self.title, classes="modal-title"),
                Label(self.message),
                Horizontal(
                    Button("Yes", id="yes", variant="primary"),
                    Button("No", id="no", variant="default"),
                    classes="button-row"
                ),
                classes="modal-content"
            ),
            classes="modal-container"
        )
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes":
            self.dismiss(True)
        else:
            self.dismiss(False)

class ProgressModal(ModalScreen[None]):
    """Modal for showing progress of operations."""
    
    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        self.log: Log
        self.progress: ProgressBar
    
    def compose(self) -> ComposeResult:
        self.log = Log(highlight=False, classes="progress-log")
        self.progress = ProgressBar(show_eta=False)
        yield Container(
            Vertical(
                Label(self.title, classes="modal-title"),
                self.progress,
                self.log,
                Button("Close", id="close"),
                classes="modal-content"
            ),
            classes="modal-container"
        )
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss()
    
    def update_progress(self, value: float, message: str = "") -> None:
        self.progress.update(progress=value)
        if message:
            self.log.write(message)

class EstateSelectModal(ModalScreen[str]):
    """Modal for selecting an estate."""
    
    def __init__(self, title: str, estates: List[str]) -> None:
        super().__init__()
        self.title = title
        self.estates = estates
        self.estate_list: ListView
    
    def compose(self) -> ComposeResult:
        items = [ListItem(Label(estate.replace("_", " "))) for estate in self.estates]
        self.estate_list = ListView(*items)
        
        yield Container(
            Vertical(
                Label(self.title, classes="modal-title"),
                self.estate_list,
                Button("Cancel", id="cancel"),
                classes="modal-content"
            ),
            classes="modal-container"
        )
    
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is not None and idx < len(self.estates):
            self.dismiss(self.estates[idx])
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss("")

class EstateArgsModal(ModalScreen[str]):
    """Modal for editing estate arguments."""
    
    def __init__(self, estate: str, current_args: str) -> None:
        super().__init__()
        self.estate = estate
        self.current_args = current_args
        self.text_area: TextArea
    
    def compose(self) -> ComposeResult:
        self.text_area = TextArea(text=self.current_args, language="text")
        yield Container(
            Vertical(
                Label(f"Edit Args for {self.estate}", classes="modal-title"),
                self.text_area,
                Horizontal(
                    Button("Save", id="save", variant="primary"),
                    Button("Cancel", id="cancel"),
                    classes="button-row"
                ),
                classes="modal-content"
            ),
            classes="modal-container"
        )
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.dismiss(self.text_area.text)
        else:
            self.dismiss("")

class LiveStatsScreen(Screen):
    """Live system statistics screen."""
    
    def __init__(self) -> None:
        super().__init__()
        self.stats_log: Log
        self.running = False
    
    def compose(self) -> ComposeResult:
        self.stats_log = Log(highlight=False, classes="stats-log")
        
        yield Container(
            Vertical(
                Label("Live System Statistics", classes="section-title"),
                Label("Press 'q' to exit", classes="subtitle"),
                Button("Back", id="back"),
                self.stats_log,
                classes="stats-content"
            )
        )
    
    async def on_mount(self) -> None:
        self.running = True
        self.update_stats_task = asyncio.create_task(self.update_stats_loop())
    
    async def on_unmount(self) -> None:
        self.running = False
        if hasattr(self, 'update_stats_task'):
            self.update_stats_task.cancel()
    
    async def update_stats_loop(self) -> None:
        """Update stats every second."""
        while self.running:
            try:
                stats = get_system_stats()
                
                self.stats_log.clear()
                self.stats_log.write("=== LIVE SYSTEM STATS ===")
                self.stats_log.write(f"CPU Usage: {stats.get('cpu', 'N/A')}")
                self.stats_log.write(f"Memory: {stats.get('memory', 'N/A')}")
                self.stats_log.write(f"Disk: {stats.get('disk', 'N/A')}")
                self.stats_log.write("")
                self.stats_log.write(f"Updated: {time.strftime('%H:%M:%S')}")
                
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.stats_log.write(f"Error updating stats: {e}")
                await asyncio.sleep(5)
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
    
    async def on_key(self, event: events.Key) -> None:
        if event.key == "q":
            self.app.pop_screen()

class EstateControlScreen(Screen):
    """Screen for managing individual estates."""
    
    def __init__(self, app_ref) -> None:
        super().__init__()
        self.app_ref = app_ref
        self.estate_table: DataTable
        self.status_log: Log
    
    def compose(self) -> ComposeResult:
        self.estate_table = DataTable(zebra_stripes=True, cursor_type="row")
        self.estate_table.add_columns("Estate", "Status")
        
        self.status_log = Log(highlight=False, classes="status-log")
        
        yield Container(
            Vertical(
                Label("Estate Controls", classes="section-title"),
                Horizontal(
                    Button("Refresh", id="refresh", variant="primary"),
                    Button("Start One", id="start_one", variant="success"),
                    Button("Stop One", id="stop_one", variant="error"),
                    Button("Restart One", id="restart_one", variant="warning"),
                    classes="button-row"
                ),
                Horizontal(
                    Button("Start All", id="start_all", variant="success"),
                    Button("Stop All", id="stop_all", variant="error"),
                    Button("Edit Args", id="edit_args"),
                    Button("Console", id="console"),
                    Button("Back", id="back"),
                    classes="button-row"
                ),
                self.estate_table,
                Label("Status Log:", classes="log-title"),
                self.status_log,
                classes="estate-content"
            )
        )
    
    async def on_mount(self) -> None:
        await self.refresh_estates()
    
    async def refresh_estates(self) -> None:
        """Refresh the estate list and status."""
        self.status_log.write("Refreshing estate list...")
        
        try:
            config = self.app_ref.config
            estate_list = detect_estates(config.estates)
            
            self.estate_table.clear()
            for estate in estate_list:
                is_running = is_estate_running(config.estates, estate)
                status = "RUNNING" if is_running else "STOPPED"
                self.estate_table.add_row(estate.replace("_", " "), status)
            
            self.status_log.write(f"Found {len(estate_list)} estates")
            
        except Exception as e:
            self.status_log.write(f"Error refreshing estates: {e}")
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "refresh":
            await self.refresh_estates()
        elif event.button.id == "start_all":
            await self.start_all_estates()
        elif event.button.id == "stop_all":
            await self.stop_all_estates()
        elif event.button.id == "start_one":
            await self.start_one_estate()
        elif event.button.id == "stop_one":
            await self.stop_one_estate()
        elif event.button.id == "restart_one":
            await self.restart_one_estate()
        elif event.button.id == "edit_args":
            await self.edit_estate_args()
        elif event.button.id == "console":
            await self.attach_estate_console()
    
    async def start_one_estate(self) -> None:
        """Start a single estate."""
        config = self.app_ref.config
        estate_list = detect_estates(config.estates)
        
        # Filter to only stopped estates
        stopped_estates = [e for e in estate_list if not is_estate_running(config.estates, e)]
        
        if not stopped_estates:
            self.status_log.write("No stopped estates to start")
            return
        
        selected = await self.app.push_screen_wait(
            EstateSelectModal("Select Estate to Start", stopped_estates)
        )
        
        if selected:
            self.status_log.write(f"Starting {selected}...")
            session = start_estate(config.base, config.estates, selected)
            if session:
                self.status_log.write(f"Started {selected} in session {session}")
                await self.refresh_estates()
            else:
                self.status_log.write(f"Failed to start {selected}")
    
    async def stop_one_estate(self) -> None:
        """Stop a single estate."""
        config = self.app_ref.config
        estate_list = detect_estates(config.estates)
        
        # Filter to only running estates
        running_estates = [e for e in estate_list if is_estate_running(config.estates, e)]
        
        if not running_estates:
            self.status_log.write("No running estates to stop")
            return
        
        selected = await self.app.push_screen_wait(
            EstateSelectModal("Select Estate to Stop", running_estates)
        )
        
        if selected:
            force = await self.app.push_screen_wait(
                ConfirmModal(f"Force kill {selected}? (No = Graceful shutdown)", "Stop Method")
            )
            
            self.status_log.write(f"Stopping {selected}...")
            success = stop_estate(config.estates, selected, force)
            if success:
                self.status_log.write(f"Stopped {selected}")
                await self.refresh_estates()
            else:
                self.status_log.write(f"Failed to stop {selected}")
    
    async def restart_one_estate(self) -> None:
        """Restart a single estate."""
        config = self.app_ref.config
        estate_list = detect_estates(config.estates)
        
        if not estate_list:
            self.status_log.write("No estates found")
            return
        
        selected = await self.app.push_screen_wait(
            EstateSelectModal("Select Estate to Restart", estate_list)
        )
        
        if selected:
            self.status_log.write(f"Restarting {selected}...")
            
            # Stop first
            if is_estate_running(config.estates, selected):
                stop_estate(config.estates, selected, False)
                await asyncio.sleep(2)
            
            # Start
            session = start_estate(config.base, config.estates, selected)
            if session:
                self.status_log.write(f"Restarted {selected}")
                await self.refresh_estates()
            else:
                self.status_log.write(f"Failed to restart {selected}")
    
    async def edit_estate_args(self) -> None:
        """Edit estate arguments."""
        config = self.app_ref.config
        estate_list = detect_estates(config.estates)
        
        if not estate_list:
            self.status_log.write("No estates found")
            return
        
        selected = await self.app.push_screen_wait(
            EstateSelectModal("Select Estate to Edit Args", estate_list)
        )
        
        if selected:
            # Load current args
            args_file = Path(config.estates) / selected / "estate.args"
            current_args = ""
            if args_file.exists():
                current_args = args_file.read_text().strip()
            
            new_args = await self.app.push_screen_wait(
                EstateArgsModal(selected, current_args)
            )
            
            if new_args is not None:
                args_file.parent.mkdir(parents=True, exist_ok=True)
                args_file.write_text(new_args)
                self.status_log.write(f"Updated args for {selected}")
    
    async def attach_estate_console(self) -> None:
        """Attach to estate console."""
        config = self.app_ref.config
        estate_list = detect_estates(config.estates)
        running_estates = [e for e in estate_list if is_estate_running(config.estates, e)]
        
        if not running_estates:
            self.status_log.write("No running estates with consoles")
            return
        
        selected = await self.app.push_screen_wait(
            EstateSelectModal("Select Estate Console", running_estates)
        )
        
        if selected:
            session_file = Path.home() / ".gridstl_sessions" / f"estate_{selected}.session"
            if session_file.exists():
                session = session_file.read_text().strip()
                self.app.exit()
                attach_to_session(session)
            else:
                self.status_log.write(f"No session found for {selected}")
    
    async def start_all_estates(self) -> None:
        """Start all stopped estates."""
        confirmed = await self.app.push_screen_wait(
            ConfirmModal("Start all stopped estates?", "Confirm Start All")
        )
        if not confirmed:
            return
        
        config = self.app_ref.config
        estate_list = detect_estates(config.estates)
        stopped_estates = [e for e in estate_list if not is_estate_running(config.estates, e)]
        
        if not stopped_estates:
            self.status_log.write("All estates already running")
            return
        
        progress = ProgressModal("Starting All Estates")
        self.app.push_screen(progress)
        
        batch_size = 3
        batch_delay = 20
        
        try:
            for i, estate in enumerate(stopped_estates):
                progress.update_progress(i / len(stopped_estates), f"Starting {estate}...")
                
                session = start_estate(config.base, config.estates, estate)
                if session:
                    progress.update_progress(i / len(stopped_estates), f"Started {estate}")
                else:
                    progress.update_progress(i / len(stopped_estates), f"Failed to start {estate}")
                
                # Batch delay every 3 estates
                if (i + 1) % batch_size == 0 and i + 1 < len(stopped_estates):
                    progress.update_progress(i / len(stopped_estates), f"Cooling down for {batch_delay}s...")
                    await asyncio.sleep(batch_delay)
                else:
                    await asyncio.sleep(2)
            
            progress.update_progress(1.0, "All estates started")
            await asyncio.sleep(1)
            progress.dismiss()
            await self.refresh_estates()
            
        except Exception as e:
            progress.update_progress(1.0, f"Error: {e}")
    
    async def stop_all_estates(self) -> None:
        """Stop all running estates."""
        confirmed = await self.app.push_screen_wait(
            ConfirmModal("Stop all running estates?", "Confirm Stop All")
        )
        if not confirmed:
            return
        
        config = self.app_ref.config
        estate_list = detect_estates(config.estates)
        running_estates = [e for e in estate_list if is_estate_running(config.estates, e)]
        
        if not running_estates:
            self.status_log.write("No running estates to stop")
            return
        
        progress = ProgressModal("Stopping All Estates")
        self.app.push_screen(progress)
        
        try:
            for i, estate in enumerate(running_estates):
                progress.update_progress(i / len(running_estates), f"Stopping {estate}...")
                
                success = stop_estate(config.estates, estate, False)  # Graceful
                if success:
                    progress.update_progress(i / len(running_estates), f"Stopped {estate}")
                else:
                    progress.update_progress(i / len(running_estates), f"Failed to stop {estate}")
                
                await asyncio.sleep(2)
            
            progress.update_progress(1.0, "All estates stopped")
            await asyncio.sleep(1)
            progress.dismiss()
            await self.refresh_estates()
            
        except Exception as e:
            progress.update_progress(1.0, f"Error: {e}")

class RobustControlScreen(Screen):
    """Screen for Robust server controls."""
    
    def __init__(self, app_ref) -> None:
        super().__init__()
        self.app_ref = app_ref
        self.status_log: Log
    
    def compose(self) -> ComposeResult:
        self.status_log = Log(highlight=False, classes="status-log")
        
        yield Container(
            Vertical(
                Label("Robust Controls", classes="section-title"),
                Horizontal(
                    Button("Start Robust", id="start", variant="success"),
                    Button("Stop Robust", id="stop", variant="error"),
                    Button("Restart Robust", id="restart", variant="warning"),
                    Button("Console", id="console"),
                    Button("Back", id="back"),
                    classes="button-row"
                ),
                Label("Status Log:", classes="log-title"),
                self.status_log,
                classes="robust-content"
            )
        )
    
    async def on_mount(self) -> None:
        # Show current status
        if is_robust_running():
            self.status_log.write("Robust is currently RUNNING")
        else:
            self.status_log.write("Robust is currently STOPPED")
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "start":
            await self.start_robust()
        elif event.button.id == "stop":
            await self.stop_robust()
        elif event.button.id == "restart":
            await self.restart_robust()
        elif event.button.id == "console":
            await self.view_console()
    
    async def start_robust(self) -> None:
        """Start Robust server."""
        if is_robust_running():
            self.status_log.write("Robust is already running")
            return
        
        self.status_log.write("Starting Robust server...")
        
        config = self.app_ref.config
        session = start_robust(config.base)
        if session:
            self.status_log.write(f"Robust started in session: {session}")
        else:
            self.status_log.write("Failed to start Robust (check if executable exists)")
    
    async def stop_robust(self) -> None:
        """Stop Robust server."""
        if not is_robust_running():
            self.status_log.write("Robust is not running")
            return
        
        force = await self.app.push_screen_wait(
            ConfirmModal("Force kill Robust? (No = Graceful shutdown)", "Stop Robust")
        )
        
        self.status_log.write("Stopping Robust server...")
        
        success = stop_robust(force)
        if success:
            self.status_log.write("Robust stopped")
        else:
            self.status_log.write("Failed to stop Robust")
    
    async def restart_robust(self) -> None:
        """Restart Robust server."""
        self.status_log.write("Restarting Robust server...")
        
        # Stop first
        if is_robust_running():
            stop_robust(False)
            await asyncio.sleep(2)
        
        # Start
        config = self.app_ref.config
        session = start_robust(config.base)
        if session:
            self.status_log.write("Robust restarted successfully")
        else:
            self.status_log.write("Failed to restart Robust")
    
    async def view_console(self) -> None:
        """View Robust console output."""
        session_file = Path.home() / ".gridstl_sessions" / "robust.session"
        if session_file.exists():
            session = session_file.read_text().strip()
            self.app.exit()
            attach_to_session(session)
        else:
            self.status_log.write("No Robust session found")

class RegionStatusScreen(Screen):
    """Screen for viewing region status."""
    
    def __init__(self, app_ref) -> None:
        super().__init__()
        self.app_ref = app_ref
        self.status_table: DataTable
    
    def compose(self) -> ComposeResult:
        self.status_table = DataTable(zebra_stripes=True)
        self.status_table.add_columns("Estate", "Status")
        
        yield Container(
            Vertical(
                Label("Region Status", classes="section-title"),
                Horizontal(
                    Button("Refresh", id="refresh", variant="primary"),
                    Button("Back", id="back"),
                    classes="button-row"
                ),
                self.status_table,
                classes="status-content"
            )
        )
    
    async def on_mount(self) -> None:
        await self.refresh_status()
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "refresh":
            await self.refresh_status()
    
    async def refresh_status(self) -> None:
        """Refresh region status."""
        try:
            config = self.app_ref.config
            estate_list = detect_estates(config.estates)
            
            self.status_table.clear()
            for estate in estate_list:
                is_running = is_estate_running(config.estates, estate)
                status = "RUNNING" if is_running else "STOPPED"
                self.status_table.add_row(estate.replace("_", " "), status)
                
        except Exception as e:
            self.status_table.clear()
            self.status_table.add_row("Error", str(e))

class SystemInfoScreen(Screen):
    """Screen for system information."""
    
    def compose(self) -> ComposeResult:
        info_table = DataTable(zebra_stripes=True)
        info_table.add_columns("Property", "Value")
        
        # Add system information
        host_info = get_host_info()
        stats = get_system_stats()
        
        info_table.add_row("Hostname", host_info.hostname)
        info_table.add_row("OS", host_info.os_info)
        info_table.add_row("Uptime", host_info.uptime)
        info_table.add_row("Python Version", platform.python_version())
        info_table.add_row("CPU Usage", stats.get('cpu', 'N/A'))
        info_table.add_row("Memory Usage", stats.get('memory', 'N/A'))
        info_table.add_row("Disk Usage", stats.get('disk', 'N/A'))
        
        yield Container(
            Vertical(
                Label("System Information", classes="section-title"),
                Horizontal(
                    Button("Refresh", id="refresh", variant="primary"),
                    Button("Live Stats", id="live_stats", variant="warning"),
                    Button("Back", id="back"),
                    classes="button-row"
                ),
                info_table,
                classes="sysinfo-content"
            )
        )
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "live_stats":
            self.app.push_screen(LiveStatsScreen())

class SettingsScreen(Screen):
    """Screen for application settings."""
    
    def __init__(self, app_ref) -> None:
        super().__init__()
        self.app_ref = app_ref
        self.inputs: Dict[str, Input] = {}
        self.status_log: Log
    
    def compose(self) -> ComposeResult:
        config = self.app_ref.config
        
        self.inputs = {
            "base": Input(value=config.base, placeholder="/home/opensim/opensim/bin"),
            "estates": Input(value=config.estates, placeholder="/home/opensim/opensim/bin/Estates"),
        }
        
        self.status_log = Log(highlight=False, classes="status-log")
        
        yield Container(
            VerticalScroll(
                Label("Settings", classes="section-title"),
                Horizontal(
                    Button("Save", id="save", variant="primary"),
                    Button("Back", id="back"),
                    classes="button-row"
                ),
                Label("Base Directory:"),
                self.inputs["base"],
                Label("Estates Directory:"),
                self.inputs["estates"],
                Label("Status Log:", classes="log-title"),
                self.status_log,
                classes="settings-content"
            )
        )
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "save":
            await self.save_settings()
    
    async def save_settings(self) -> None:
        """Save current settings."""
        try:
            config = self.app_ref.config
            config.base = self.inputs["base"].value.strip()
            config.estates = self.inputs["estates"].value.strip()
            
            settings.save_settings(config)
            self.status_log.write("Settings saved successfully")
            
        except Exception as e:
            self.status_log.write(f"Error saving settings: {e}")

class MainScreen(Screen):
    """Main menu screen."""
    
    def __init__(self, app_ref) -> None:
        super().__init__()
        self.app_ref = app_ref
    
    def compose(self) -> ComposeResult:
        menu_items = [
            ("robust", "Robust Controls"),
            ("estates", "Estate Controls"),
            ("status", "Region Status"),
            ("sysinfo", "System Info"),
            ("settings", "Settings"),
            ("quit", "Quit")
        ]
        
        buttons = [Button(label, id=key, classes="menu-button") for key, label in menu_items]
        
        yield Container(
            Vertical(
                Label("VergeGrid Control Panel", classes="main-title"),
                Label("Select an option:", classes="subtitle"),
                *buttons,
                classes="main-menu"
            )
        )
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit":
            self.app.exit()
        elif event.button.id == "robust":
            self.app.push_screen(RobustControlScreen(self.app_ref))
        elif event.button.id == "estates":
            self.app.push_screen(EstateControlScreen(self.app_ref))
        elif event.button.id == "status":
            self.app.push_screen(RegionStatusScreen(self.app_ref))
        elif event.button.id == "sysinfo":
            self.app.push_screen(SystemInfoScreen())
        elif event.button.id == "settings":
            self.app.push_screen(SettingsScreen(self.app_ref))

class VergeGridApp(App):
    """Main Textual application."""
    
    CSS = """
    .main-title {
        text-align: center;
        text-style: bold;
        margin: 1;
    }
    
    .subtitle {
        text-align: center;
        margin: 1;
    }
    
    .section-title {
        text-style: bold;
        margin: 1 0;
    }
    
    .menu-button {
        width: 100%;
        margin: 0 2;
    }
    
    .button-row {
        height: auto;
        margin: 1 0;
    }
    
    .status-log {
        height: 10;
        border: solid $accent;
        margin: 1 0;
    }
    
    .modal-container {
        align: center middle;
    }
    
    .modal-content {
        width: 60;
        height: auto;
        background: $surface;
        border: solid $accent;
        padding: 1;
    }
    
    .modal-title {
        text-style: bold;
        text-align: center;
        margin: 0 0 1 0;
    }
    
    .progress-log {
        height: 8;
        border: solid $accent;
    }
    
    .stats-log {
        height: 15;
        border: solid $accent;
    }
    """
    
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
    ]
    
    def __init__(self) -> None:
        super().__init__()
        self.config = settings.load_settings()
    
    def compose(self) -> ComposeResult:
        yield HeaderPanel()
        yield MainScreen(self)
        yield Footer()
    
    def action_quit(self) -> None:
        self.exit()

def main():
    """Entry point for the application."""
    app = VergeGridApp()
    app.run()

if __name__ == "__main__":
    main()