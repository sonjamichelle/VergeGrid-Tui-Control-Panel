#!/usr/bin/env python3
"""
VergeGrid Control Panel - Textual TUI
Converts gridctl-portable.sh functionality to a modern Textual-based interface.
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

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label, 
    ListItem, ListView, Log, ProgressBar, Static, TextArea
)

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

class EstateControlScreen(Screen):
    """Screen for managing individual estates."""
    
    def __init__(self, app_ref) -> None:
        super().__init__()
        self.app_ref = app_ref
        self.estate_table: DataTable
        self.status_log: Log
    
    def compose(self) -> ComposeResult:
        self.estate_table = DataTable(zebra_stripes=True)
        self.estate_table.add_columns("Estate", "Status", "Actions")
        
        self.status_log = Log(highlight=False, classes="status-log")
        
        yield Container(
            Vertical(
                Label("Estate Controls", classes="section-title"),
                Horizontal(
                    Button("Refresh", id="refresh", variant="primary"),
                    Button("Start All", id="start_all", variant="success"),
                    Button("Stop All", id="stop_all", variant="error"),
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
                self.estate_table.add_row(estate, status, "Start|Stop|Reload")
            
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
    
    async def start_all_estates(self) -> None:
        """Start all detected estates."""
        confirmed = await self.app.push_screen_wait(
            ConfirmModal("Start all estates?", "Confirm Start All")
        )
        if not confirmed:
            return
        
        progress = ProgressModal("Starting All Estates")
        self.app.push_screen(progress)
        
        try:
            config = self.app_ref.config
            transport = self.app_ref.transport
            estate_list = estates.detect_estates(config.estates, transport)
            
            for i, estate in enumerate(estate_list):
                progress.update_progress(i / len(estate_list), f"Starting {estate}...")
                
                if not estates.running_instance(config.estates, estate, transport):
                    # Start estate using tmux backend
                    session_name = f"estate-{estate}"
                    command = (f'cd "{config.base}"; '
                             f'dotnet OpenSim.dll --hypergrid=true '
                             f'--inidirectory="{config.estates}/{estate}"')
                    
                    tmux.new_window("vgctl", session_name, command, transport)
                    self.status_log.write(f"Started {estate}")
                else:
                    self.status_log.write(f"{estate} already running")
                
                await asyncio.sleep(0.5)  # Brief delay between starts
            
            progress.update_progress(1.0, "All estates started")
            await asyncio.sleep(1)
            progress.dismiss()
            await self.refresh_estates()
            
        except Exception as e:
            progress.update_progress(1.0, f"Error: {e}")
            self.status_log.write(f"Error starting estates: {e}")
    
    async def stop_all_estates(self) -> None:
        """Stop all running estates."""
        confirmed = await self.app.push_screen_wait(
            ConfirmModal("Stop all running estates?", "Confirm Stop All")
        )
        if not confirmed:
            return
        
        self.status_log.write("Stopping all estates...")
        # Implementation would send shutdown commands to tmux sessions
        await self.refresh_estates()

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
                    Button("View Console", id="console"),
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
                self.status_log.write(f"Robust started in session: {session}")
            else:
                self.status_log.write("Failed to start Robust")
                
        except Exception as e:
            self.status_log.write(f"Error starting Robust: {e}")
    
    async def stop_robust(self) -> None:
        """Stop Robust server."""
        confirmed = await self.app.push_screen_wait(
            ConfirmModal("Stop Robust server?", "Confirm Stop")
        )
        if not confirmed:
            return
        
        self.status_log.write("Stopping Robust server...")
        # Send shutdown command to tmux session
        tmux.send_text("vgctl:robust", "shutdown", self.app_ref.transport)
    
    async def restart_robust(self) -> None:
        """Restart Robust server."""
        await self.stop_robust()
        await asyncio.sleep(2)
        await self.start_robust()
    
    async def view_console(self) -> None:
        """View Robust console output."""
        output = tmux.capture_output("vgctl:robust", 50, self.app_ref.transport)
        if output:
            self.status_log.write("=== Robust Console Output ===")
            self.status_log.write(output)
        else:
            self.status_log.write("No console output available")

class SystemInfoScreen(Screen):
    """Screen for system information."""
    
    def compose(self) -> ComposeResult:
        info_table = DataTable(zebra_stripes=True)
        info_table.add_columns("Property", "Value")
        
        # Add system information
        host_info = get_host_info()
        info_table.add_row("Hostname", host_info.hostname)
        info_table.add_row("OS", host_info.os_info)
        info_table.add_row("Uptime", host_info.uptime)
        info_table.add_row("Python Version", platform.python_version())
        
        yield Container(
            Vertical(
                Label("System Information", classes="section-title"),
                Button("Back", id="back"),
                info_table,
                classes="sysinfo-content"
            )
        )
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()

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