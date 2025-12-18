#!/usr/bin/env python3
"""
Minimal working VergeGrid TUI that actually does stuff.
"""

import os
import subprocess
import time
from pathlib import Path
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Button, Header, Footer, Log, Static, Label
from textual.screen import Screen

class MainApp(App):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Label("VergeGrid Control Panel", classes="title"),
                Horizontal(
                    Button("Start Robust", id="start_robust", variant="success"),
                    Button("Stop Robust", id="stop_robust", variant="error"),
                    Button("List Estates", id="list_estates", variant="primary"),
                    Button("System Info", id="sysinfo", variant="warning"),
                ),
                Horizontal(
                    Button("Test Tmux", id="test_tmux"),
                    Button("Kill All", id="kill_all", variant="error"),
                    Button("Clear Log", id="clear_log"),
                    Button("Quit", id="quit"),
                ),
                Log(id="output", highlight=False),
            )
        )
        yield Footer()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        log = self.query_one("#output", Log)
        
        if event.button.id == "quit":
            self.exit()
        
        elif event.button.id == "clear_log":
            log.clear()
        
        elif event.button.id == "start_robust":
            log.write("=== STARTING ROBUST ===")
            
            # Check if already running
            result = subprocess.run(["pgrep", "-f", "Robust"], capture_output=True)
            if result.returncode == 0:
                log.write("Robust is already running!")
                return
            
            # Try to start Robust
            base_dir = "/home/opensim/opensim/bin"  # Default path
            
            if Path(f"{base_dir}/Robust.dll").exists():
                cmd = f'cd "{base_dir}" && dotnet Robust.dll -inifile=Robust.HG.ini'
            elif Path(f"{base_dir}/Robust.exe").exists():
                cmd = f'cd "{base_dir}" && mono Robust.exe -inifile=Robust.HG.ini'
            else:
                log.write(f"ERROR: No Robust executable found in {base_dir}")
                return
            
            # Start in tmux
            try:
                subprocess.run(["tmux", "new-session", "-d", "-s", "vgctl"], 
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                result = subprocess.run([
                    "tmux", "new-window", "-t", "vgctl", "-n", "robust", 
                    "bash", "-c", cmd
                ], capture_output=True, text=True)
                
                if result.returncode == 0:
                    log.write("✓ Robust started in tmux session 'vgctl:robust'")
                    log.write("  Attach with: tmux attach -t vgctl")
                else:
                    log.write(f"✗ Failed to start Robust: {result.stderr}")
            except Exception as e:
                log.write(f"✗ Error: {e}")
        
        elif event.button.id == "stop_robust":
            log.write("=== STOPPING ROBUST ===")
            
            # Try graceful shutdown first
            try:
                result = subprocess.run([
                    "tmux", "send-keys", "-t", "vgctl:robust", "shutdown", "C-m"
                ], capture_output=True)
                
                if result.returncode == 0:
                    log.write("✓ Sent graceful shutdown command")
                else:
                    log.write("No tmux session found, trying force kill...")
                    
                # Force kill if needed
                result = subprocess.run(["pkill", "-f", "Robust"], capture_output=True)
                if result.returncode == 0:
                    log.write("✓ Force killed Robust processes")
                else:
                    log.write("No Robust processes found")
                    
            except Exception as e:
                log.write(f"✗ Error: {e}")
        
        elif event.button.id == "list_estates":
            log.write("=== SCANNING FOR ESTATES ===")
            
            estates_dir = "/home/opensim/opensim/bin/Estates"  # Default path
            estates_path = Path(estates_dir)
            
            if not estates_path.exists():
                log.write(f"✗ Estates directory not found: {estates_dir}")
                return
            
            found_estates = []
            for estate_dir in estates_path.iterdir():
                if not estate_dir.is_dir():
                    continue
                
                # Check for OpenSim.ini
                if not (estate_dir / "OpenSim.ini").exists():
                    continue
                
                # Check for Regions directory
                regions_dir = estate_dir / "Regions"
                if not regions_dir.exists():
                    continue
                
                # Check for .ini files in Regions
                ini_files = list(regions_dir.glob("*.ini"))
                if not ini_files:
                    continue
                
                # Check if running
                result = subprocess.run([
                    "pgrep", "-f", f"inidirectory={estate_dir}"
                ], capture_output=True)
                
                status = "RUNNING" if result.returncode == 0 else "STOPPED"
                found_estates.append((estate_dir.name, status))
            
            if found_estates:
                log.write(f"Found {len(found_estates)} valid estates:")
                for name, status in found_estates:
                    log.write(f"  {name}: {status}")
            else:
                log.write("No valid estates found")
        
        elif event.button.id == "sysinfo":
            log.write("=== SYSTEM INFO ===")
            
            # Hostname
            try:
                hostname = subprocess.run(["hostname"], capture_output=True, text=True)
                log.write(f"Hostname: {hostname.stdout.strip()}")
            except:
                log.write("Hostname: unknown")
            
            # Uptime
            try:
                uptime = subprocess.run(["uptime"], capture_output=True, text=True)
                log.write(f"Uptime: {uptime.stdout.strip()}")
            except:
                log.write("Uptime: unknown")
            
            # Memory
            try:
                free = subprocess.run(["free", "-h"], capture_output=True, text=True)
                lines = free.stdout.strip().split('\n')
                if len(lines) > 1:
                    log.write(f"Memory: {lines[1]}")
            except:
                log.write("Memory: unknown")
            
            # Disk
            try:
                df = subprocess.run(["df", "-h", "/"], capture_output=True, text=True)
                lines = df.stdout.strip().split('\n')
                if len(lines) > 1:
                    log.write(f"Disk /: {lines[1]}")
            except:
                log.write("Disk: unknown")
        
        elif event.button.id == "test_tmux":
            log.write("=== TESTING TMUX ===")
            
            # Check if tmux is installed
            try:
                result = subprocess.run(["tmux", "-V"], capture_output=True, text=True)
                log.write(f"✓ {result.stdout.strip()}")
                
                # List sessions
                result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True)
                if result.returncode == 0:
                    log.write("Active tmux sessions:")
                    for line in result.stdout.strip().split('\n'):
                        log.write(f"  {line}")
                else:
                    log.write("No active tmux sessions")
                    
            except FileNotFoundError:
                log.write("✗ tmux not installed")
            except Exception as e:
                log.write(f"✗ Error: {e}")
        
        elif event.button.id == "kill_all":
            log.write("=== KILLING ALL OPENSIM/ROBUST PROCESSES ===")
            
            # Kill Robust
            result = subprocess.run(["pkill", "-f", "Robust"], capture_output=True)
            if result.returncode == 0:
                log.write("✓ Killed Robust processes")
            
            # Kill OpenSim
            result = subprocess.run(["pkill", "-f", "OpenSim"], capture_output=True)
            if result.returncode == 0:
                log.write("✓ Killed OpenSim processes")
            
            # Kill tmux session
            result = subprocess.run(["tmux", "kill-session", "-t", "vgctl"], 
                                  capture_output=True)
            if result.returncode == 0:
                log.write("✓ Killed tmux session 'vgctl'")
            
            log.write("All processes terminated")

    CSS = """
    .title {
        text-align: center;
        text-style: bold;
        margin: 1;
    }
    
    Button {
        margin: 0 1;
    }
    
    #output {
        height: 20;
        border: solid green;
        margin: 1 0;
    }
    """

if __name__ == "__main__":
    app = MainApp()
    app.run()