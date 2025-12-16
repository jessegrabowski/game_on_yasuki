import sys
import argparse
from pathlib import Path

# Ensure we can import from app/
root = Path(__file__).parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Launch Game on, Yasuki!")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Set up logging before importing GUI
    from app import setup_logging

    setup_logging(debug=args.debug)

    from app.gui.__main__ import main

    main()
