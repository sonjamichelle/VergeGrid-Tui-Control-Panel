"""
Textual-based VergeGrid Control Panel (skeleton).

This replaces the dialog/whiptail menus with a real TUI that can
grow into a PyQt GUI later. Backend calls are stubbed and will be
hooked up to the existing tmux/OpenSim logic in vg/backend/*.
"""

from __future__ import annotations

import platform
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.screen import ModalScreen
from textual.reactive import reactive
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    Static,
    Log,
    Input,
)

from vg.backend import settings, transport

__version__ = "v0.8.3-alpha"


NavItem = Tuple[str, str]  # (key, label)

NAV_ITEMS: List[NavItem] = [
    ("robust", "Robust Controls"),
    ("estates", "Estate Controls"),
    ("login", "Login Controls"),
    ("status", "Region Status"),
    ("sysinfo", "System Info"),
    ("settings", "Settings"),
    ("quit", "Quit"),
]


@dataclass
class HostInfo:
    hostname: str
    pretty_os: str
    uptime: str


def gather_host_info() -> HostInfo:
    hostname = socket.gethostname()
    pretty_os = platform.platform()
    # Placeholder uptime; replace with real uptime probe later.
    uptime = "unknown"
    return HostInfo(hostname=hostname, pretty_os=pretty_os, uptime=uptime)


class Sidebar(ListView):
    """Left navigation list."""

    def __init__(self) -> None:
        items = [ListItem(Label(text)) for _, text in NAV_ITEMS]
        super().__init__(*items, id="sidebar")


class HeaderPanel(Static):
    """Top header with build info."""

    host: reactive[HostInfo] = reactive(gather_host_info())

    def __init__(self, version: str, mode: str) -> None:
        super().__init__(id="vg-header")
        self.version = version
        self.mode = mode

    def on_mount(self) -> None:
        self.set_interval(5, self.refresh_host_info)

    def refresh_host_info(self) -> None:
        self.host = gather_host_info()

    def render(self) -> str:
        h = self.host
        return (
            f"VergeGrid Control Panel  |  Build: {self.version}  |  "
            f"Host: {h.hostname}  |  OS: {h.pretty_os}  |  Uptime: {h.uptime}  |  Mode: {self.mode}"
        )


class MainPanel(Container):
    """Main content area that swaps panels based on navigation."""

    def __init__(self) -> None:
        super().__init__(id="main")
        self.body = Static("Select an option from the left menu.")

    def compose(self) -> ComposeResult:
        yield self.body

    def set_body(self, widget: Static | Container) -> None:
        self.body.remove()
        self.body = widget
        self.mount(widget)


class TestStatusModal(ModalScreen[None]):
    """Transient modal to show test progress/results."""

    def compose(self) -> ComposeResult:
        self.log = Log(highlight=False, id="test-status-log")
        yield self.log

    def update(self, message: str) -> None:
        self.log.write(message)


