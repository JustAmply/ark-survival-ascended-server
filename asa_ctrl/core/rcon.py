"""
RCON (Remote Console) communication module for ASA Control.

Handles communication with the ARK server via RCON protocol.
"""

import socket
import struct
import time
from contextlib import closing
from typing import NamedTuple, Optional

from asa_ctrl.common.constants import RconPacketTypes
from asa_ctrl.common.config import AsaSettings
from asa_ctrl.common.errors import (
    RconUnconfirmedConnectionError,
    RconUnconfirmedPacketError,
    RconUnconfirmedTimeoutError,
    RconPasswordNotFoundError,
    RconPortNotFoundError,
    RconAuthenticationError,
    RconConnectionError,
    RconPacketError,
    RconTimeoutError,
)

RCON_MAX_COMMAND_LENGTH = 1000


class RconPacket(NamedTuple):
    """RCON packet structure."""
    size: int
    id: int
    type: int
    body: str


class RconPacketCodec:
    """Encode/decode RCON packets and validate raw data."""

    def __init__(self, max_packet_size: int, min_packet_size: int) -> None:
        self._max_packet_size = max_packet_size
        self._min_packet_size = min_packet_size

    def validate_packet_data(self, data: bytes, expected_min_size: Optional[int] = None) -> None:
        """
        Validate received packet data.

        Args:
            data: Raw packet data
            expected_min_size: Minimum expected packet size

        Raises:
            RconPacketError: If packet is invalid
        """
        min_size = expected_min_size if expected_min_size is not None else self._min_packet_size
        if not data:
            raise RconPacketError("Received empty packet")

        if len(data) < min_size:
            raise RconPacketError(f"Packet too small: {len(data)} < {min_size}")

        if len(data) > self._max_packet_size:
            raise RconPacketError(f"Packet too large: {len(data)} > {self._max_packet_size}")

    def encode(self, packet_id: int, packet_type: int, body: str) -> bytes:
        body_bytes = body.encode('utf-8')
        packet_size = 10 + len(body_bytes)
        packet_data = struct.pack('<Iii', packet_size, packet_id, packet_type)
        return packet_data + body_bytes + b'\x00\x00'

    def decode(self, data: bytes) -> RconPacket:
        self.validate_packet_data(data)
        if len(data) < 12:
            raise RconPacketError(f"Response too short: {len(data)} bytes")

        size, response_id, response_type = struct.unpack('<Iii', data[:12])
        if size < 10:
            raise RconPacketError(f"Invalid response size: {size}")
        if size != len(data) - 4:  # Size field doesn't include itself
            raise RconPacketError(f"Size mismatch: declared {size}, actual {len(data) - 4}")

        body_data = data[12:]
        if body_data and body_data[-1:] == b'\x00':
            body_data = body_data[:-1]

        null_pos = body_data.find(b'\x00')
        if null_pos >= 0:
            body_data = body_data[:null_pos]

        try:
            body = body_data.decode('utf-8', errors='replace')
        except UnicodeDecodeError:
            body = body_data.decode('utf-8', errors='ignore')

        return RconPacket(size, response_id, response_type, body)


