"""
RCON (Remote Console) communication module for ASA Control.

Handles communication with the ARK server via RCON protocol.
"""

import os
import socket
import struct
from typing import NamedTuple, Optional

from .constants import RconPacketTypes
from .config import StartParamsHelper, IniConfigHelper
from .errors import RconPasswordNotFoundError, RconPortNotFoundError, RconAuthenticationError


class RconPacket(NamedTuple):
    """RCON packet structure."""
    size: int
    id: int
    type: int
    body: str


class RconClient:
    """RCON client for communicating with ARK server."""
    
    def __init__(self, server_ip: str = '127.0.0.1', port: Optional[int] = None, password: Optional[str] = None):
        """
        Initialize RCON client.
        
        Args:
            server_ip: Server IP address
            port: RCON port (auto-detected if None)
            password: RCON password (auto-detected if None)
        """
        self.server_ip = server_ip
        self.port = port or self._identify_port()
        self.password = password or self._identify_password()
        self.socket = None
    
    def _identify_password(self) -> str:
        """
        Identify RCON password from start parameters or INI file.
        
        Returns:
            The RCON password
            
        Raises:
            RconPasswordNotFoundError: If password cannot be found
        """
        # Try to get password from start parameters
        start_params = os.environ.get('ASA_START_PARAMS')
        password = StartParamsHelper.get_value(start_params, 'ServerAdminPassword')
        
        if password:
            return password
        
        # Try to get password from GameUserSettings.ini
        password = IniConfigHelper.get_server_setting('ServerAdminPassword')
        
        if password:
            return password
            
        raise RconPasswordNotFoundError("Could not find RCON password in start parameters or configuration")
    
    def _identify_port(self) -> int:
        """
        Identify RCON port from start parameters or INI file.
        
        Returns:
            The RCON port
            
        Raises:
            RconPortNotFoundError: If port cannot be found
        """
        # Try to get port from start parameters
        start_params = os.environ.get('ASA_START_PARAMS')
        port_str = StartParamsHelper.get_value(start_params, 'RCONPort')
        
        if port_str:
            return int(port_str)
        
        # Try to get port from GameUserSettings.ini
        port_str = IniConfigHelper.get_server_setting('RCONPort')
        
        if port_str:
            return int(port_str)
            
        raise RconPortNotFoundError("Could not find RCON port in start parameters or configuration")
    
    def _send_packet(self, data: str, packet_type: int) -> RconPacket:
        """
        Send an RCON packet and receive response.
        
        Args:
            data: The data to send
            packet_type: The packet type
            
        Returns:
            The response packet
        """
        packet_size = 10 + len(data.encode('utf-8'))
        packet_id = 0
        
        # Pack the packet: size, id, type, body (null-terminated), extra null byte
        packet_data = struct.pack('<III', packet_size, packet_id, packet_type)
        packet_data += data.encode('utf-8') + b'\x00\x00'
        
        # Ensure the socket is connected (helps static type checkers and avoids None attribute errors)
        assert self.socket is not None, "RCON socket is not connected"
        self.socket.sendall(packet_data)
        
        # Receive response
        response_data = self.socket.recv(4096)
        
        # Unpack response: size, id, type, then body
        size, response_id, response_type = struct.unpack('<III', response_data[:12])
        body = response_data[12:].split(b'\x00')[0].decode('utf-8')
        
        return RconPacket(size, response_id, response_type, body)
    
    def _authenticate(self) -> bool:
        """
        Authenticate with the RCON server.
        
        Returns:
            True if authentication successful, False otherwise
        """
        response = self._send_packet(self.password, RconPacketTypes.AUTH)
        return response.id != -1
    
    def connect(self) -> None:
        """
        Connect to the RCON server and authenticate.
        
        Raises:
            RconAuthenticationError: If authentication fails
        """
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.server_ip, self.port))
        
        if not self._authenticate():
            raise RconAuthenticationError("RCON authentication failed")
    
    def execute_command(self, command: str) -> str:
        """
        Execute an RCON command.
        
        Args:
            command: The command to execute
            
        Returns:
            The command response
        """
        if not self.socket:
            self.connect()
            
        response = self._send_packet(command, RconPacketTypes.EXEC_COMMAND)
        
        if response.type == RconPacketTypes.RESPONSE_VALUE:
            return response.body
        else:
            raise Exception(f"Command execution failed: {response}")
    
    def close(self) -> None:
        """Close the RCON connection."""
        if self.socket:
            self.socket.close()
            self.socket = None
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


def execute_rcon_command(command: str, server_ip: str = '127.0.0.1') -> str:
    """
    Execute a single RCON command (convenience function).
    
    Args:
        command: The command to execute
        server_ip: Server IP address
        
    Returns:
        The command response
    """
    with RconClient(server_ip) as client:
        return client.execute_command(command)
