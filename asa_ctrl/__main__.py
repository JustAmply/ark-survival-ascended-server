#!/usr/bin/env python3
"""
Main entry point for ASA Control when run as a module.

This allows the package to be executed with: python -m asa_ctrl
"""

from .cli import main

if __name__ == '__main__':
    main()
