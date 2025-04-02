import logging.config
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
import random
from logging import INFO, ERROR, log, basicConfig, WARN
from colorama import Style, Fore, Back
import string

basicConfig(filename="log.ansi")
app = Flask(__name__)
socketio = SocketIO(app)

games = {}  # Stores active game sessions

def generate_game_id():
    return ''.join(random.choices(string.digits, k=6))

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/host')
def host():
    game_id = generate_game_id()
    games[game_id] = {'host': request.remote_addr, 'player': None}
    return render_template('host.html', game_id=game_id)

@socketio.on('host_game')
def host_game(data):
    """Handler for when the host establishes a WebSocket connection."""
    game_id = data.get('game_id')
    
    if game_id in games:
        games[game_id]['host_sid'] = request.sid  # Store host's socket ID
        join_room(game_id)  # Host joins the room
        emit('game_created', {'game_id': game_id}, room=request.sid)
        app.logger.log(INFO, Fore.GREEN + f"Host joined game id: {game_id}" + Style.RESET_ALL)
    else:
        emit('error', {'status': 'error', 'message': 'Invalid game ID'})
        app.logger.log(ERROR, Fore.RED + f"Failed to host game id: {game_id}" + Style.RESET_ALL)

@app.route('/join')
def join_page():
    return render_template('join.html')

@socketio.on('join_game')
def join_game(data):
    game_id = data.get('game_id')
    app.logger.log(INFO, Fore.GREEN + f"Attempting to join game id: {game_id}" + Style.RESET_ALL)
    if game_id in games and not games[game_id]['player']:
        games[game_id]['player'] = request.remote_addr
        join_room(game_id)
        emit('connected', {'status': 'connected'}, room=game_id)
        emit('start_game', {'status': 'start'}, room=game_id)
        app.logger.log(INFO, Fore.GREEN + f"Joined game id: {game_id}" + Style.RESET_ALL)
    else:
        emit('error', {'status': 'error', 'message': 'Invalid or full game'})
        app.logger.log(ERROR, Fore.RED + f"Failed to join game id: {game_id}" + Style.RESET_ALL)

@socketio.on('connect')
def handle_connect():
    pass

if __name__ == '__main__':
    socketio.run(app, debug=True)