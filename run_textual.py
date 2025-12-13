#!/usr/bin/env python3
"""
Simple launcher for the Textual-based VergeGrid Control Panel.
This replaces the bash script with a modern Python TUI.
"""

import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from gridctl_textual import main
    main()
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Please install dependencies with: pip install -r requirements.txt")
    sys.exit(1)
except KeyboardInterrupt:
    print("\nExiting...")
    sys.exit(0)