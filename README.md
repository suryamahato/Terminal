# VPS Web Terminal

A professional, production-ready web terminal emulator for remote command execution through a browser. Perfect for managing VPS instances, cloud servers, and local systems remotely.

## Features

✨ **Full Terminal Emulation**
- Complete bash/shell support with all standard commands
- Real-time bidirectional communication via WebSocket
- Terminal resizing and proper PTY handling
- Full xterm color support

🛡️ **Production Ready**
- Robust error handling and recovery
- Automatic reconnection with exponential backoff
- Thread-safe session management
- Comprehensive logging

🎨 **Modern UI**
- Dark theme optimized for terminal work
- Responsive design for all screen sizes
- Real-time connection status indicator
- Smooth animations and visual feedback

## Installation

### Prerequisites
- Python 3.7+
- pip (Python package manager)

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/suryamahato/Terminal.git
   cd Terminal
   ```

2. **Create virtual environment** (recommended)
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env and set your configuration
   ```

5. **Run the server**
   ```bash
   python app.py
   ```

   The terminal will be available at `http://localhost:5000`

## Configuration

Edit the `.env` file to customize:

```env
# Server Settings
HOST=0.0.0.0
PORT=5000
DEBUG=False

# Security
SECRET_KEY=your-super-secret-key-change-this-in-production

# CORS Settings (comma-separated origins)
CORS_ORIGINS=*

# Logging
LOG_LEVEL=INFO

# Shell
SHELL=/bin/bash
```

## Usage

1. Open your browser and navigate to the server URL
2. Wait for the terminal to initialize
3. Start typing commands just like in a local terminal
4. Monitor the connection status indicator in the top bar

### Keyboard Shortcuts
- `Ctrl+C` - Interrupt current process
- `Ctrl+L` - Clear screen
- `Ctrl+D` - Exit shell

## API Endpoints

### Health Check
```
GET /api/health
```

Returns:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T00:00:00.000000",
  "active_sessions": 1
}
```

### Active Sessions
```
GET /api/sessions
```

Returns array of active session information.

## Socket.IO Events

### Client → Server
- `input` - Send terminal input
- `resize` - Terminal size changed

### Server → Client
- `connected` - Session established
- `output` - Terminal output data
- `closed` - Terminal session closed
- `error` - Error message

## Troubleshooting

### Terminal won't connect
- Check if the server is running: `python app.py`
- Verify the URL is correct
- Check browser console for errors (F12)
- Ensure firewall allows connections to the port

### Commands not executing
- Check that you have typing cursor in the terminal
- Try pressing Enter after typing a command
- Check server logs for errors

### Terminal disconnects frequently
- Check network stability
- Verify `ping_timeout` and `ping_interval` in `.env`
- Check server resources (CPU, memory)

## Performance Tips

- Use modern browsers (Chrome, Firefox, Safari, Edge)
- Ensure stable network connection
- For large terminal sessions, increase `scrollback` value in HTML

## Security Notes

⚠️ **Important**: This terminal has full shell access. Before deployment:

1. Change `SECRET_KEY` in `.env` to a strong random value
2. Restrict `CORS_ORIGINS` to trusted domains
3. Use HTTPS/WSS in production
4. Implement authentication mechanism
5. Run with least privileged user
6. Monitor access logs

## Deployment

### Using Gunicorn (Production)
```bash
gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
```

### Using Docker
```dockerfile
FROM python:3.11
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "app.py"]
```

## Logging

Logs are written to `terminal.log` and console output. Configure log level in `.env`:
- `DEBUG` - Detailed debugging information
- `INFO` - General information (default)
- `WARNING` - Warning messages
- `ERROR` - Error messages only

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is open source and available under the MIT License.

## Support

For issues and questions:
1. Check the troubleshooting section
2. Review server logs in `terminal.log`
3. Open an issue on GitHub

---

Made with ❤️ for developers who need remote terminal access
