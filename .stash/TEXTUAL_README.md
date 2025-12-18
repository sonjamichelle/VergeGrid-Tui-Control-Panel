# VergeGrid Control Panel - Textual Version

This is the modern Textual-based TUI version of the VergeGrid Control Panel, converted from the original bash script (`gridctl-portable.sh`).

## Features

- **Modern TUI Interface**: Built with Textual for a rich terminal user interface
- **Estate Management**: Start, stop, and monitor OpenSim estates
- **Robust Controls**: Manage Robust server instances
- **System Information**: View host and system details
- **Settings Management**: Configure paths and remote connections
- **Tmux Integration**: Uses tmux for session management (like the original script)

## Quick Start

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the Application**:
   ```bash
   python run_textual.py
   ```
   
   Or directly:
   ```bash
   python gridctl_textual.py
   ```

## Key Differences from Bash Script

### Advantages of Textual Version:
- **Better UX**: Rich terminal interface with mouse support
- **Real-time Updates**: Live status updates and progress indicators
- **Structured Navigation**: Clear menu system and screen management
- **Error Handling**: Better error reporting and user feedback
- **Extensibility**: Easy to add new features and screens

### Converted Features:
- ✅ Estate detection and management
- ✅ Robust server controls
- ✅ Settings management
- ✅ System information display
- ✅ Tmux session management
- ✅ Remote SSH support (via existing backend)

### Navigation:
- Use **arrow keys** or **mouse** to navigate
- **Enter** to select buttons/options
- **Q** or **Ctrl+C** to quit
- **Back** buttons to return to previous screens

## Configuration

The application uses the same settings file as the original script:
- **Settings File**: `~/.vergegrid_settings`
- **Session Directory**: `~/.gridstl_sessions`

### Settings Options:
- **Base Directory**: OpenSim installation path
- **Estates Directory**: Path to estates folder
- **Remote Host**: SSH hostname (optional)
- **Remote User**: SSH username (optional)
- **Remote Port**: SSH port (default: 22)
- **SSH Key Path**: Path to SSH private key (optional)

## Architecture

The Textual version maintains the same backend architecture:
- **Backend Modules**: Uses existing `vg.backend.*` modules
- **Transport Layer**: Supports both local and SSH execution
- **Tmux Integration**: Same tmux session management as bash script
- **Settings**: Compatible settings format

## Screens

1. **Main Menu**: Primary navigation hub
2. **Estate Controls**: Manage individual estates and bulk operations
3. **Robust Controls**: Start/stop/restart Robust server
4. **System Info**: Display system information
5. **Settings**: Configure application settings

## Development

The Textual version is designed to be:
- **Modular**: Easy to extend with new screens and features
- **Maintainable**: Clear separation of concerns
- **Compatible**: Works with existing backend infrastructure
- **Future-ready**: Foundation for GUI versions

## Migration from Bash Script

The Textual version provides the same core functionality as `gridctl-portable.sh` but with a modern interface. All tmux sessions, settings, and estate management work the same way.

To migrate:
1. Your existing `~/.vergegrid_settings` file will work as-is
2. Existing tmux sessions remain compatible
3. All estate and Robust management functions are preserved

## Requirements

- Python 3.8+
- Textual 0.50+
- tmux (for session management)
- SSH client (for remote operations)

See `requirements.txt` for complete dependency list.