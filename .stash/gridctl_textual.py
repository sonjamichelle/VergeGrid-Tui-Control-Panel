#!/usr/bin/env python3
"""
Launcher stub that hands control to the complete Textual conversion.
"""

import sys
from pathlib import Path

# Make sure the project root is on Python path so we can import sibling modules.
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def main() -> None:
    try:
        from gridctl_complete import main as complete_main
    except ImportError as exc:
        print(f"Error importing required modules: {exc}")
        print("Please install dependencies with: pip install -r requirements.txt")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)

    complete_main()


if __name__ == "__main__":
    main()
