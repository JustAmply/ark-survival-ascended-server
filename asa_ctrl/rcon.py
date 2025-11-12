"""
RCON (Remote Console) communication module for ASA Control.

Handles communication with the ARK server via RCON protocol.
"""

import os
import select
import socket
import struct
import time
from typing import NamedTuple, Optional

from .constants import RconPacketTypes
from .config import StartParamsHelper, IniConfigHelper
from .errors import (
    AsaCtrlError,
    RconPasswordNotFoundError,
    RconPortNotFoundError,
    RconAuthenticationError,
    RconConnectionError,
    RconPacketError,
    RconTimeoutError,
)


class RconPacket(NamedTuple):
    """RCON packet structure."""
    size: int
    id: int
    type: int
    body: str


class RconClient:
    """RCON client for communicating with ARK server."""
    
    # Configuration constants
    MAX_PACKET_SIZE = 4096  # Maximum RCON packet size
    MIN_PACKET_SIZE = 12    # Minimum packet size (header only)
    MAX_COMMAND_LENGTH = 1000  # Maximum command length
    DEFAULT_RETRY_COUNT = 3
    DEFAULT_RETRY_DELAY = 1.0
    
    def __init__(self, server_ip: str = '127.0.0.1', port: Optional[int] = None, password: Optional[str] = None,
                 connect_timeout: float = 30.0, read_timeout: float = 10.0, 
                 retry_count: int = DEFAULT_RETRY_COUNT, retry_delay: float = DEFAULT_RETRY_DELAY):
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
        self.port = self._validate_port(port) if port is not None else self._identify_port()
        self.password = password or self._identify_password()
        self.connect_timeout = max(1.0, connect_timeout)
        self.read_timeout = max(1.0, read_timeout) 
        self.retry_count = max(0, retry_count)
        self.retry_delay = max(0.1, retry_delay)
        self.socket = None
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
        if not command or not isinstance(command, str):
            raise ValueError("Command must be a non-empty string")
            
        # Strip whitespace and check length
        command = command.strip()
        if len(command) > self.MAX_COMMAND_LENGTH:
            raise ValueError(f"Command too long: {len(command)} > {self.MAX_COMMAND_LENGTH}")
            
        # Basic sanitization - remove null bytes and control characters
        command = ''.join(char for char in command if ord(char) >= 32 or char in '\t\n\r')
        
        if not command:
            raise ValueError("Command contains only invalid characters")
            
        return command
    
    def _validate_packet_data(self, data: bytes, expected_min_size: int = MIN_PACKET_SIZE) -> None:
        """
        Validate received packet data.
        
        Args:
            data: Raw packet data
            expected_min_size: Minimum expected packet size
            
        Raises:
            RconPacketError: If packet is invalid
        """
        if not data:
            raise RconPacketError("Received empty packet")
            
        if len(data) < expected_min_size:
            raise RconPacketError(f"Packet too small: {len(data)} < {expected_min_size}")
            
        if len(data) > self.MAX_PACKET_SIZE:
            raise RconPacketError(f"Packet too large: {len(data)} > {self.MAX_PACKET_SIZE}")
    
    def _with_retry(self, operation, *args, **kwargs):
        """
        Execute operation with retry logic.
        
        Args:
            operation: Function to execute
            *args: Positional arguments for operation
            **kwargs: Keyword arguments for operation
            
        Returns:
            Operation result
            
        Raises:
            Exception: Last exception if all retries fail
        """
        last_exception = None
        
        for attempt in range(self.retry_count + 1):
            try:
                return operation(*args, **kwargs)
            except (socket.timeout, socket.error, RconPacketError, RconConnectionError, RconTimeoutError) as e:
                last_exception = e
                if attempt < self.retry_count:
                    delay = self.retry_delay * (2 ** attempt)  # Exponential backoff
                    time.sleep(delay)
                    # Reset connection state for retry
                    self._connected = False
                    self._authenticated = False
                    if self.socket:
                        try:
                            self.socket.close()
                        except Exception:
                            pass
                        self.socket = None
                else:
                    break
        
        if last_exception:
            raise last_exception
    
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
            try:
                port = int(port_str)
                if not (1 <= port <= 65535):
                    raise ValueError(f"Port out of range: {port}")
                return port
            except ValueError as e:
                raise RconPortNotFoundError(f"Invalid port in start parameters: {port_str}") from e
        
        # Try to get port from GameUserSettings.ini
        port_str = IniConfigHelper.get_server_setting('RCONPort')
        
        if port_str:
            try:
                port = int(port_str)
                if not (1 <= port <= 65535):
                    raise ValueError(f"Port out of range: {port}")
                return port
            except ValueError as e:
                raise RconPortNotFoundError(f"Invalid port in configuration: {port_str}") from e
            
        raise RconPortNotFoundError("Could not find RCON port in start parameters or configuration")
    
    def _send_packet(self, data: str, packet_type: int) -> RconPacket:
        """
        Send an RCON packet and receive response.
        
        Args:
            data: The data to send
            packet_type: The packet type
            
        Returns:
            The response packet
            
        Raises:
            RconPacketError: If packet is malformed
            RconTimeoutError: If operation times out
            RconConnectionError: If connection fails
        """
        if not self.socket or not self._connected:
            raise RconConnectionError("Socket not connected")
        
        # Validate and encode data
        data = self._validate_command(data) if packet_type == RconPacketTypes.EXEC_COMMAND else data
        data_bytes = data.encode('utf-8')
        
        packet_size = 10 + len(data_bytes)
        packet_id = int(time.time()) % 2**31  # Use timestamp as packet ID for uniqueness
        
        # Pack the packet: size, id, type, body (null-terminated), extra null byte.
        # IDs and types must be encoded as signed integers because the RCON
        # protocol uses -1 as the authentication failure sentinel.
        packet_data = struct.pack('<Iii', packet_size, packet_id, packet_type)
        packet_data += data_bytes + b'\x00\x00'
        
        try:
            # Send with timeout
            self.socket.settimeout(self.read_timeout)
            self.socket.sendall(packet_data)

            combined_body = bytearray()
            response_count = 0
            response_type = None

            while True:
                try:
                    response_data = self._receive_full_packet()
                except RconTimeoutError:
                    if response_count:
                        break
                    raise

                # Validate response
                self._validate_packet_data(response_data)

                # Unpack response: size, id, type, then body
                if len(response_data) < 12:
                    raise RconPacketError(f"Response too short: {len(response_data)} bytes")

                # IDs and types are signed because the server returns -1 on auth failure.
                declared_size, response_id, current_type = struct.unpack('<Iii', response_data[:12])

                # Validate response packet structure
                if declared_size < 10:
                    raise RconPacketError(f"Invalid response size: {declared_size}")
                if declared_size != len(response_data) - 4:  # Size field doesn't include itself
                    raise RconPacketError(
                        f"Size mismatch: declared {declared_size}, actual {len(response_data) - 4}"
                    )

                # Handle authentication failure sentinel (-1 response ID)
                if packet_type == RconPacketTypes.AUTH and response_id == -1:
                    body = self._decode_packet_body(response_data[12:])
                    self._drain_socket()
                    return RconPacket(declared_size, response_id, current_type, body)

                if response_id != packet_id:
                    if response_count == 0:
                        self._drain_socket()
                        raise RconPacketError(
                            f"Unexpected response ID {response_id} for request {packet_id}"
                        )
                    # Different ID after valid packets indicates termination; stop accumulating.
                    break

                response_count += 1
                if response_type is None:
                    response_type = current_type

                body_bytes = self._extract_body_bytes(response_data[12:])
                if not body_bytes:
                    # Empty body marks termination for multi-packet responses.
                    break
                combined_body.extend(body_bytes)

                # For single-packet responses without an empty terminator, avoid blocking for
                # the full read timeout by checking if more data is immediately available.
                if not self._wait_for_additional_packet():
                    break

            body = combined_body.decode('utf-8', errors='replace')
            self._drain_socket()
            return RconPacket(10 + len(combined_body), packet_id, response_type or packet_type, body)

        except socket.timeout as e:
            raise RconTimeoutError(f"Packet operation timed out after {self.read_timeout}s") from e
        except socket.error as e:
            self._connected = False
            raise RconConnectionError(f"Socket error during packet operation: {e}") from e

    def _extract_body_bytes(self, body_data: bytes) -> bytes:
        """Extract body payload from raw packet data, removing terminators."""
        if body_data and body_data[-1:] == b'\x00':
            body_data = body_data[:-1]

        null_pos = body_data.find(b'\x00')
        if null_pos >= 0:
            body_data = body_data[:null_pos]

        return body_data

    def _decode_packet_body(self, body_data: bytes) -> str:
        """Decode packet body bytes into a UTF-8 string."""
        cleaned = self._extract_body_bytes(body_data)
        try:
            return cleaned.decode('utf-8', errors='replace')
        except UnicodeDecodeError:
            return cleaned.decode('utf-8', errors='ignore')

    def _drain_socket(self) -> None:
        """Drain any leftover data from the socket to avoid contaminating future reads."""
        if not self.socket:
            return

        try:
            # Switch to non-blocking mode to drain without waiting for new data.
            self.socket.setblocking(False)
            while True:
                try:
                    data = self.socket.recv(self.MAX_PACKET_SIZE)
                except BlockingIOError:
                    break
                if not data:
                    break
        except (socket.error, AttributeError):
            # Ignore errors while draining; the main operation has already succeeded.
            pass
        finally:
            try:
                self.socket.setblocking(True)
                self.socket.settimeout(self.read_timeout)
            except (socket.error, AttributeError):
                pass

    def _wait_for_additional_packet(self) -> bool:
        """Return True if another packet appears to be available shortly."""
        wait_time = min(0.2, self.read_timeout / 5)
        return self._socket_has_data(wait_time)

    def _socket_has_data(self, timeout: float) -> bool:
        """Check if the socket has data ready within the specified timeout."""
        if not self.socket:
            return False
        fileno = getattr(self.socket, 'fileno', None)
        if fileno is None or not callable(fileno):
            # Test doubles may not provide fileno(); assume data is ready to avoid hanging.
            return True
        try:
            ready, _, _ = select.select([self.socket], [], [], timeout)
            return bool(ready)
        except (OSError, ValueError):
            return False
        except TypeError:
            return True
    
    def _receive_full_packet(self) -> bytes:
        """
        Receive a complete RCON packet, handling partial reads.
        
        Returns:
            Complete packet data
            
        Raises:
            RconPacketError: If packet is invalid
            RconTimeoutError: If operation times out
        """
        # First, read the size field (4 bytes)
        try:
            size_data = self._receive_exact(4)
            packet_size = struct.unpack('<I', size_data)[0]
            
            # Validate size
            if packet_size < 10:
                raise RconPacketError(f"Invalid packet size: {packet_size}")
            if packet_size > self.MAX_PACKET_SIZE - 4:
                raise RconPacketError(f"Packet size too large: {packet_size}")
            
            # Read the rest of the packet
            remaining_data = self._receive_exact(packet_size)
            
            return size_data + remaining_data
            
        except socket.timeout as e:
            raise RconTimeoutError("Timeout receiving packet") from e
        except socket.error as e:
            self._connected = False
            raise RconConnectionError(f"Connection error receiving packet: {e}") from e
    
    def _receive_exact(self, num_bytes: int) -> bytes:
        """
        Receive exactly num_bytes from socket.
        
        Args:
            num_bytes: Number of bytes to receive
            
        Returns:
            Received data
            
        Raises:
            RconConnectionError: If connection is lost
            RconPacketError: If not enough data received
        """
        if self.socket is None:
            raise RconConnectionError("Socket not connected")
        data = b''
        try:
            while len(data) < num_bytes:
                chunk = self.socket.recv(num_bytes - len(data))
                if not chunk:
                    raise RconConnectionError("Connection closed by remote host")
                data += chunk
        except socket.timeout as e:
            # Normalize socket timeout to RconTimeoutError
            raise RconTimeoutError("Timeout while receiving data") from e
        except socket.error as e:
            # Mark as disconnected and raise a connection error
            self._connected = False
            raise RconConnectionError(f"Connection error while receiving data: {e}") from e
        return data
    
    def _authenticate(self) -> bool:
        """
        Authenticate with the RCON server.
        
        Returns:
            True if authentication successful, False otherwise
            
        Raises:
            RconPacketError: If authentication packet is malformed
            RconTimeoutError: If authentication times out
        """
        try:
            response = self._send_packet(self.password, RconPacketTypes.AUTH)
        except (RconPacketError, RconTimeoutError, RconConnectionError):
            self._authenticated = False
            raise

        if response.id == -1:
            self._authenticated = False
            raise RconAuthenticationError("RCON authentication failed: server returned -1 response ID")

        self._authenticated = True
        return True
    
    def connect(self, timeout: Optional[float] = None) -> None:
        """
        Connect to the RCON server and authenticate.

        Args:
            timeout: Timeout in seconds for establishing the connection (uses instance default if None)

        Raises:
            RconConnectionError: If connection fails
            RconAuthenticationError: If authentication fails
            RconTimeoutError: If connection times out
        """
        if self._connected and self._authenticated:
            return  # Already connected and authenticated
        
        connect_timeout = timeout if timeout is not None else self.connect_timeout
        
        def _connect_once():
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(connect_timeout)
            
            try:
                self.socket.connect((self.server_ip, self.port))
                self._connected = True
                
                if not self._authenticate():
                    raise RconAuthenticationError("RCON authentication failed")
                    
            except socket.timeout as exc:
                self.close()
                raise RconTimeoutError(
                    f"Timed out connecting to RCON server at {self.server_ip}:{self.port} "
                    f"after {connect_timeout}s"
                ) from exc
            except socket.gaierror as exc:
                self.close()
                raise RconConnectionError(
                    f"Failed to resolve hostname {self.server_ip}: {exc}"
                ) from exc
            except socket.error as exc:
                self.close()
                raise RconConnectionError(
                    f"Failed to connect to RCON server at {self.server_ip}:{self.port}: {exc}"
                ) from exc
        
        # Use retry logic for connection
        self._with_retry(_connect_once)
    
    def execute_command(self, command: str) -> str:
        """
        Execute an RCON command.
        
        Args:
            command: The command to execute
            
        Returns:
            The command response
            
        Raises:
            RconConnectionError: If not connected or connection fails
            RconPacketError: If packet is malformed
            RconTimeoutError: If command times out
            ValueError: If command is invalid
        """
        if not command or not isinstance(command, str):
            raise ValueError("Command must be a non-empty string")
        
        # Ensure we're connected and authenticated
        if not self._connected or not self._authenticated:
            self.connect()
        
        def _execute_once():
            response = self._send_packet(command, RconPacketTypes.EXEC_COMMAND)
            
            if response.type == RconPacketTypes.RESPONSE_VALUE:
                return response.body
            else:
                raise RconPacketError(f"Unexpected response type: {response.type}, expected {RconPacketTypes.RESPONSE_VALUE}")
        
        # Use retry logic for command execution
        result = self._with_retry(_execute_once)
        if result is None:
            raise RconPacketError("Empty response from RCON command")
        if not isinstance(result, str):
            result = str(result)
        return result
    
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