class VGApp(App):
    """Textual application shell."""

    CSS = """
    Screen { layout: vertical; }
    #top { layout: horizontal; }
    #sidebar { width: 26; border: solid $accent; }
      #main { border: solid $accent; }
      #content { padding: 1 2; }
      .section-title { text-style: bold; }
      .input-wide { width: 40; min-width: 20; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("ctrl+s", "save_settings", "Save Settings"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.config = settings.load_settings()
        cfg = transport.TransportConfig(
            mode="ssh",
            host=self.config.remote_host or None,
            user=self.config.remote_user or None,
            port=self.config.remote_port,
            password=self.config.remote_password or None,
        )
        self.transport = transport.detect_transport(self.config.base, self.config.estates, cfg=cfg)
        self.transport_mode = "unknown"
        self.settings_status: Log | None = None
        self.settings_inputs: Dict[str, Input] = {}

    def compose(self) -> ComposeResult:
        yield HeaderPanel(version=__version__, mode=self.transport_mode)
        with Horizontal(id="top"):
            yield Sidebar()
            yield MainPanel()
        yield Footer()

    async def on_mount(self) -> None:
        sidebar = self.query_one(Sidebar)
        sidebar.index = 0
        await self.show_section(NAV_ITEMS[0][0])

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        key, _ = NAV_ITEMS[idx]
        if key == "quit":
            await self.action_quit()
            return
        await self.show_section(key)

    async def action_refresh(self) -> None:
        sidebar = self.query_one(Sidebar)
        idx = sidebar.index
        key, _ = NAV_ITEMS[idx]
        if key != "quit":
            await self.show_section(key)

    async def show_section(self, key: str) -> None:
        panel = self.query_one(MainPanel)
        builders: Dict[str, Callable[[], Static | Container]] = {
            "robust": self._build_robust_panel,
            "estates": self._build_estates_panel,
            "login": self._build_login_panel,
            "status": self._build_status_panel,
            "sysinfo": self._build_sysinfo_panel,
            "settings": self._build_settings_panel,
        }
        builder = builders.get(key)
        if builder is None:
            panel.set_body(Static(f"Unknown panel '{key}'", id="content"))
            return
        panel.set_body(builder())

    def _build_section(self, title: str, content: str | Widget) -> Container:
        header = Label(title, classes="section-title")
        if isinstance(content, Widget):
            body: Widget = content
        else:
            log = Log(highlight=False)
            log.write(content)
            body = log
        return Vertical(header, body)

    def _build_robust_panel(self) -> Container:
        body = Log(highlight=False)
        body.write("Robust Controls\n\nActions will be wired to tmux sessions.\n")
        body.write("Planned: start/stop robust, attach console, status view.")
        return self._build_section("Robust Controls", body)

    def _build_estates_panel(self) -> Container:
        table = DataTable(zebra_stripes=True)
        table.add_columns("Estate", "Status")
        # Placeholder data; will populate from estates.detect_estates + running_instance
        table.add_row("example_estate", "UNKNOWN")
        return self._build_section("Estate Controls", table)

    def _build_login_panel(self) -> Container:
        body = Log(highlight=False)
        body.write("Login Controls\n\nPlanned actions:\n")
        body.write("- Enable/Disable logins (one/all running)\n")
        body.write("- Show login status\n")
        body.write("- Robust login level/message\n")
        return self._build_section("Login Controls", body)

    def _build_status_panel(self) -> Container:
        table = DataTable(zebra_stripes=True)
        table.add_columns("Region", "Status")
        table.add_row("example_region", "RUNNING")
        return self._build_section("Region Status", table)

    def _build_sysinfo_panel(self) -> Container:
        body = Log(highlight=False)
        body.write("System Info\n\nPlanned:\n")
        body.write("- Static snapshot (CPU, RAM, disk, net)\n")
        body.write("- Live stats view with async updates\n")
        return self._build_section("System Info", body)

    def _build_settings_panel(self) -> Container:
        base = self.config.base
        estates_root = self.config.estates
        remote_host = self.config.remote_host
        remote_user = self.config.remote_user
        remote_port = str(self.config.remote_port)
        remote_password = self.config.remote_password
        remote_password_confirm = ""

        self.settings_inputs = {
            "base": Input(value=base, placeholder="/home/opensim/opensim/bin", classes="input-wide"),
            "estates": Input(value=estates_root, placeholder="/home/opensim/opensim/bin/Estates", classes="input-wide"),
            "remote_host": Input(value=remote_host, placeholder="server.example.com", classes="input-wide"),
            "remote_user": Input(value=remote_user, placeholder="opensim", classes="input-wide"),
            "remote_port": Input(value=remote_port, placeholder="22", classes="input-wide"),
            "remote_password": Input(
                value=remote_password,
                placeholder="(optional)",
                password=True,
                id="remote-password-input",
                classes="input-wide",
            ),
            "remote_password_confirm": Input(
                value=remote_password_confirm,
                placeholder="retype password",
                password=True,
                id="remote-password-confirm-input",
                classes="input-wide",
            ),
        }
        form = Vertical(
            Label("Settings", classes="section-title"),
            Label("BASE"), self.settings_inputs["base"],
            Label("ESTATES"), self.settings_inputs["estates"],
            Label("Host"), self.settings_inputs["remote_host"],
            Label("User"), self.settings_inputs["remote_user"],
            Label("Port"), self.settings_inputs["remote_port"],
            Static("---- Password (masked) ----"),
            Label("Password"), self.settings_inputs["remote_password"],
            Label("Confirm Password"), self.settings_inputs["remote_password_confirm"],
            Button("Toggle Mask", id="toggle-password-mask", variant="warning"),
            Button("Save Settings (Ctrl+S)", id="settings-save", variant="primary"),
            Button("Test Settings", id="settings-test", variant="warning"),
            id="settings-form",
        )
        # Compact status log to the right, capped at 5 lines.
        self.settings_status = None
        return VerticalScroll(form, id="settings-left")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings-save":
            await self._save_settings()
        elif event.button.id == "toggle-password-mask":
            await self._toggle_password_mask()
        elif event.button.id == "settings-test":
            await self._test_settings()

    async def action_save_settings(self) -> None:
        await self._save_settings()

    async def _toggle_password_mask(self) -> None:
        pw = self.settings_inputs.get("remote_password")
        pwc = self.settings_inputs.get("remote_password_confirm")
        if pw:
            pw.password = not pw.password
        if pwc and pw:
            pwc.password = pw.password

    async def _test_settings(self) -> None:
        """Test SSH connectivity; update status but do not change mode."""
        try:
            remote_host = self.settings_inputs["remote_host"].value.strip()
            remote_user = self.settings_inputs["remote_user"].value.strip()
            remote_port_raw = self.settings_inputs["remote_port"].value.strip() or "22"
            remote_port = int(remote_port_raw)
            remote_key = self.settings_inputs["remote_key"].value.strip()
            remote_password = self.settings_inputs["remote_password"].value.strip()
            remote_password_confirm = self.settings_inputs["remote_password_confirm"].value.strip()
        except Exception as exc:
            if self.settings_status:
                self.settings_status.clear()
                self.settings_status.write(f"Error reading settings: {exc}")
            return

        if remote_password != remote_password_confirm:
            if self.settings_status:
                self.settings_status.clear()
                self.settings_status.write("Passwords do not match.")
            return

        if self.settings_status:
            self.settings_status.clear()
            self.settings_status.write(
                f"Testing SSH to {remote_user or '(current user)'}@{remote_host}:{remote_port} "
                f"{'(key)' if remote_key else '(password)'}..."
            )

        # Build SSH test command. Password-only will be skipped unless key provided.
        user_host = f"{remote_user + '@' if remote_user else ''}{remote_host}"
        cmd = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            "-p",
            str(remote_port),
        ]
        if remote_key:
            cmd += ["-i", remote_key]
        cmd += [user_host, "true"]

        cp = None
        try:
            cp = subprocess.run(
                cmd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except Exception as exc:
            if self.settings_status:
                self.settings_status.write(f"Test error: {exc}")
            return

        if cp and cp.returncode == 0:
            self.transport_mode = "ssh"
            header = self.query_one(HeaderPanel)
            header.mode = self.transport_mode
            header.refresh()
            if self.settings_status:
                self.settings_status.write("Test passed: SSH reachable with key.")
        else:
            if self.settings_status:
                # show stderr for visibility
                err = (cp.stderr or "").strip() if cp else "no response"
                self.settings_status.write(f"Test failed (key auth). stderr: {err}")

    async def _save_settings(self) -> None:
        try:
            base = self.settings_inputs["base"].value.strip()
            estates = self.settings_inputs["estates"].value.strip()
            remote_host = self.settings_inputs["remote_host"].value.strip()
            remote_user = self.settings_inputs["remote_user"].value.strip()
            remote_port_raw = self.settings_inputs["remote_port"].value.strip() or "22"
            remote_port = int(remote_port_raw)
            remote_key = self.settings_inputs["remote_key"].value.strip()
            remote_password = self.settings_inputs["remote_password"].value.strip()
            remote_password_confirm = self.settings_inputs["remote_password_confirm"].value.strip()
        except Exception as exc:
            if self.settings_status:
                self.settings_status.write(f"Error reading settings: {exc}")
            return

        if remote_password != remote_password_confirm:
            if self.settings_status:
                self.settings_status.write("Passwords do not match.")
            return

        self.config.base = base
        self.config.estates = estates
        self.config.remote_host = remote_host
        self.config.remote_user = remote_user
        self.config.remote_port = remote_port
        self.config.remote_key = remote_key
        self.config.remote_password = remote_password
        settings.save_settings(self.config)

        cfg = transport.TransportConfig(
            mode="ssh",
            host=remote_host or None,
            user=remote_user or None,
            port=remote_port,
            identity_file=remote_key or None,
            password=remote_password or None,
        )
        # Do not change mode here; only test updates status. Mode stays unknown until test succeeds.
        if self.settings_status:
            self.settings_status.clear()
            self.settings_status.write("Settings saved. Run 'Test Settings' to validate SSH.")


if __name__ == "__main__":
    VGApp().run()
