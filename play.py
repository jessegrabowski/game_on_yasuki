import sys
import argparse
from pathlib import Path

# Ensure we can import from src/
src = Path(__file__).parent / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Launch Game on, Yasuki!")
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug logging and the client's debug menu"
    )
    args = parser.parse_args()

    # Set up logging before importing GUI
    from yasuki_core import setup_logging

    setup_logging(debug=args.debug)
    if args.debug:
        import yasuki_gui.config as gui_config

        gui_config.DEBUG_MODE = True

    from yasuki_gui.__main__ import main

    main()
