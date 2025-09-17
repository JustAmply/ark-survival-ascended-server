"""
Enterprise REST API for ASA Control.

Provides REST API endpoints for remote management including:
* Configuration management
* Health monitoring
* Metrics collection
* RCON command execution
* Mod management
* Audit log access
"""

import json
import socket
import time
import hashlib
import hmac
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Dict, Any, Optional, List, Tuple
import threading

from .enterprise import (
    get_config_manager,
    get_security_manager,
    get_audit_logger,
    get_health_checker,
    get_metrics_collector
)
from .mods import ModDatabase
from .rcon import execute_rcon_command
from .logging_config import get_logger
from .errors import (
    AsaCtrlError,
    ConfigValidationError,
    SecurityViolationError,
    RconPasswordNotFoundError,
    RconAuthenticationError,
    RconPortNotFoundError
)


class APIAuthenticationError(AsaCtrlError):
    """API authentication error."""
    pass


class APIRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the enterprise API."""
    
    def __init__(self, *args, api_server=None, **kwargs):
        self.api_server = api_server
        self._log = get_logger(__name__)
        super().__init__(*args, **kwargs)
    
    def log_message(self, format, *args):
        """Override to use our logger instead of stderr."""
        self._log.info(f"{self.client_address[0]} - {format % args}")
    
    def _send_json_response(self, data: Dict[str, Any], status_code: int = 200) -> None:
        """Send JSON response."""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
        
        response_json = json.dumps(data, indent=2)
        self.wfile.write(response_json.encode('utf-8'))
    
    def _send_html_response(self, html: str, status_code: int = 200) -> None:
        """Send HTML response."""
        self.send_response(status_code)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        self.wfile.write(html.encode('utf-8'))
    
    def _send_error_response(self, message: str, status_code: int = 400) -> None:
        """Send error response."""
        error_data = {
            "error": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status_code": status_code
        }
        self._send_json_response(error_data, status_code)
    
    def _authenticate_request(self) -> bool:
        """Authenticate API request."""
        config_manager = get_config_manager()
        config = config_manager.get_config()
        
        if not config.api_auth_token:
            # No authentication required if no token is set
            return True
        
        # Check Authorization header
        auth_header = self.headers.get('Authorization')
        if not auth_header:
            return False
        
        if not auth_header.startswith('Bearer '):
            return False
        
        token = auth_header[7:]  # Remove 'Bearer ' prefix
        
        # Simple token comparison (in production, use more secure methods)
        if not hmac.compare_digest(token, config.api_auth_token):
            return False
        
        return True
    
    def _log_api_request(self, endpoint: str, method: str, success: bool) -> None:
        """Log API request for audit purposes."""
        audit_logger = get_audit_logger()
        audit_logger.log_event("api_request", {
            "endpoint": endpoint,
            "method": method,
            "client_ip": self.client_address[0],
            "user_agent": self.headers.get('User-Agent', 'unknown'),
            "success": success,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    
    def _parse_request_body(self) -> Dict[str, Any]:
        """Parse JSON request body."""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            return {}
        
        body = self.rfile.read(content_length)
        try:
            return json.loads(body.decode('utf-8'))
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in request body")
    
    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
    
    def do_GET(self):
        """Handle GET requests."""
        if not self._authenticate_request():
            self._send_error_response("Authentication required", 401)
            self._log_api_request(self.path, "GET", False)
            return
        
        try:
            self._handle_get_request()
            self._log_api_request(self.path, "GET", True)
        except Exception as e:
            self._log.error("GET request failed: %s", e)
            self._send_error_response(f"Internal server error: {e}", 500)
            self._log_api_request(self.path, "GET", False)
    
    def do_POST(self):
        """Handle POST requests."""
        if not self._authenticate_request():
            self._send_error_response("Authentication required", 401)
            self._log_api_request(self.path, "POST", False)
            return
        
        try:
            self._handle_post_request()
            self._log_api_request(self.path, "POST", True)
        except Exception as e:
            self._log.error("POST request failed: %s", e)
            self._send_error_response(f"Internal server error: {e}", 500)
            self._log_api_request(self.path, "POST", False)
    
    def _handle_get_request(self):
        """Route GET requests to appropriate handlers."""
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query_params = parse_qs(parsed_url.query)
        
        if path == '/':
            self._handle_root()
        elif path == '/dashboard':
            self._handle_dashboard()
        elif path == '/api/v1/status':
            self._handle_status()
        elif path == '/api/v1/health':
            self._handle_health()
        elif path == '/api/v1/config':
            self._handle_get_config()
        elif path == '/api/v1/metrics':
            self._handle_metrics()
        elif path == '/api/v1/mods':
            self._handle_get_mods(query_params)
        elif path == '/api/v1/audit':
            self._handle_get_audit(query_params)
        else:
            self._send_error_response("Endpoint not found", 404)
    
    def _handle_post_request(self):
        """Route POST requests to appropriate handlers."""
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        
        try:
            request_data = self._parse_request_body()
        except ValueError as e:
            self._send_error_response(str(e), 400)
            return
        
        if path == '/api/v1/config':
            self._handle_update_config(request_data)
        elif path == '/api/v1/rcon':
            self._handle_rcon_command(request_data)
        elif path == '/api/v1/mods':
            self._handle_mod_action(request_data)
        else:
            self._send_error_response("Endpoint not found", 404)
    
    def _handle_root(self):
        """Handle root endpoint - API documentation."""
        docs = {
            "name": "ASA Enterprise API",
            "version": "1.0.0",
            "description": "REST API for ARK: Survival Ascended server management",
            "web_dashboard": "/dashboard",
            "endpoints": {
                "GET /": "This documentation",
                "GET /dashboard": "Web management dashboard",
                "GET /api/v1/status": "Server status",
                "GET /api/v1/health": "Health check",
                "GET /api/v1/config": "Get configuration",
                "POST /api/v1/config": "Update configuration",
                "GET /api/v1/metrics": "System metrics",
                "GET /api/v1/mods": "List mods",
                "POST /api/v1/mods": "Manage mods",
                "POST /api/v1/rcon": "Execute RCON command",
                "GET /api/v1/audit": "Audit logs"
            },
            "authentication": "Bearer token in Authorization header (if configured)"
        }
        self._send_json_response(docs)
    
    def _handle_dashboard(self):
        """Handle dashboard endpoint - simple web interface."""
        config_manager = get_config_manager()
        config = config_manager.get_config()
        
        html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>ASA Enterprise Dashboard</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
                .container {{ max-width: 1200px; margin: 0 auto; }}
                .header {{ background: #333; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
                .card {{ background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }}
                .status {{ padding: 5px 10px; border-radius: 4px; color: white; font-weight: bold; }}
                .status.running {{ background-color: #28a745; }}
                .status.stopped {{ background-color: #dc3545; }}
                .status.warning {{ background-color: #ffc107; }}
                .metric {{ display: flex; justify-content: space-between; margin: 10px 0; }}
                .metric-label {{ font-weight: bold; }}
                .metric-value {{ color: #007bff; }}
                button {{ background-color: #007bff; color: white; border: none; padding: 10px 15px; border-radius: 4px; cursor: pointer; margin: 5px; }}
                button:hover {{ background-color: #0056b3; }}
                .refresh {{ float: right; }}
                pre {{ background: #f8f9fa; padding: 10px; border-radius: 4px; overflow-x: auto; }}
                .error {{ color: #dc3545; }}
                .success {{ color: #28a745; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🦕 ASA Enterprise Dashboard</h1>
                    <p>ARK: Survival Ascended Server Management Interface</p>
                    <button class="refresh" onclick="location.reload()">🔄 Refresh</button>
                </div>
                
                <div class="grid">
                    <div class="card">
                        <h3>📊 Server Status</h3>
                        <div class="metric">
                            <span class="metric-label">Server Name:</span>
                            <span class="metric-value">{config.server_name}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Max Players:</span>
                            <span class="metric-value">{config.max_players}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">API Status:</span>
                            <span class="status running">RUNNING</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Health Check:</span>
                            <span class="metric-value" id="health-status">Loading...</span>
                        </div>
                    </div>
                    
                    <div class="card">
                        <h3>🔧 Quick Actions</h3>
                        <button onclick="runHealthCheck()">🩺 Run Health Check</button>
                        <button onclick="collectMetrics()">📈 Collect Metrics</button>
                        <button onclick="listMods()">🎮 View Mods</button>
                        <button onclick="viewConfig()">⚙️ View Config</button>
                    </div>
                    
                    <div class="card">
                        <h3>📋 RCON Console</h3>
                        <input type="text" id="rcon-command" placeholder="Enter RCON command..." style="width: 70%; padding: 8px;">
                        <button onclick="executeRcon()">Execute</button>
                        <pre id="rcon-output" style="min-height: 100px;">RCON command output will appear here...</pre>
                    </div>
                </div>
                
                <div class="card">
                    <h3>📊 System Information</h3>
                    <div id="system-info">Loading system information...</div>
                </div>
            </div>
            
            <script>
                // Auto-refresh health status
                function updateHealthStatus() {{
                    fetch('/api/v1/health')
                        .then(response => response.json())
                        .then(data => {{
                            const status = data.status.toUpperCase();
                            const element = document.getElementById('health-status');
                            element.textContent = status;
                            element.className = 'status ' + (status === 'HEALTHY' ? 'running' : 'warning');
                        }})
                        .catch(error => {{
                            document.getElementById('health-status').textContent = 'ERROR';
                            document.getElementById('health-status').className = 'status stopped';
                        }});
                }}
                
                function runHealthCheck() {{
                    fetch('/api/v1/health')
                        .then(response => response.json())
                        .then(data => {{
                            document.getElementById('system-info').innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
                        }})
                        .catch(error => {{
                            document.getElementById('system-info').innerHTML = '<span class="error">Error: ' + error.message + '</span>';
                        }});
                }}
                
                function collectMetrics() {{
                    fetch('/api/v1/metrics')
                        .then(response => response.json())
                        .then(data => {{
                            document.getElementById('system-info').innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
                        }})
                        .catch(error => {{
                            document.getElementById('system-info').innerHTML = '<span class="error">Error: ' + error.message + '</span>';
                        }});
                }}
                
                function listMods() {{
                    fetch('/api/v1/mods')
                        .then(response => response.json())
                        .then(data => {{
                            document.getElementById('system-info').innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
                        }})
                        .catch(error => {{
                            document.getElementById('system-info').innerHTML = '<span class="error">Error: ' + error.message + '</span>';
                        }});
                }}
                
                function viewConfig() {{
                    fetch('/api/v1/config')
                        .then(response => response.json())
                        .then(data => {{
                            document.getElementById('system-info').innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
                        }})
                        .catch(error => {{
                            document.getElementById('system-info').innerHTML = '<span class="error">Error: ' + error.message + '</span>';
                        }});
                }}
                
                function executeRcon() {{
                    const command = document.getElementById('rcon-command').value;
                    if (!command) return;
                    
                    fetch('/api/v1/rcon', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json'
                        }},
                        body: JSON.stringify({{ command: command }})
                    }})
                    .then(response => response.json())
                    .then(data => {{
                        if (data.error) {{
                            document.getElementById('rcon-output').innerHTML = '<span class="error">Error: ' + data.error + '</span>';
                        }} else {{
                            document.getElementById('rcon-output').textContent = data.response;
                        }}
                    }})
                    .catch(error => {{
                        document.getElementById('rcon-output').innerHTML = '<span class="error">Error: ' + error.message + '</span>';
                    }});
                    
                    document.getElementById('rcon-command').value = '';
                }}
                
                // Enter key support for RCON
                document.getElementById('rcon-command').addEventListener('keypress', function(e) {{
                    if (e.key === 'Enter') {{
                        executeRcon();
                    }}
                }});
                
                // Initial load
                updateHealthStatus();
                runHealthCheck();
                
                // Auto-refresh health status every 30 seconds
                setInterval(updateHealthStatus, 30000);
            </script>
        </body>
        </html>
        """
        
        self._send_html_response(html)
    
    def _handle_status(self):
        """Handle server status endpoint."""
        config_manager = get_config_manager()
        config = config_manager.get_config()
        
        status = {
            "status": "running",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "server_name": config.server_name,
            "max_players": config.max_players,
            "api_version": "1.0.0"
        }
        self._send_json_response(status)
    
    def _handle_health(self):
        """Handle health check endpoint."""
        health_checker = get_health_checker()
        health = health_checker.check_system_health()
        self._send_json_response(health)
    
    def _handle_get_config(self):
        """Handle get configuration endpoint."""
        config_manager = get_config_manager()
        config = config_manager.get_config()
        
        # Convert to dict and hide sensitive data
        config_dict = config.__dict__.copy()
        for key in config_dict:
            if 'password' in key.lower() or 'token' in key.lower():
                config_dict[key] = "***HIDDEN***" if config_dict[key] else None
        
        self._send_json_response({
            "config": config_dict,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    
    def _handle_update_config(self, request_data: Dict[str, Any]):
        """Handle update configuration endpoint."""
        if 'updates' not in request_data:
            self._send_error_response("Missing 'updates' field", 400)
            return
        
        try:
            config_manager = get_config_manager()
            config_manager.update_config(request_data['updates'])
            
            self._send_json_response({
                "message": "Configuration updated successfully",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        except ConfigValidationError as e:
            self._send_error_response(f"Configuration validation error: {e}", 400)
    
    def _handle_metrics(self):
        """Handle metrics endpoint."""
        metrics_collector = get_metrics_collector()
        metrics = metrics_collector.collect_metrics()
        self._send_json_response(metrics)
    
    def _handle_get_mods(self, query_params: Dict[str, List[str]]):
        """Handle get mods endpoint."""
        enabled_only = 'enabled_only' in query_params
        
        db = ModDatabase.get_instance()
        if enabled_only:
            mods = db.get_enabled_mods()
        else:
            mods = db.get_all_mods()
        
        mod_list = [
            {
                "mod_id": mod.mod_id,
                "name": mod.name,
                "enabled": mod.enabled,
                "added_at": mod.added_at
            }
            for mod in mods
        ]
        
        self._send_json_response({
            "mods": mod_list,
            "count": len(mod_list),
            "enabled_only": enabled_only,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    
    def _handle_mod_action(self, request_data: Dict[str, Any]):
        """Handle mod management actions."""
        action = request_data.get('action')
        mod_id = request_data.get('mod_id')
        
        if not action:
            self._send_error_response("Missing 'action' field", 400)
            return
        
        if not mod_id:
            self._send_error_response("Missing 'mod_id' field", 400)
            return
        
        try:
            mod_id = int(mod_id)
        except ValueError:
            self._send_error_response("Invalid mod_id - must be integer", 400)
            return
        
        db = ModDatabase.get_instance()
        
        try:
            if action == 'enable':
                db.enable_mod(mod_id)
                message = f"Mod {mod_id} enabled successfully"
            elif action == 'disable':
                success = db.disable_mod(mod_id)
                if success:
                    message = f"Mod {mod_id} disabled successfully"
                else:
                    message = f"Mod {mod_id} was not enabled"
            else:
                self._send_error_response(f"Unknown action: {action}", 400)
                return
            
            self._send_json_response({
                "message": message,
                "mod_id": mod_id,
                "action": action,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
        except Exception as e:
            self._send_error_response(f"Mod action failed: {e}", 400)
    
    def _handle_rcon_command(self, request_data: Dict[str, Any]):
        """Handle RCON command execution."""
        command = request_data.get('command')
        
        if not command:
            self._send_error_response("Missing 'command' field", 400)
            return
        
        try:
            # Security checks
            security_manager = get_security_manager()
            client_ip = self.client_address[0]
            
            if not security_manager.check_rcon_access(client_ip):
                self._send_error_response("RCON access denied", 403)
                return
            
            if not security_manager.check_rate_limit(client_ip):
                self._send_error_response("Rate limit exceeded", 429)
                return
            
            if not security_manager.validate_input(command):
                self._send_error_response("Command blocked by security policy", 403)
                return
            
            # Execute command
            response = execute_rcon_command(command)
            
            # Log the command
            audit_logger = get_audit_logger()
            audit_logger.log_admin_action("rcon_command_api", {
                "command": command,
                "client_ip": client_ip,
                "response_length": len(response)
            })
            
            self._send_json_response({
                "command": command,
                "response": response,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
        except (RconPasswordNotFoundError, RconAuthenticationError, RconPortNotFoundError) as e:
            self._send_error_response(f"RCON error: {e}", 500)
        except SecurityViolationError as e:
            self._send_error_response(f"Security violation: {e}", 403)
        except Exception as e:
            self._send_error_response(f"Command execution failed: {e}", 500)
    
    def _handle_get_audit(self, query_params: Dict[str, List[str]]):
        """Handle audit log retrieval."""
        # Simple implementation - read recent audit log entries
        limit = 100
        if 'limit' in query_params:
            try:
                limit = min(int(query_params['limit'][0]), 1000)  # Max 1000 entries
            except ValueError:
                pass
        
        try:
            audit_logger = get_audit_logger()
            
            # Read the audit log file
            if audit_logger.log_path.exists():
                with open(audit_logger.log_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                # Get the last N lines
                recent_lines = lines[-limit:] if len(lines) > limit else lines
                
                # Parse JSON entries
                entries = []
                for line in recent_lines:
                    try:
                        entry = json.loads(line.strip())
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue
                
                self._send_json_response({
                    "audit_entries": entries,
                    "count": len(entries),
                    "limit": limit,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            else:
                self._send_json_response({
                    "audit_entries": [],
                    "count": 0,
                    "limit": limit,
                    "message": "No audit log file found",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                
        except Exception as e:
            self._send_error_response(f"Failed to retrieve audit logs: {e}", 500)


class EnterpriseAPIServer:
    """Enterprise REST API server."""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = port
        self.server: Optional[HTTPServer] = None
        self._log = get_logger(__name__)
        self._running = False
        self._thread: Optional[threading.Thread] = None
    
    def start(self) -> None:
        """Start the API server."""
        if self._running:
            raise RuntimeError("Server is already running")
        
        # Create request handler class with reference to this server
        def handler_factory(*args, **kwargs):
            return APIRequestHandler(*args, api_server=self, **kwargs)
        
        try:
            self.server = HTTPServer((self.host, self.port), handler_factory)
            self._running = True
            
            self._log.info("Starting Enterprise API server on %s:%d", self.host, self.port)
            
            # Run server in separate thread
            self._thread = threading.Thread(target=self._run_server, daemon=True)
            self._thread.start()
            
        except Exception as e:
            self._log.error("Failed to start API server: %s", e)
            self._running = False
            raise
    
    def _run_server(self) -> None:
        """Run the server loop."""
        try:
            self.server.serve_forever()
        except Exception as e:
            self._log.error("API server error: %s", e)
        finally:
            self._running = False
    
    def stop(self) -> None:
        """Stop the API server."""
        if not self._running:
            return
        
        self._log.info("Stopping Enterprise API server")
        self._running = False
        
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
    
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._running


# Global API server instance
_api_server: Optional[EnterpriseAPIServer] = None


def get_api_server() -> EnterpriseAPIServer:
    """Get the global API server instance."""
    global _api_server
    if _api_server is None:
        config_manager = get_config_manager()
        config = config_manager.get_config()
        _api_server = EnterpriseAPIServer(port=config.api_port)
    return _api_server


def start_api_server() -> None:
    """Start the enterprise API server if enabled."""
    config_manager = get_config_manager()
    config = config_manager.get_config()
    
    if config.api_enabled:
        api_server = get_api_server()
        api_server.start()
    else:
        logger = get_logger(__name__)
        logger.info("Enterprise API server is disabled in configuration")


def stop_api_server() -> None:
    """Stop the enterprise API server."""
    global _api_server
    if _api_server:
        _api_server.stop()
        _api_server = None