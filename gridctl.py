#!/usr/bin/env python3

import os
import sys
import subprocess
import time
from pathlib import Path
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Button, Static, ListView, ListItem, TextArea, Label
from textual.screen import Screen
from textual import events

# Version info
VG_VERSION = "v0.9.0-alpha"
VG_DATE = "Dec 13 2025 12:00"  # Placeholder, can be updated

# Settings
SETTINGS_FILE = Path.home() / ".vergegrid_settings"
BASE = "/home/opensim/opensim/bin"
ESTATES = f"{BASE}/Estates"

def load_settings():
    global BASE, ESTATES
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, 'r') as f:
            for line in f:
                if line.startswith('VG_BASE='):
                    BASE = line.split('=', 1)[1].strip().strip('"')
                elif line.startswith('VG_ESTATES='):
                    ESTATES = line.split('=', 1)[1].strip().strip('"')
    ESTATES = ESTATES or f"{BASE}/Estates"

def save_settings():
    with open(SETTINGS_FILE, 'w') as f:
        f.write(f'VG_BASE="{BASE}"\n')
        f.write(f'VG_ESTATES="{ESTATES}"\n')

load_settings()

SESS_DIR = Path.home() / ".gridstl_sessions"
SESS_DIR.mkdir(exist_ok=True)

class MainScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Label("VergeGrid Control Panel", id="title"),
                ListView(
                    ListItem(Button("Start Robust", id="start_robust")),
                    ListItem(Button("Stop Robust", id="stop_robust")),
                    ListItem(Button("Start Estate", id="start_estate")),
                    ListItem(Button("Stop Estate", id="stop_estate")),
                    ListItem(Button("Reload Estate", id="reload_estate")),
                    ListItem(Button("Edit Config", id="edit_config")),
                    ListItem(Button("View Status", id="view_status")),
                    ListItem(Button("System Info", id="system_info")),
                    ListItem(Button("Start All Estates", id="start_all")),
                    ListItem(Button("Stop All Estates", id="stop_all")),
                    ListItem(Button("Settings", id="settings")),
                    ListItem(Button("Quit", id="quit")),
                    id="menu"
                ),
                id="main_container"
            )
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit":
            self.app.exit()
        elif event.button.id == "start_robust":
            self.app.push_screen(StartRobustScreen())
        # Add other handlers similarly

class StartRobustScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Label("Starting Robust..."),
                Button("Back", id="back")
            )
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()

class VergeGridApp(App):
    CSS = """
    #title {
        text-align: center;
        margin: 1;
    }
    #menu {
        height: 100%;
    }
    """

    def on_mount(self) -> None:
        self.push_screen(MainScreen())

if __name__ == "__main__":
    app = VergeGridApp()
    app.run()