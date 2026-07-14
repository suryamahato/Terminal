"""
Professional VPS Web Terminal
A standalone, production-ready web terminal emulator with full shell support.
"""

import os
import sys
import pty
import select
import subprocess
import threading
import logging
import struct
import fcntl
import termios
import signal
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, disconnect
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('terminal.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Flask configuration
app = Flask(__name__, template_folder='Templates', static_folder='Static')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-this-in-production')
app.config['JSON_SORT_KEYS'] = False

# SocketIO configuration with better defaults
socketio = SocketIO(
    app,
    cors_allowed_origins=os.getenv('CORS_ORIGINS', '*').split(','),
    async_mode='threading',
    ping_timeout=60,
    ping_interval=25,
    logger=False,
    engineio_logger=False,
    max_http_buffer_size=10000000
)

# Global clients dictionary
clients = {}
clients_lock = threading.Lock()


class TerminalSession:
    """Manages a single terminal session"""
    def __init__(self, sid):
        self.sid = sid
        self.pid = None
        self.fd = None
        self.active = True
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        self.reader_thread = None
        self.cleanup_lock = threading.Lock()
    
    def set_reader_thread(self, thread):
        """Store the reader thread reference"""
        self.reader_thread = thread
    
    def cleanup(self):
        """Clean up terminal session resources"""
        with self.cleanup_lock:
            if not self.active:
                return  # Already cleaned up
            
            self.active = False
            
            # Close file descriptor
            if self.fd is not None:
                try:
                    os.close(self.fd)
                except Exception as e:
                    logger.debug(f"Error closing fd for session {self.sid}: {e}")
                finally:
                    self.fd = None
            
            # Terminate process
            if self.pid is not None:
                try:
                    # Try graceful termination first
                    os.kill(self.pid, signal.SIGTERM)
                    # Give it a moment to terminate
                    time.sleep(0.1)
                    try:
                        # Check if process still exists and force kill if needed
                        os.kill(self.pid, 0)
                        os.kill(self.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass  # Process already terminated
                except ProcessLookupError:
                    pass  # Process already terminated
                except Exception as e:
                    logger.debug(f"Error killing process {self.pid}: {e}")
                finally:
                    self.pid = None


@app.route('/')
def home():
    """Serve the main terminal page"""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error rendering home page: {e}")
        return jsonify({'error': 'Failed to load terminal', 'details': str(e)}), 500


@app.route('/api/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'active_sessions': len(clients)
    }), 200


@app.route('/api/sessions')
def get_sessions():
    """Get active sessions (admin endpoint)"""
    with clients_lock:
        sessions_info = []
        for sid, session in clients.items():
            sessions_info.append({
                'sid': sid,
                'created_at': session.created_at.isoformat(),
                'last_activity': session.last_activity.isoformat(),
                'active': session.active
            })
    return jsonify(sessions_info), 200


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def server_error(error):
    """Handle server errors"""
    logger.error(f"Server error: {error}")
    return jsonify({'error': 'Internal server error'}), 500


@socketio.on('connect')
def on_connect():
    """Handle new client connection"""
    sid = request.sid
    logger.info(f"Client connected: {sid}")
    
    try:
        # Create a new PTY
        pid, fd = pty.fork()
        
        if pid == 0:
            # Child process - execute shell
            env = os.environ.copy()
            env['TERM'] = 'xterm-256color'
            
            # Use /bin/bash if available, fall back to /bin/sh
            shell = '/bin/bash' if os.path.exists('/bin/bash') else '/bin/sh'
            try:
                os.execvp(shell, [shell])
            except Exception as e:
                logger.error(f"Failed to execute shell: {e}")
                sys.exit(1)
        
        # Parent process - manage terminal
        session = TerminalSession(sid)
        session.pid = pid
        session.fd = fd
        
        # Set initial window size
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
        except Exception as e:
            logger.warning(f"Could not set initial terminal size: {e}")
        
        # Set non-blocking mode
        try:
            import fcntl as fcntl_module
            flags = fcntl_module.fcntl(fd, fcntl_module.F_GETFL)
            fcntl_module.fcntl(fd, fcntl_module.F_SETFL, flags | os.O_NONBLOCK)
        except Exception as e:
            logger.debug(f"Could not set non-blocking mode: {e}")
        
        with clients_lock:
            clients[sid] = session
        
        # Start thread to read from terminal and forward to client
        reader_thread = threading.Thread(
            target=read_and_forward,
            args=(sid, fd),
            daemon=True,
            name=f'reader-{sid}'
        )
        session.set_reader_thread(reader_thread)
        reader_thread.start()
        
        emit('connected', {
            'message': 'Terminal session started',
            'shell': os.getenv('SHELL', 'bash')
        })
        
    except Exception as e:
        logger.error(f"Error during connection: {e}", exc_info=True)
        emit('error', {'message': f'Failed to create terminal: {str(e)}'})
        disconnect()


def read_and_forward(sid, fd):
    """Read from terminal and forward output to client"""
    try:
        buffer_size = 4096
        while True:
            # Check if session is still active
            with clients_lock:
                if sid not in clients or not clients[sid].active:
                    break
            
            # Use select to check if data is available
            try:
                rl, _, _ = select.select([fd], [], [], 0.5)
            except (OSError, ValueError):
                # File descriptor might be closed
                break
            
            if fd in rl:
                try:
                    data = os.read(fd, buffer_size)
                    if data:
                        try:
                            # Decode with error handling
                            text_data = data.decode(errors='replace')
                            socketio.emit('output', text_data, to=sid)
                        except Exception as e:
                            logger.debug(f"Could not emit to {sid}: {e}")
                            break
                    else:
                        # EOF - terminal closed
                        try:
                            socketio.emit('closed', {'message': 'Terminal closed'}, to=sid)
                        except Exception as e:
                            logger.debug(f"Could not emit closed event to {sid}: {e}")
                        break
                except OSError:
                    # File descriptor closed or read error
                    break
                except Exception as e:
                    logger.debug(f"Error reading from terminal {sid}: {e}")
                    break
    except Exception as e:
        logger.error(f"Error in read_and_forward for {sid}: {e}", exc_info=True)
    finally:
        # Clean up session
        with clients_lock:
            if sid in clients:
                clients[sid].cleanup()
                del clients[sid]
        logger.info(f"Terminal session ended: {sid}")


@socketio.on('input')
def on_input(data):
    """Handle user input from client"""
    sid = request.sid
    
    try:
        if not isinstance(data, str):
            logger.warning(f"Invalid input type for {sid}: {type(data)}")
            return
        
        with clients_lock:
            if sid not in clients:
                logger.warning(f"Input received for non-existent session: {sid}")
                return
            session = clients[sid]
            if not session.active:
                logger.warning(f"Input received for inactive session: {sid}")
                return
            fd = session.fd
            session.last_activity = datetime.now()
        
        if fd is not None:
            try:
                # Encode input and write to terminal
                encoded_data = data.encode(errors='replace')
                os.write(fd, encoded_data)
            except OSError:
                logger.debug(f"Could not write to terminal {sid}: file descriptor may be closed")
            except Exception as e:
                logger.error(f"Error writing input for {sid}: {e}")
    except Exception as e:
        logger.error(f"Error in on_input for {sid}: {e}", exc_info=True)


@socketio.on('resize')
def on_resize(data):
    """Handle terminal resize events"""
    sid = request.sid
    
    try:
        if not isinstance(data, dict):
            logger.warning(f"Invalid resize data type for {sid}: {type(data)}")
            return
        
        try:
            cols = int(data.get('cols', 80))
            rows = int(data.get('rows', 24))
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid resize dimensions for {sid}: {e}")
            return
        
        # Validate dimensions
        if cols < 1 or cols > 500 or rows < 1 or rows > 500:
            logger.warning(f"Invalid resize dimensions for {sid}: {rows}x{cols}")
            return
        
        with clients_lock:
            if sid not in clients or not clients[sid].active:
                return
            fd = clients[sid].fd
        
        if fd is not None:
            try:
                # Set the PTY size
                fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
                logger.debug(f"Resized terminal {sid} to {rows}x{cols}")
            except (OSError, IOError) as e:
                logger.debug(f"Error resizing terminal for {sid}: {e}")
            except Exception as e:
                logger.error(f"Error resizing terminal for {sid}: {e}")
    except Exception as e:
        logger.error(f"Error processing resize for {sid}: {e}", exc_info=True)


@socketio.on('disconnect')
def on_disconnect():
    """Handle client disconnection"""
    sid = request.sid
    logger.info(f"Client disconnected: {sid}")
    
    try:
        with clients_lock:
            if sid in clients:
                clients[sid].cleanup()
                del clients[sid]
    except Exception as e:
        logger.error(f"Error during disconnect cleanup for {sid}: {e}", exc_info=True)


if __name__ == '__main__':
    host = os.getenv('HOST', '0.0.0.0')
    try:
        port = int(os.getenv('PORT', 5000))
    except ValueError:
        logger.warning("Invalid PORT value, using default 5000")
        port = 5000
    
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    logger.info(f"Starting Terminal server on {host}:{port}")
    logger.info(f"Debug mode: {debug}")
    logger.info(f"Active sessions: {len(clients)}")
    
    try:
        socketio.run(
            app,
            host=host,
            port=port,
            debug=debug,
            allow_unsafe_werkzeug=True,
            log_output=False
        )
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)