class RconClient:
    """RCON client for communicating with ARK server."""
    
    # Configuration constants
    MAX_PACKET_SIZE = 4096  # Maximum value of the size field, excluding the field itself
    MIN_PACKET_SIZE = 12    # Minimum packet size (header only)
    MAX_COMMAND_LENGTH = RCON_MAX_COMMAND_LENGTH
    DEFAULT_RETRY_COUNT = 3
    DEFAULT_RETRY_DELAY = 1.0
    
    def __init__(self, server_ip: str = '127.0.0.1', port: Optional[int] = None, password: Optional[str] = None,
                 connect_timeout: float = 30.0, read_timeout: float = 10.0,
                 retry_count: int = DEFAULT_RETRY_COUNT, retry_delay: float = DEFAULT_RETRY_DELAY,
                 settings: Optional[AsaSettings] = None):
        """
        Initialize RCON client.
        
        Args:
            server_ip: Server IP address
            port: RCON port (auto-detected if None)
            password: RCON password (auto-detected if None)
            connect_timeout: Timeout for connection establishment
            read_timeout: Timeout for socket read operations
            retry_count: Number of retry attempts for failed operations
            retry_delay: Base delay between retry attempts (exponential backoff)
        """
        self.server_ip = self._validate_ip(server_ip)
        self._settings = settings or AsaSettings()
        self.port = self._validate_port(port) if port is not None else self._identify_port()
        self.password = password or self._identify_password()
        self.connect_timeout = max(1.0, connect_timeout)
        self.read_timeout = max(1.0, read_timeout) 
        self.retry_count = max(0, retry_count)
        self.retry_delay = max(0.1, retry_delay)
        self.socket = None
        self._codec = RconPacketCodec(self.MAX_PACKET_SIZE + 4, self.MIN_PACKET_SIZE)
        self._packet_id = 0
        self._connected = False
        self._authenticated = False

    def _validate_ip(self, ip: str) -> str:
        """
        Validate IP address format.
        
        Args:
            ip: IP address to validate
            
        Returns:
            Validated IP address
            
        Raises:
            ValueError: If IP address is invalid
        """
        if not ip or not isinstance(ip, str):
            raise ValueError("IP address must be a non-empty string")
        
        # Basic IP validation - allow hostnames too
        if not (ip.replace('.', '').replace(':', '').replace('-', '').replace('_', '').isalnum() or 
                ip in ('localhost', '127.0.0.1', '::1')):
            raise ValueError(f"Invalid IP address format: {ip}")
        
        return ip
    
    def _validate_port(self, port: int) -> int:
        """
        Validate port number.
        
        Args:
            port: Port number to validate
            
        Returns:
            Validated port number
            
        Raises:
            ValueError: If port is invalid
        """
        if not isinstance(port, int) or not (1 <= port <= 65535):
            raise ValueError(f"Port must be an integer between 1 and 65535, got: {port}")
        return port
    
    def _validate_command(self, command: str) -> str:
        """
        Validate and sanitize RCON command.
        
        Args:
            command: Command to validate
            
        Returns:
            Sanitized command
            
        Raises:
            ValueError: If command is invalid
        """
        return _validate_command(command, self.MAX_COMMAND_LENGTH)
    
    def _identify_password(self) -> str:
        """
        Identify RCON password from start parameters or INI file.
        
        Returns:
            The RCON password
            
        Raises:
            RconPasswordNotFoundError: If password cannot be found
        """
        # Try to get password from start parameters
        password = self._settings.get_start_param_value('ServerAdminPassword')
        
        if password:
            return password
        
        # Try to get password from GameUserSettings.ini
        password = self._settings.get_server_setting('ServerAdminPassword')
        
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
        port_str = self._settings.get_start_param_value('RCONPort')
        
        if port_str:
            return self._parse_port_value(port_str, "start parameters")
        
        # Try to get port from GameUserSettings.ini
        port_str = self._settings.get_server_setting('RCONPort')
        
        if port_str:
            return self._parse_port_value(port_str, "configuration")
            
        raise RconPortNotFoundError("Could not find RCON port in start parameters or configuration")

    def _parse_port_value(self, port_str: str, source: str) -> int:
        try:
            port = int(port_str)
            return self._validate_port(port)
        except (TypeError, ValueError) as exc:
            raise RconPortNotFoundError(f"Invalid port in {source}: {port_str}") from exc
    
    @staticmethod
    def _remaining(limit: float, deadline: Optional[float]) -> float:
        if deadline is None:
            return limit
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RconTimeoutError("RCON operation deadline expired")
        return min(limit, remaining)

    def _request(self, packet_type: int, body: str) -> tuple[int, bytes]:
        self._packet_id = self._packet_id % 0x7fffffff + 1
        return self._packet_id, self._codec.encode(self._packet_id, packet_type, body)

    def _receive_exact(self, num_bytes: int, deadline: Optional[float]) -> bytes:
        data = bytearray()
        while len(data) < num_bytes:
            self.socket.settimeout(self._remaining(self.read_timeout, deadline))
            chunk = self.socket.recv(num_bytes - len(data))
            if not chunk:
                raise RconConnectionError("Connection closed by remote host")
            data.extend(chunk)
        return bytes(data)

    def _receive_full_packet(self, deadline: Optional[float]) -> bytes:
        header = self._receive_exact(4, deadline)
        size, = struct.unpack("<I", header)
        if size < 10:
            raise RconPacketError(f"Invalid packet size: {size}")
        if size > self.MAX_PACKET_SIZE:
            raise RconPacketError(f"Packet size too large: {size}")
        return header + self._receive_exact(size, deadline)

    def _receive_response(self, deadline: Optional[float]) -> RconPacket:
        return self._codec.decode(self._receive_full_packet(deadline))

    def _authenticate(self, deadline: Optional[float]) -> None:
        packet_id, request = self._request(RconPacketTypes.AUTH, self.password)
        self.socket.settimeout(self._remaining(self.read_timeout, deadline))
        self.socket.sendall(request)
        response = self._receive_response(deadline)
        # Some servers precede AUTH_RESPONSE with one empty RESPONSE_VALUE.
        if (response.id, response.type, response.body) == (
            packet_id, RconPacketTypes.RESPONSE_VALUE, ""
        ):
            response = self._receive_response(deadline)
        if response.id == -1:
            raise RconAuthenticationError("RCON authentication failed: server returned -1 response ID")
        if (response.id, response.type) != (packet_id, RconPacketTypes.AUTH_RESPONSE):
            raise RconPacketError("Unexpected RCON authentication response")
        self._authenticated = True

    def connect(self, timeout: Optional[float] = None) -> None:
        """Open and authenticate a session; timeout limits each TCP connection attempt."""
        self._connect(self.connect_timeout if timeout is None else timeout, None)

    def _connect(self, timeout: float, deadline: Optional[float]) -> None:
        if self.is_connected():
            return
        for attempt in range(self.retry_count + 1):
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(self._remaining(timeout, deadline))
                self.socket.connect((self.server_ip, self.port))
                self._connected = True
                self._authenticate(deadline)
                return
            except (RconAuthenticationError, RconPacketError):
                self.close()
                raise
            except (OSError, RconConnectionError, RconTimeoutError) as exc:
                self.close()
                if attempt == self.retry_count:
                    if isinstance(exc, socket.timeout):
                        raise RconTimeoutError("RCON connection or authentication timed out") from exc
                    if isinstance(exc, OSError):
                        raise RconConnectionError(f"RCON connection failed: {exc}") from exc
                    raise
            time.sleep(self._remaining(self.retry_delay * 2**attempt, deadline))

    def execute_command(self, command: str, *, operation_timeout: Optional[float] = None) -> str:
        """Send once. An optional total budget covers connection, retries and the reply."""
        command = self._validate_command(command)
        deadline = None if operation_timeout is None else time.monotonic() + operation_timeout
        self._connect(self.connect_timeout, deadline)
        packet_id, request = self._request(RconPacketTypes.EXEC_COMMAND, command)
        self.socket.settimeout(self._remaining(self.read_timeout, deadline))
        # Once sendall starts, even an exception cannot establish how much arrived.
        try:
            self.socket.sendall(request)
            response = self._receive_response(deadline)
            if (response.id, response.type) != (packet_id, RconPacketTypes.RESPONSE_VALUE):
                raise RconPacketError("Unexpected RCON command response ID or type")
            return response.body
        except (socket.timeout, RconTimeoutError) as exc:
            self.close()
            raise RconUnconfirmedTimeoutError(f"Command delivery unconfirmed: {exc}") from exc
        except (OSError, RconConnectionError) as exc:
            self.close()
            raise RconUnconfirmedConnectionError(f"Command delivery unconfirmed: {exc}") from exc
        except RconPacketError as exc:
            self.close()
            raise RconUnconfirmedPacketError(f"Command delivery unconfirmed: {exc}") from exc

    def close(self) -> None:
        """Close the RCON connection and clean up resources."""
        self._connected = False
        self._authenticated = False
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass  # Ignore errors during cleanup
            finally:
                self.socket = None
    
    def is_connected(self) -> bool:
        """
        Check if the client is connected and authenticated.
        
        Returns:
            True if connected and authenticated, False otherwise
        """
        return self._connected and self._authenticated and self.socket is not None
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


