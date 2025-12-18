#!/usr/bin/env python3
"""
VergeGrid Control Panel - Complete Textual TUI
Full conversion of gridctl-portable.sh functionality.
"""

import asyncio
import os
import platform
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from functools import partial

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen, ScreenResultType
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label, 
    ListItem, ListView, Log, ProgressBar, Static, TextArea
)

import psutil
from vg.backend import estates, settings, tmux
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
    
    # Get uptime
    try:
        if os.name == 'posix':
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = float(f.readline().split()[0])
                days = int(uptime_seconds // 86400)
                hours = int((uptime_seconds % 86400) // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                uptime = f"{days}d {hours}h {minutes}m"
        else:
            uptime = "unknown"
    except:
        uptime = "unknown"
    
    return HostInfo(hostname, os_info, uptime)

def get_system_stats() -> Dict[str, str]:
    """Get system statistics."""
    stats = {}
    
    try:
        # CPU usage
        with open('/proc/stat', 'r') as f:
            cpu_line = f.readline().strip().split()
            user, nice, system, idle = map(int, cpu_line[1:5])
            total = user + nice + system + idle
            used = total - idle
            cpu_pct = (100 * used // total) if total > 0 else 0
            stats['cpu'] = f"{cpu_pct}%"
        
        # Memory usage
        with open('/proc/meminfo', 'r') as f:
            meminfo = {}
            for line in f:
                key, value = line.split(':')
                meminfo[key] = int(value.split()[0])
            
            total_mb = meminfo['MemTotal'] // 1024
            avail_mb = meminfo['MemAvailable'] // 1024
            used_mb = total_mb - avail_mb
            stats['memory'] = f"{used_mb}MB / {total_mb}MB"
        
        # Disk usage
        result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True)
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:
                parts = lines[1].split()
                stats['disk'] = f"{parts[2]} / {parts[1]} ({parts[4]})"
        
    except Exception:
        stats = {'cpu': 'N/A', 'memory': 'N/A', 'disk': 'N/A'}
    
    return stats

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

class LoginControlScreen(Screen):
    """Screen for login controls."""
    
    def __init__(self, app_ref) -> None:
        super().__init__()
        self.app_ref = app_ref
        self.status_log: Log
    
    def compose(self) -> ComposeResult:
        self.status_log = Log(highlight=False, classes="status-log")
        
        yield Container(
            Vertical(
                Label("Login Controls", classes="section-title"),
                Horizontal(
                    Button("Enable One", id="enable_one", variant="success"),
                    Button("Disable One", id="disable_one", variant="error"),
                    Button("Status One", id="status_one"),
                    classes="button-row"
                ),
                Horizontal(
                    Button("Enable All", id="enable_all", variant="success"),
                    Button("Disable All", id="disable_all", variant="error"),
                    Button("Status All", id="status_all"),
                    classes="button-row"
                ),
                Horizontal(
                    Button("Robust Level", id="robust_level"),
                    Button("Robust Reset", id="robust_reset"),
                    Button("Robust Message", id="robust_message"),
                    Button("Back", id="back"),
                    classes="button-row"
                ),
                Label("Status Log:", classes="log-title"),
                self.status_log,
                classes="login-content"
            )
        )
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "enable_one":
            await self.login_region_single("enable")
        elif event.button.id == "disable_one":
            await self.login_region_single("disable")
        elif event.button.id == "status_one":
            await self.login_region_single("status")
        elif event.button.id == "enable_all":
            await self.login_region_all("enable")
        elif event.button.id == "disable_all":
            await self.login_region_all("disable")
        elif event.button.id == "status_all":
            await self.login_status_all()
        elif event.button.id == "robust_level":
            await self.robust_login_level()
        elif event.button.id == "robust_reset":
            await self.robust_login_reset()
        elif event.button.id == "robust_message":
            await self.robust_login_message()
    
    async def get_running_estates(self) -> List[str]:
        """Get list of running estates."""
        config = self.app_ref.config
        transport = self.app_ref.transport
        estate_list = estates.detect_estates(config.estates, transport)
        
        running = []
        for estate in estate_list:
            if estates.running_instance(config.estates, estate, transport):
                running.append(estate)
        return running
    
    async def login_region_single(self, action: str) -> None:
        """Perform login action on single region."""
        running_estates = await self.get_running_estates()
        if not running_estates:
            self.status_log.write("No running regions available")
            return
        
        selected = await self.app.push_modal(
            EstateSelectModal(f"Select Region to {action.title()}", running_estates)
        )
        
        if selected:
            session_file = Path.home() / ".gridstl_sessions" / f"estate_{selected}.session"
            if session_file.exists():
                session = session_file.read_text().strip()
                command = f"login {action}"
                tmux.send_text(session, command, self.app_ref.transport)
                self.status_log.write(f"Sent '{command}' to {selected}")
            else:
                self.status_log.write(f"No session found for {selected}")
    
    async def login_region_all(self, action: str) -> None:
        """Perform login action on all running regions."""
        running_estates = await self.get_running_estates()
        if not running_estates:
            self.status_log.write("No running regions to update")
            return
        
        confirmed = await self.app.push_modal(
            ConfirmModal(f"{action.title()} logins on all running regions?", f"Confirm {action.title()} All")
        )
        
        if confirmed:
            for estate in running_estates:
                session_file = Path.home() / ".gridstl_sessions" / f"estate_{estate}.session"
                if session_file.exists():
                    session = session_file.read_text().strip()
                    command = f"login {action}"
                    tmux.send_text(session, command, self.app_ref.transport)
            
            self.status_log.write(f"Sent 'login {action}' to {len(running_estates)} regions")
    
    async def login_status_all(self) -> None:
        """Show login status for all running regions."""
        running_estates = await self.get_running_estates()
        if not running_estates:
            self.status_log.write("No running regions to query")
            return
        
        self.status_log.write("=== LOGIN STATUS ===")
        for estate in running_estates:
            session_file = Path.home() / ".gridstl_sessions" / f"estate_{estate}.session"
            if session_file.exists():
                session = session_file.read_text().strip()
                tmux.send_text(session, "login status", self.app_ref.transport)
                self.status_log.write(f"Queried status for {estate}")
            else:
                self.status_log.write(f"{estate}: No session")
    
    async def robust_login_level(self) -> None:
        """Set Robust login level."""
        # This would need an input modal - simplified for now
        session_file = Path.home() / ".gridstl_sessions" / "robust.session"
        if session_file.exists():
            session = session_file.read_text().strip()
            tmux.send_text(session, "login level 0", self.app_ref.transport)
            self.status_log.write("Set Robust login level to 0")
        else:
            self.status_log.write("No Robust session found")
    
    async def robust_login_reset(self) -> None:
        """Reset Robust login."""
        session_file = Path.home() / ".gridstl_sessions" / "robust.session"
        if session_file.exists():
            session = session_file.read_text().strip()
            tmux.send_text(session, "login reset", self.app_ref.transport)
            self.status_log.write("Reset Robust login")
        else:
            self.status_log.write("No Robust session found")
    
    async def robust_login_message(self) -> None:
        """Set Robust login message."""
        # This would need an input modal - simplified for now
        session_file = Path.home() / ".gridstl_sessions" / "robust.session"
        if session_file.exists():
            session = session_file.read_text().strip()
            tmux.send_text(session, "login text Welcome to VergeGrid", self.app_ref.transport)
            self.status_log.write("Set Robust login message")
        else:
            self.status_log.write("No Robust session found")

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
                    Button("Reload Config", id="reload_one", variant="warning"),
                    Button("Edit Args", id="edit_args"),
                    classes="button-row"
                ),
                Horizontal(
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
            transport = self.app_ref.transport
            
            estate_list = estates.detect_estates(config.estates, transport)
            
            self.estate_table.clear()
            for estate in estate_list:
                is_running = estates.running_instance(config.estates, estate, transport)
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
        elif event.button.id == "reload_one":
            await self.reload_one_estate()
        elif event.button.id == "edit_args":
            await self.edit_estate_args()
        elif event.button.id == "console":
            await self.attach_estate_console()
    
    async def get_estate_list(self) -> List[str]:
        """Get list of detected estates."""
        config = self.app_ref.config
        transport = self.app_ref.transport
        return estates.detect_estates(config.estates, transport)
    
    async def start_one_estate(self) -> None:
        """Start a single estate."""
        estate_list = await self.get_estate_list()
        if not estate_list:
            self.status_log.write("No estates found")
            return
        
        # Filter to only stopped estates
        stopped_estates = []
        for estate in estate_list:
            if not estates.running_instance(self.app_ref.config.estates, estate, self.app_ref.transport):
                stopped_estates.append(estate)
        
        if not stopped_estates:
            self.status_log.write("No stopped estates to start")
            return
        
        selected = await self.app.push_modal(
            EstateSelectModal("Select Estate to Start", stopped_estates)
        )
        
        if selected:
            await self.start_estate(selected)
    
    async def stop_one_estate(self) -> None:
        """Stop a single estate."""
        estate_list = await self.get_estate_list()
        if not estate_list:
            self.status_log.write("No estates found")
            return
        
        # Filter to only running estates
        running_estates = []
        for estate in estate_list:
            if estates.running_instance(self.app_ref.config.estates, estate, self.app_ref.transport):
                running_estates.append(estate)
        
        if not running_estates:
            self.status_log.write("No running estates to stop")
            return
        
        selected = await self.app.push_modal(
            EstateSelectModal("Select Estate to Stop", running_estates)
        )
        
        if selected:
            await self.stop_estate(selected)
    
    async def restart_one_estate(self) -> None:
        """Restart a single estate."""
        estate_list = await self.get_estate_list()
        if not estate_list:
            self.status_log.write("No estates found")
            return
        
        selected = await self.app.push_modal(
            EstateSelectModal("Select Estate to Restart", estate_list)
        )
        
        if selected:
            await self.stop_estate(selected)
            await asyncio.sleep(2)
            await self.start_estate(selected)
    
    async def reload_one_estate(self) -> None:
        """Reload config on a single estate."""
        estate_list = await self.get_estate_list()
        running_estates = []
        for estate in estate_list:
            if estates.running_instance(self.app_ref.config.estates, estate, self.app_ref.transport):
                running_estates.append(estate)
        
        if not running_estates:
            self.status_log.write("No running estates to reload")
            return
        
        selected = await self.app.push_modal(
            EstateSelectModal("Select Estate to Reload", running_estates)
        )
        
        if selected:
            await self.reload_estate_config(selected)
    
    async def edit_estate_args(self) -> None:
        """Edit estate arguments."""
        estate_list = await self.get_estate_list()
        if not estate_list:
            self.status_log.write("No estates found")
            return
        
        selected = await self.app.push_modal(
            EstateSelectModal("Select Estate to Edit Args", estate_list)
        )
        
        if selected:
            # Load current args
            args_file = Path(self.app_ref.config.estates) / selected / "estate.args"
            current_args = ""
            if args_file.exists():
                current_args = args_file.read_text().strip()
            
            new_args = await self.app.push_modal(
                EstateArgsModal(selected, current_args)
            )
            
            if new_args is not None:
                args_file.parent.mkdir(parents=True, exist_ok=True)
                args_file.write_text(new_args)
                self.status_log.write(f"Updated args for {selected}")
    
    async def attach_estate_console(self) -> None:
        """Attach to estate console."""
        estate_list = await self.get_estate_list()
        running_estates = []
        for estate in estate_list:
            if estates.running_instance(self.app_ref.config.estates, estate, self.app_ref.transport):
                running_estates.append(estate)
        
        if not running_estates:
            self.status_log.write("No running estates with consoles")
            return
        
        selected = await self.app.push_modal(
            EstateSelectModal("Select Estate Console", running_estates)
        )
        
        if selected:
            # Exit app and attach to tmux
            session_file = Path.home() / ".gridstl_sessions" / f"estate_{selected}.session"
            if session_file.exists():
                session = session_file.read_text().strip()
                self.app.exit()
                os.system(f"tmux attach -t '{session}'")
    
    async def start_estate(self, estate: str) -> None:
        """Start a specific estate."""
        self.status_log.write(f"Starting {estate}...")
        
        try:
            config = self.app_ref.config
            transport = self.app_ref.transport
            
            # Load extra args if they exist
            args_file = Path(config.estates) / estate / "estate.args"
            extra_args = ""
            if args_file.exists():
                extra_args = args_file.read_text().strip()
            
            # Create tmux session
            session_name = f"estate-{estate}"
            command = (f'cd "{config.base}"; '
                      f'ulimit -s 262144; '
                      f'exec dotnet OpenSim.dll --hypergrid=true '
                      f'--inidirectory="{config.estates}/{estate}" {extra_args}')
            
            session = tmux.new_window("vgctl", session_name, command, transport)
            if session:
                # Save session info
                session_file = Path.home() / ".gridstl_sessions" / f"estate_{estate}.session"
                session_file.parent.mkdir(exist_ok=True)
                session_file.write_text(session)
                
                self.status_log.write(f"Started {estate} in session {session}")
                await self.refresh_estates()
            else:
                self.status_log.write(f"Failed to start {estate}")
                
        except Exception as e:
            self.status_log.write(f"Error starting {estate}: {e}")
    
    async def stop_estate(self, estate: str) -> None:
        """Stop a specific estate."""
        self.status_log.write(f"Stopping {estate}...")
        
        try:
            # Get graceful vs force choice
            choice = await self.app.push_modal(
                ConfirmModal(f"Graceful shutdown for {estate}? (No = Force kill)", "Stop Method")
            )
            
            session_file = Path.home() / ".gridstl_sessions" / f"estate_{estate}.session"
            if session_file.exists():
                session = session_file.read_text().strip()
                
                if choice:  # Graceful
                    tmux.send_text(session, "shutdown", self.app_ref.transport)
                    self.status_log.write(f"Sent graceful shutdown to {estate}")
                else:  # Force
                    # Kill process
                    estate_dir = Path(self.app_ref.config.estates) / estate
                    subprocess.run(["pkill", "-f", str(estate_dir)], check=False)
                    session_file.unlink(missing_ok=True)
                    self.status_log.write(f"Force killed {estate}")
                
                await asyncio.sleep(1)
                await self.refresh_estates()
            else:
                self.status_log.write(f"No session file found for {estate}")
                
        except Exception as e:
            self.status_log.write(f"Error stopping {estate}: {e}")
    
    async def reload_estate_config(self, estate: str) -> None:
        """Reload config for a specific estate."""
        self.status_log.write(f"Reloading config for {estate}...")
        
        try:
            session_file = Path.home() / ".gridstl_sessions" / f"estate_{estate}.session"
            if session_file.exists():
                session = session_file.read_text().strip()
                tmux.send_text(session, "config reload", self.app_ref.transport)
                self.status_log.write(f"Sent config reload to {estate}")
            else:
                self.status_log.write(f"No session found for {estate}")
                
        except Exception as e:
            self.status_log.write(f"Error reloading config for {estate}: {e}")
    
    async def start_all_estates(self) -> None:
        """Start all detected estates."""
        confirmed = await self.app.push_modal(
            ConfirmModal("Start all stopped estates?", "Confirm Start All")
        )
        if not confirmed:
            return
        
        progress = ProgressModal("Starting All Estates")
        self.app.push_screen(progress)
        
        try:
            estate_list = await self.get_estate_list()
            stopped_estates = []
            
            for estate in estate_list:
                if not estates.running_instance(self.app_ref.config.estates, estate, self.app_ref.transport):
                    stopped_estates.append(estate)
            
            if not stopped_estates:
                progress.update_progress(1.0, "All estates already running")
                await asyncio.sleep(1)
                progress.dismiss()
                return
            
            batch_size = 3
            batch_delay = 20
            
            for i, estate in enumerate(stopped_estates):
                progress.update_progress(i / len(stopped_estates), f"Starting {estate}...")
                await self.start_estate(estate)
                
                # Batch delay every 3 estates
                if (i + 1) % batch_size == 0 and i + 1 < len(stopped_estates):
                    progress.update_progress(i / len(stopped_estates), f"Cooling down for {batch_delay}s...")
                    await asyncio.sleep(batch_delay)
                else:
                    await asyncio.sleep(2)  # Brief delay between starts
            
            progress.update_progress(1.0, "All estates started")
            await asyncio.sleep(1)
            progress.dismiss()
            await self.refresh_estates()
            
        except Exception as e:
            progress.update_progress(1.0, f"Error: {e}")
            self.status_log.write(f"Error starting estates: {e}")
    
    async def stop_all_estates(self) -> None:
        """Stop all running estates."""
        confirmed = await self.app.push_modal(
            ConfirmModal("Stop all running estates?", "Confirm Stop All")
        )
        if not confirmed:
            return
        
        progress = ProgressModal("Stopping All Estates")
        self.app.push_screen(progress)
        
        try:
            estate_list = await self.get_estate_list()
            running_estates = []
            
            for estate in estate_list:
                if estates.running_instance(self.app_ref.config.estates, estate, self.app_ref.transport):
                    running_estates.append(estate)
            
            if not running_estates:
                progress.update_progress(1.0, "No running estates to stop")
                await asyncio.sleep(1)
                progress.dismiss()
                return
            
            for i, estate in enumerate(running_estates):
                progress.update_progress(i / len(running_estates), f"Stopping {estate}...")
                
                # Send graceful shutdown
                session_file = Path.home() / ".gridstl_sessions" / f"estate_{estate}.session"
                if session_file.exists():
                    session = session_file.read_text().strip()
                    tmux.send_text(session, "shutdown", self.app_ref.transport)
                
                await asyncio.sleep(2)
            
            progress.update_progress(1.0, "All estates stopped")
            await asyncio.sleep(1)
            progress.dismiss()
            await self.refresh_estates()
            
        except Exception as e:
            progress.update_progress(1.0, f"Error: {e}")
            self.status_log.write(f"Error stopping estates: {e}")

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
        self.status_log.write("Starting Robust server...")
        
        try:
            config = self.app_ref.config
            transport = self.app_ref.transport
            
            command = (f'cd "{config.base}"; '
                      f'if [ -f Robust.dll ]; then '
                      f'dotnet Robust.dll -inifile=Robust.HG.ini; '
                      f'elif [ -f Robust.exe ]; then '
                      f'mono --desktop -O=all Robust.exe -inifile=Robust.HG.ini; '
                      f'else echo "ERROR: No Robust executable found"; fi')
            
            session = tmux.new_window("vgctl", "robust", command, transport)
            if session:
                # Save session info
                session_file = Path.home() / ".gridstl_sessions" / "robust.session"
                session_file.parent.mkdir(exist_ok=True)
                session_file.write_text(session)
                
                self.status_log.write(f"Robust started in session: {session}")
            else:
                self.status_log.write("Failed to start Robust")
                
        except Exception as e:
            self.status_log.write(f"Error starting Robust: {e}")
    
    async def stop_robust(self) -> None:
        """Stop Robust server."""
        confirmed = await self.app.push_modal(
            ConfirmModal("Graceful shutdown for Robust? (No = Force kill)", "Stop Robust")
        )
        
        self.status_log.write("Stopping Robust server...")
        
        try:
            session_file = Path.home() / ".gridstl_sessions" / "robust.session"
            if session_file.exists():
                session = session_file.read_text().strip()
                
                if confirmed:  # Graceful
                    tmux.send_text(session, "shutdown", self.app_ref.transport)
                    self.status_log.write("Sent graceful shutdown to Robust")
                else:  # Force
                    subprocess.run(["pkill", "-f", "Robust"], check=False)
                    session_file.unlink(missing_ok=True)
                    self.status_log.write("Force killed Robust")
            else:
                self.status_log.write("No Robust session found")
                
        except Exception as e:
            self.status_log.write(f"Error stopping Robust: {e}")
    
    async def restart_robust(self) -> None:
        """Restart Robust server."""
        await self.stop_robust()
        await asyncio.sleep(2)
        await self.start_robust()
    
    async def view_console(self) -> None:
        """View Robust console output."""
        session_file = Path.home() / ".gridstl_sessions" / "robust.session"
        if session_file.exists():
            session = session_file.read_text().strip()
            self.app.exit()
            os.system(f"tmux attach -t '{session}'")
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
            transport = self.app_ref.transport
            
            estate_list = estates.detect_estates(config.estates, transport)
            
            self.status_table.clear()
            for estate in estate_list:
                is_running = estates.running_instance(config.estates, estate, transport)
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
        elif event.button.id == "refresh":
            # Refresh the table
            pass
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
            "remote_host": Input(value=config.remote_host, placeholder="server.example.com"),
            "remote_user": Input(value=config.remote_user, placeholder="opensim"),
            "remote_port": Input(value=str(config.remote_port), placeholder="22"),
            "remote_key": Input(value=config.remote_key, placeholder="/path/to/ssh/key"),
        }
        
        self.status_log = Log(highlight=False, classes="status-log")
        
        yield Container(
            VerticalScroll(
                Label("Settings", classes="section-title"),
                Horizontal(
                    Button("Save", id="save", variant="primary"),
                    Button("Test Connection", id="test", variant="warning"),
                    Button("Back", id="back"),
                    classes="button-row"
                ),
                Label("Base Directory:"),
                self.inputs["base"],
                Label("Estates Directory:"),
                self.inputs["estates"],
                Label("Remote Host (optional):"),
                self.inputs["remote_host"],
                Label("Remote User (optional):"),
                self.inputs["remote_user"],
                Label("Remote Port:"),
                self.inputs["remote_port"],
                Label("SSH Key Path (optional):"),
                self.inputs["remote_key"],
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
        elif event.button.id == "test":
            await self.test_connection()
    
    async def save_settings(self) -> None:
        """Save current settings."""
        try:
            config = self.app_ref.config
            config.base = self.inputs["base"].value.strip()
            config.estates = self.inputs["estates"].value.strip()
            config.remote_host = self.inputs["remote_host"].value.strip()
            config.remote_user = self.inputs["remote_user"].value.strip()
            config.remote_port = int(self.inputs["remote_port"].value.strip() or "22")
            config.remote_key = self.inputs["remote_key"].value.strip()
            
            settings.save_settings(config)
            self.status_log.write("Settings saved successfully")
            
        except Exception as e:
            self.status_log.write(f"Error saving settings: {e}")
    
    async def test_connection(self) -> None:
        """Test remote connection if configured."""
        remote_host = self.inputs["remote_host"].value.strip()
        if not remote_host:
            self.status_log.write("No remote host configured")
            return
        
        self.status_log.write(f"Testing connection to {remote_host}...")
        
        try:
            # Simple ping test
            result = subprocess.run(
                ["ping", "-c", "1", remote_host] if os.name == 'posix' else ["ping", "-n", "1", remote_host],
                capture_output=True, text=True, timeout=5
            )
            
            if result.returncode == 0:
                self.status_log.write("Connection test successful")
            else:
                self.status_log.write("Connection test failed")
                
        except Exception as e:
            self.status_log.write(f"Connection test error: {e}")

class MainScreen(Screen):
    """Main menu screen."""
    
    def __init__(self, app_ref) -> None:
        super().__init__()
        self.app_ref = app_ref
    
    def compose(self) -> ComposeResult:
        menu_items = [
            ("robust", "Robust Controls"),
            ("estates", "Estate Controls"),
            ("login", "Login Controls"),
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
        elif event.button.id == "login":
            self.app.push_screen(LoginControlScreen(self.app_ref))
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
        
        # Initialize transport
        transport_config = TransportConfig(
            mode="ssh" if self.config.remote_host else "local",
            host=self.config.remote_host or None,
            user=self.config.remote_user or None,
            port=self.config.remote_port,
        )
        
        self.transport = detect_transport(
            self.config.base, 
            self.config.estates, 
            cfg=transport_config
        )
    
    def compose(self) -> ComposeResult:
        yield HeaderPanel()
        yield Footer()

    async def on_mount(self) -> None:  # noqa: D401
        await self.push_screen(MainScreen(self))

    async def push_modal(
        self, screen: Screen[ScreenResultType]
    ) -> ScreenResultType | Any:
        worker = self.run_worker(
            partial(self.push_screen_wait, screen),
            name="modal",
            description=f"Waiting for {screen!r}",
        )
        return await worker.wait()

    def action_quit(self) -> None:
        self.exit()

def main():
    """Entry point for the application."""
    app = VergeGridApp()
    app.run()

if __name__ == "__main__":
    main()
