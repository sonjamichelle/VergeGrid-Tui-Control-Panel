#!/usr/bin/env python3
"""
Launcher for the complete VergeGrid Control Panel Textual TUI.
This is the fully converted version of gridctl-portable.sh.
"""

import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from gridctl_complete import main
    main()
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Please install dependencies with: pip install -r requirements.txt")
    sys.exit(1)
except KeyboardInterrupt:
    print("\nExiting...")
    sys.exit(0)