"""
Main execution script for DropSync Server.
Run with: python3 -m dropsync_server.main [options]
"""

import sys
from pathlib import Path

# Add project root to sys.path if executed directly
package_dir = Path(__file__).resolve().parent.parent
if str(package_dir) not in sys.path:
    sys.path.insert(0, str(package_dir))

from dropsync_server.cli import main

if __name__ == "__main__":
    main()
