# VergeGrid TUI Control Panel – Quick Usage Guide

This document provides a quick overview for running the VergeGrid TUI Control Panel
and the helper launcher script `gridctl.sh`. A full manual will be created later
as additional features are developed.

---

## 1. What This Tool Does

The VergeGrid TUI Control Panel is a lightweight terminal interface for managing:

- OpenSim estates and regions
- System performance and health
- Service wrappers and launchers
- Folder and configuration discovery
- Future integrations for GUI and WebUI layers

This early alpha release focuses on the command line experience.

---

## 2. Installing the Launcher Script

Copy `gridctl.sh` to the server where your OpenSim instance runs.



Example:

scp gridctl.sh user@yourserver:/home/user/

`Move it into place if desired:`

mv gridctl.sh /usr/local/bin/gridctl

`---  ## 3. Make the Script Executable  On the server, run:`

chmod +x gridctl.sh

`If moved to /usr/local/bin:`

chmod +x /usr/local/bin/gridctl

`---  ## 4. Running the TUI  From the script’s directory:`

./gridctl.sh

`If installed globally:`

gridctl

``The TUI will start immediately and display the main control panel menu.  ---  ## 5. Requirements  - Python 3.10 or newer - Modules listed in `requirements.txt` - Access to OpenSim installation paths - A terminal that supports basic ANSI color output  Install dependencies:``

pip install -r requirements.txt

`---  ## 6. Troubleshooting  ### TUI does not start Ensure Python is installed:`

python3 --version

`### Permission denied Make sure the script is executable:`

chmod +x gridctl.sh

`### Cannot locate OpenSim base directory Manually set environment variables:`

export VG_BASE=/path/to/opensim/bin  
export VG_ESTATES=/path/to/opensim/bin/Estates

``### Stats not updating System may not support required `/proc` or psutil features.   Check:``

pip install psutil

`---  ## 7. Updates and Versioning  New versions will be tagged in the repository using semantic versioning:`

v0.x.x = development alpha  
v1.x.x = stable combined UI suite

`Check the CHANGELOG.md for detailed updates.  ---  ## 8. Full Manual Coming Soon  As the TUI matures and gains more modules such as:  - Service manager - Estate manager - Region inspector - Log viewer - Port registry editor - GUI & WebUI integrations  A full administrative manual will be added under:`

docs/manual/

`Stay tuned for incremental improvements.  ---`
