#!/usr/bin/env python3
"""
Launcher for the ACTUALLY WORKING VergeGrid Control Panel.
This version has real backend functionality, not just UI stubs.
"""

import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from gridctl_working import main
    main()
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Please install dependencies with: pip install -r requirements.txt")
    print("Make sure psutil is installed: pip install psutil")
    sys.exit(1)
except KeyboardInterrupt:
    print("\nExiting...")
    sys.exit(0)