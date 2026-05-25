
from flask import Flask, render_template, request
from flask_socketio import SocketIO
import pty
import os
import select
import threading

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

clients = {}

@app.route("/")
def home():
    return render_template("index.html")

@socketio.on("connect")
def connect():
    sid = request.sid

    pid, fd = pty.fork()

    if pid == 0:
        os.execvp("bash", ["bash"])

    clients[sid] = fd

    def read_and_forward():
        while True:
            try:
                rl, _, _ = select.select([fd], [], [], 0.1)
                if fd in rl:
                    data = os.read(fd, 1024).decode(errors="ignore")
                    socketio.emit("output", data, to=sid)
            except:
                break

    threading.Thread(target=read_and_forward, daemon=True).start()

@socketio.on("input")
def user_input(data):
    sid = request.sid
    fd = clients.get(sid)

    if fd:
        os.write(fd, data.encode())

@socketio.on("disconnect")
def disconnect():
    sid = request.sid
    fd = clients.get(sid)

    if fd:
        try:
            os.close(fd)
        except:
            pass

        del clients[sid]

if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        allow_unsafe_werkzeug=True
    )
