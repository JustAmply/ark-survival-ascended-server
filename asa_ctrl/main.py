#!/usr/bin/env python3
"""
Main entry point for ASA Control.

This script provides the main command line interface for managing
ARK: Survival Ascended servers.
"""

import sys
import os

# Add parent directory to path for direct execution
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if __name__ == '__main__':
    from asa_ctrl.cli import main
    main()