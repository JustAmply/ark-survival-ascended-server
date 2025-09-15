"""
Server restart management for ASA Control.

Handles automated server restarts based on cron schedules.
"""

import os
import re
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .logging_config import get_logger
from .errors import RestartScheduleInvalidError
from .rcon import execute_rcon_command


def validate_cron_expression(cron_expr: str) -> bool:
    """
    Validate a cron expression format.
    
    Args:
        cron_expr: The cron expression to validate (e.g., "0 4 * * *")
        
    Returns:
        True if valid, False otherwise
    """
    if not cron_expr or not isinstance(cron_expr, str):
        return False
    
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return False
    
    # Basic validation for each field
    minute, hour, day, month, weekday = parts
    
    # Simple regex patterns for cron fields
    patterns = [
        r'^(\*|[0-5]?[0-9]|[0-5]?[0-9]-[0-5]?[0-9]|[0-5]?[0-9]/[0-9]+|\*/[0-9]+)$',  # minute
        r'^(\*|[01]?[0-9]|2[0-3]|[01]?[0-9]-[01]?[0-9]|2[0-3]-2[0-3]|[01]?[0-9]/[0-9]+|2[0-3]/[0-9]+|\*/[0-9]+)$',  # hour
        r'^(\*|[1-9]|[12][0-9]|3[01]|[1-9]-[1-9]|[12][0-9]-[12][0-9]|3[01]-3[01]|[1-9]/[0-9]+|[12][0-9]/[0-9]+|3[01]/[0-9]+|\*/[0-9]+)$',  # day
        r'^(\*|[1-9]|1[0-2]|[1-9]-[1-9]|1[0-2]-1[0-2]|[1-9]/[0-9]+|1[0-2]/[0-9]+|\*/[0-9]+)$',  # month
        r'^(\*|[0-7]|[0-7]-[0-7]|[0-7]/[0-9]+|\*/[0-9]+)$',  # weekday
    ]
    
    for part, pattern in zip(parts, patterns):
        if not re.match(pattern, part):
            return False
    
    return True


def setup_restart_cron(cron_schedule: str, warning_minutes: int = 5) -> None:
    """
    Set up a cron job for server restart with optional warning.
    
    Args:
        cron_schedule: Cron expression for restart timing (e.g., "0 4 * * *")
        warning_minutes: Minutes before restart to send warning (default: 5)
        
    Raises:
        RestartScheduleInvalidError: If cron schedule format is invalid
    """
    logger = get_logger(__name__)
    
    if not validate_cron_expression(cron_schedule):
        raise RestartScheduleInvalidError(f"Invalid cron expression: {cron_schedule}")
    
    # Create restart script
    restart_script = _create_restart_script(warning_minutes)
    restart_script_path = "/usr/local/bin/asa-restart.sh"
    
    with open(restart_script_path, 'w') as f:
        f.write(restart_script)
    os.chmod(restart_script_path, 0o755)
    
    # Add cron job
    cron_entry = f"{cron_schedule} {restart_script_path}\n"
    
    # Get existing crontab, remove any existing asa-restart entries, and add new one
    try:
        existing_cron = subprocess.run(
            ['crontab', '-l'], 
            capture_output=True, 
            text=True, 
            check=False
        ).stdout
    except Exception:
        existing_cron = ""
    
    # Filter out existing asa-restart entries
    filtered_lines = []
    for line in existing_cron.splitlines():
        if 'asa-restart.sh' not in line:
            filtered_lines.append(line)
    
    # Add new entry
    filtered_lines.append(cron_entry.strip())
    
    # Write updated crontab
    new_crontab = '\n'.join(filtered_lines) + '\n'
    process = subprocess.run(
        ['crontab', '-'], 
        input=new_crontab, 
        text=True, 
        capture_output=True
    )
    
    if process.returncode != 0:
        raise RestartScheduleInvalidError(f"Failed to update crontab: {process.stderr}")
    
    logger.info("Configured server restart schedule: %s", cron_schedule)


def _create_restart_script(warning_minutes: int) -> str:
    """
    Create the restart script content.
    
    Args:
        warning_minutes: Minutes before restart to send warning
        
    Returns:
        Script content as string
    """
    warning_script = ""
    if warning_minutes > 0:
        warning_script = f'''
# Send warning
/usr/local/bin/asa-ctrl rcon --exec "serverchat Server will restart in {warning_minutes} minutes" 2>/dev/null || true
sleep {warning_minutes * 60}
'''
    
    return f'''#!/bin/bash
# ARK Server Restart Script
# Generated automatically by asa-ctrl

set -e

LOG_FILE="/tmp/asa-restart.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "$(date): Starting server restart process"
{warning_script}
# Send final warning
/usr/local/bin/asa-ctrl rcon --exec "serverchat Server restarting now..." 2>/dev/null || true
sleep 3

# Save world data before restart
/usr/local/bin/asa-ctrl rcon --exec "saveworld" 2>/dev/null || true
sleep 5

# Gracefully stop the server process
echo "$(date): Stopping server process"
pkill -TERM -f "ArkAscendedServer.exe" || pkill -TERM -f "AsaApiLoader.exe" || true

# Wait for graceful shutdown
sleep 10

# Force kill if still running
pkill -KILL -f "ArkAscendedServer.exe" || pkill -KILL -f "AsaApiLoader.exe" || true

# In Docker, exit the container to trigger restart (if restart policy is set)
# Or kill the main start_server.sh process to restart the loop
echo "$(date): Triggering container restart"
pkill -TERM -f "/usr/bin/start_server.sh" || exit 0
'''


def disable_restart_cron() -> None:
    """Remove the restart cron job."""
    logger = get_logger(__name__)
    
    try:
        existing_cron = subprocess.run(
            ['crontab', '-l'], 
            capture_output=True, 
            text=True, 
            check=False
        ).stdout
    except Exception:
        existing_cron = ""
    
    # Filter out asa-restart entries
    filtered_lines = []
    for line in existing_cron.splitlines():
        if 'asa-restart.sh' not in line:
            filtered_lines.append(line)
    
    # Write updated crontab
    new_crontab = '\n'.join(filtered_lines) + '\n'
    subprocess.run(
        ['crontab', '-'], 
        input=new_crontab, 
        text=True, 
        capture_output=True
    )
    
    # Remove restart script
    restart_script_path = "/usr/local/bin/asa-restart.sh"
    if os.path.exists(restart_script_path):
        os.remove(restart_script_path)
    
    logger.info("Removed server restart schedule")


def get_restart_schedule() -> Optional[str]:
    """
    Get the current restart schedule from crontab.
    
    Returns:
        Cron expression if found, None otherwise
    """
    try:
        existing_cron = subprocess.run(
            ['crontab', '-l'], 
            capture_output=True, 
            text=True, 
            check=False
        ).stdout
        
        for line in existing_cron.splitlines():
            if 'asa-restart.sh' in line:
                # Extract cron expression (first 5 fields)
                parts = line.strip().split()
                if len(parts) >= 6:
                    return ' '.join(parts[:5])
        
    except Exception:
        pass
    
    return None