def execute_rcon_command(
    command: str,
    server_ip: str = '127.0.0.1',
    *,
    settings: Optional[AsaSettings] = None,
    operation_timeout: Optional[float] = None,
) -> str:
    """
    Execute a single RCON command (convenience function).

    Args:
        command: The command to execute
        server_ip: Server IP address
        settings: Optional configuration source for password and port discovery
        
    Returns:
        The command response
    """
    normalized_command = _validate_command(command, RCON_MAX_COMMAND_LENGTH)
    settings = settings or AsaSettings()
    if server_ip == '127.0.0.1':
        port, password = settings.rcon_endpoint()
        client = RconClient(server_ip, port=port, password=password, settings=settings)
    else:
        client = RconClient(server_ip, settings=settings)
    with closing(client):
        return client.execute_command(normalized_command, operation_timeout=operation_timeout)


def _validate_command(command: str, max_length: int) -> str:
    if not command or not isinstance(command, str):
        raise ValueError("Command must be a non-empty string")

    command = command.strip()
    if len(command) > max_length:
        raise ValueError(f"Command too long: {len(command)} > {max_length}")

    command = ''.join(char for char in command if ord(char) >= 32 or char in '\t\n\r')
    if not command:
        raise ValueError("Command contains only invalid characters")
    return command
