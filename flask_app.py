import logging
import random
import string
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
from colorama import Fore, Style

app = Flask(__name__)
socketio = SocketIO(app)

games = {}  # Stores active game sessions
game_boards = {
    "board1": {"nodes": [(0, 0), (1, 1), (2, 2)], "connections": [[(0, 0), (1, 1)], [(1, 1), (2, 2)]]},
    "board2": {"nodes": [(0, 2), (1, 3), (2, 4)], "connections": [[(0, 2), (1, 3)], [(1, 3), (2, 4)]]}
}  # Example boards

def generate_game_id():
    return ''.join(random.choices(string.digits, k=6))

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/host')
def host():
    """Generate game ID but do not send it to the frontend until board is chosen."""
    game_id = generate_game_id()
    games[game_id] = {'host': request.remote_addr, 'player': None, 'board': None}
    return render_template('host.html', game_id=game_id, boards=game_boards)  # Game ID is greyed out

@socketio.on('select_board')
def select_board(data):
    """Handles board selection and reveals game ID."""
    game_id = data.get('game_id')
    board_key = data.get('board')

    if game_id in games and games[game_id]['board'] is None:
        if board_key in game_boards:
            games[game_id]['board'] = game_boards[board_key]
            emit('board_selected', {'game_id': game_id, 'board': board_key}, room=request.sid)
            app.logger.info(Fore.BLUE + f"Board selected for game {game_id}: {board_key}" + Style.RESET_ALL)
        else:
            emit('error', {'status': 'error', 'message': 'Invalid board selection'})
    else:
        emit('error', {'status': 'error', 'message': 'Game not found or board already chosen'})

@socketio.on('join_game')
def join_game(data):
    """Allows a player to join only after board selection."""
    game_id = data.get('game_id')

    if game_id in games and games[game_id]['player'] is None and games[game_id]['board']:
        games[game_id]['player'] = request.remote_addr
        join_room(game_id)
        emit('connected', {'status': 'connected'}, room=game_id)
        emit('start_game', {'status': 'start'}, room=game_id)
        app.logger.info(Fore.GREEN + f"Player joined game {game_id}" + Style.RESET_ALL)
    else:
        emit('error', {'status': 'error', 'message': 'Invalid or full game'})

if __name__ == '__main__':
    socketio.run(app, debug=True)
