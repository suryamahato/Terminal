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
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, disconnect
from dotenv import load_dotenv
import signal

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
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-this-in-production')
app.config['JSON_SORT_KEYS'] = False

# SocketIO configuration
socketio = SocketIO(
    app,
    cors_allowed_origins=os.getenv('CORS_ORIGINS', '*').split(','),
    async_mode='threading',
    ping_timeout=60,
    ping_interval=25,
    logger=True,
    engineio_logger=True
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
    
    def cleanup(self):
        """Clean up terminal session resources"""
        self.active = False
        if self.fd is not None:
            try:
                os.close(self.fd)
            except Exception as e:
                logger.error(f"Error closing fd for session {self.sid}: {e}")
        
        if self.pid is not None:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except Exception as e:
                logger.error(f"Error killing process {self.pid}: {e}")


@app.route('/')
def home():
    """Serve the main terminal page"""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error rendering home page: {e}")
        return jsonify({'error': 'Failed to load terminal'}), 500


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
            os.execvp(shell, [shell])
        
        # Parent process - manage terminal
        session = TerminalSession(sid)
        session.pid = pid
        session.fd = fd
        
        with clients_lock:
            clients[sid] = session
        
        # Start thread to read from terminal and forward to client
        reader_thread = threading.Thread(
            target=read_and_forward,
            args=(sid, fd),
            daemon=True,
            name=f'reader-{sid}'
        )
        reader_thread.start()
        
        emit('connected', {
            'message': 'Terminal session started',
            'shell': os.getenv('SHELL', 'bash')
        })
        
    except Exception as e:
        logger.error(f"Error during connection: {e}")
        emit('error', {'message': f'Failed to create terminal: {str(e)}'})
        disconnect()


def read_and_forward(sid, fd):
    """Read from terminal and forward output to client"""
    try:
        while True:
            with clients_lock:
                if sid not in clients or not clients[sid].active:
                    break
            
            # Use select to check if data is available
            rl, _, _ = select.select([fd], [], [], 0.1)
            
            if fd in rl:
                try:
                    data = os.read(fd, 4096)
                    if data:
                        socketio.emit('output', data.decode(errors='replace'), to=sid)
                    else:
                        # EOF - terminal closed
                        socketio.emit('closed', {'message': 'Terminal closed'}, to=sid)
                        break
                except OSError:
                    break
    except Exception as e:
        logger.error(f"Error in read_and_forward for {sid}: {e}")
    finally:
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
        with clients_lock:
            if sid not in clients:
                logger.warning(f"Input received for non-existent session: {sid}")
                return
            session = clients[sid]
            fd = session.fd
            session.last_activity = datetime.now()
        
        if fd is not None:
            os.write(fd, data.encode(errors='replace'))
    except Exception as e:
        logger.error(f"Error writing input for {sid}: {e}")


@socketio.on('resize')
def on_resize(data):
    """Handle terminal resize events"""
    sid = request.sid
    
    try:
        cols = int(data.get('cols', 80))
        rows = int(data.get('rows', 24))
        
        with clients_lock:
            if sid in clients:
                fd = clients[sid].fd
            else:
                return
        
        if fd is not None:
            # Set the PTY size
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
    except Exception as e:
        logger.error(f"Error resizing terminal for {sid}: {e}")


@socketio.on('disconnect')
def on_disconnect():
    """Handle client disconnection"""
    sid = request.sid
    logger.info(f"Client disconnected: {sid}")
    
    with clients_lock:
        if sid in clients:
            clients[sid].cleanup()
            del clients[sid]


if __name__ == '__main__':
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    logger.info(f"Starting Terminal server on {host}:{port}")
    logger.info(f"Debug mode: {debug}")
    
    socketio.run(
        app,
        host=host,
        port=port,
        debug=debug,
        allow_unsafe_werkzeug=True,
        log_output=True
    )
