import logging
from logging import ERROR, INFO, WARNING
from colorama import Fore, Back, Style
import random
import string
import os
from flask import Flask, render_template, request, send_from_directory
from flask_socketio import SocketIO, emit, join_room
from colorama import Fore, Style

logging.basicConfig(filename="log.ansi")
app = Flask(__name__)
socketio = SocketIO(app)

CLEAR_ALL = Style.RESET_ALL

games = {}  # Stores active game sessions
def load_boards(filename="boards.txt"):
    """Reads board configurations from a file and parses them into a dictionary."""
    game_boards = {}  # Stores all parsed boards

    with open(filename, "r") as file:
        lines = [line.strip() for line in file if line.strip()]  # Remove empty lines

    board_name = None
    board_grid = []
    connections = []
    parsing_board = False

    for line in lines:
        if line.startswith("START BOARD"):
            parts = line.split()
            if len(parts) < 3:
                app.logger.log(ERROR, Fore.RED + f"Invalid board definition: {line}" + CLEAR_ALL)
                continue

            board_name = parts[2]  # Extract board name
            board_grid = []  # Reset grid storage
            connections = []  # Reset connections
            parsing_board = True
            continue

        if line == "END BOARD":
            if board_name:
                nodes = {}
                for y, row in enumerate(board_grid):
                    for x, char in enumerate(row):
                        if char.isalpha():
                            nodes[char] = (x, y)

                parsed_connections = []
                for connection in connections:
                    node1, node2 = connection.split("-")
                    if node1 in nodes and node2 in nodes:
                        parsed_connections.append([nodes[node1], nodes[node2]])

                game_boards[board_name] = {"nodes": list(nodes.values()), "connections": parsed_connections}

            parsing_board = False
            board_name = None
            continue

        if parsing_board:
            if "-" in line and len(line) == 3:  
                connections.append(line)
            else:
                board_grid.append(line)

    return game_boards




# Load the boards at startup
game_boards = load_boards()

def generate_game_id():
    return ''.join(random.choices(string.digits, k=6))

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'templates'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')

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
            join_room(game_id)
        else:
            emit('error', {'status': 'error', 'message': 'Invalid board selection'})
    else:
        emit('error', {'status': 'error', 'message': 'Game not found or board already chosen'})

@app.route('/join')
def join_page():
    return render_template('join.html')


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
