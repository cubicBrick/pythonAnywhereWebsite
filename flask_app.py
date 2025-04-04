import os
import logging
import random
import string
from logging import ERROR
from flask import Flask, render_template, request, jsonify, send_from_directory
from colorama import Fore, Style
import pusher
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Initialize Pusher
pusher_client = pusher.Pusher(
    app_id=os.getenv("PUSHER_APP_ID"),
    key=os.getenv("PUSHER_KEY"),
    secret=os.getenv("PUSHER_SECRET"),
    cluster=os.getenv("PUSHER_CLUSTER"),
    ssl=True
)

logging.basicConfig(filename="log.ansi")

games = {}  # Stores active game sessions

def load_boards(filename=os.path.join(app.root_path, "boards.txt")):
    game_boards = {}
    with open(filename, "r") as file:
        lines = [line.strip() for line in file if line.strip()]

    board_name, board_grid, connections = None, [], []
    parsing_board = False

    for line in lines:
        if line.startswith("START BOARD"):
            parts = line.split()
            if len(parts) < 3:
                app.logger.log(ERROR, Fore.RED + f"Invalid board definition: {line}" + Style.RESET_ALL)
                continue
            board_name = parts[2]
            board_grid, connections = [], []
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

                game_boards[board_name] = {
                    "nodes": list(nodes.values()),
                    "connections": parsed_connections
                }

            parsing_board = False
            board_name = None
            continue

        if parsing_board:
            if "-" in line and len(line) == 3:
                connections.append(line)
            else:
                board_grid.append(line)

    return game_boards

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
    game_id = generate_game_id()
    games[game_id] = {'host': request.remote_addr, 'player': None, 'board': None}
    return render_template('host.html', game_id=game_id, boards=game_boards)

@app.route('/select_board', methods=['POST'])
def select_board():
    data = request.get_json()
    game_id = data.get('game_id')
    board_name = data.get('board')

    if game_id in games and board_name in game_boards:
        games[game_id]['board'] = board_name
        pusher_client.trigger(f'game-{game_id}', 'board_selected', {
            'game_id': game_id,
            'board': board_name
        })
        return '', 200
    return jsonify({'error': 'Invalid game or board'}), 400

@app.route('/join')
def join_page():
    return render_template('join.html')

@app.route('/join_game', methods=['POST'])
def join_game():
    data = request.get_json()
    game_id = data.get('game_id')

    if game_id in games and games[game_id]['player'] is None and games[game_id]['board']:
        games[game_id]['player'] = request.remote_addr
        pusher_client.trigger(f'game-{game_id}', 'connected', {'status': 'connected'})
        pusher_client.trigger(f'game-{game_id}', 'start_game', {'status': 'start'})
        app.logger.info(Fore.GREEN + f"Player joined game {game_id}" + Style.RESET_ALL)
        return '', 200
    return jsonify({'error': 'Invalid or full game'}), 400
@app.route("/pusher/auth", methods=["POST"])
def pusher_auth():
    channel = request.form['channel_name']
    socket_id = request.form['socket_id']

    # Optional: Get user ID from session or cookie
    user_id = request.cookies.get("user_id", "anonymous")

    auth = pusher_client.authenticate(
        channel=channel,
        socket_id=socket_id,
        custom_data={"user_id": user_id}
    )

    return jsonify(auth)
if __name__ == '__main__':
    app.run(debug=True)
