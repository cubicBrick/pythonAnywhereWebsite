import logging
from logging import ERROR, INFO, WARNING
from colorama import Fore, Back, Style
import random
import string
import os
from flask import Flask, render_template, request, send_from_directory
from flask_socketio import SocketIO, emit, join_room
from colorama import Fore, Style
from functools import wraps

logging.basicConfig(filename="log.ansi", format="%(asctime)s - %(levelname)s: %(message)s", level=INFO)
app = Flask(__name__)
socketio = SocketIO(app)
logging.getLogger('werkzeug').setLevel(logging.WARNING)
CLEAR_ALL = Style.RESET_ALL

games = {}  # Stores active game sessions

# Save original socketio.on
_original_on = socketio.on
def auto_logging_on(event, *args, **kwargs):
    def decorator(f):
        @wraps(f)
        def wrapped(*f_args, **f_kwargs):
            app.logger.info(
                Fore.CYAN + f"RECEIVE <- Event: {event}, Args: {f_args}, Kwargs: {f_kwargs}" + Style.RESET_ALL
            )
            return f(*f_args, **f_kwargs)
        return _original_on(event, *args, **kwargs)(wrapped)
    return decorator
socketio.on = auto_logging_on
_original_emit = socketio.emit
def auto_logging_emit(event, *args, **kwargs):
    app.logger.info(
        Fore.MAGENTA + f"SEND    -> Event: {event}, Args: {args}, Kwargs: {kwargs}" + Style.RESET_ALL
    )
    return _original_emit(event, *args, **kwargs)
socketio.emit = auto_logging_emit

app.logger.info(Fore.YELLOW + "Flask app started" + Style.RESET_ALL)

def load_boards(filename=os.path.join(app.root_path, "boards.txt")):
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
                app.logger.log(
                    ERROR, Fore.RED + f"Invalid board definition: {line}" + CLEAR_ALL
                )
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

                game_boards[board_name] = {
                    "nodes": list(nodes.values()),
                    "connections": parsed_connections,
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

# Load the boards at startup
game_boards = load_boards()

def generate_game_id():
    return "".join(random.choices(string.digits, k=6))

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/moon")
def moon():
    return render_template("index.html")

@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "templates"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )

@app.route("/host")
def host():
    """Generate game ID but do not send it to the frontend until board is chosen."""
    game_id = generate_game_id()
    games[game_id] = {"host": request.remote_addr, "player": None, "board": None}
    return render_template(
        "host.html", game_id=game_id, boards=game_boards
    )

@app.route("/disconnected")
def disconnected():
    return render_template("disconnected.html")

@socketio.on("select_board")
def select_board(data):
    """Handles board selection and reveals game ID."""
    game_id = data.get("game_id")
    board_key = data.get("board")

    if game_id in games and games[game_id]["board"] is None:
        if board_key in game_boards:
            games[game_id]["board"] = game_boards[board_key]
            join_room(game_id)
            emit(
                "board_selected", {"game_id": game_id, "board": board_key}, room=game_id
            )
            games[game_id]["host"] = request.sid
            games[game_id]["cards_host"] = []
            games[game_id]["cards_player"] = []
            app.logger.info(
                Fore.BLUE
                + f"{game_id} - Board {board_key} selected"
                + Style.RESET_ALL
            )
        else:
            emit("error", {"status": "error", "message": "Invalid board selection"})
    else:
        emit(
            "error",
            {"status": "error", "message": "Game not found or board already chosen"},
        )

@app.route("/join")
def join_page():
    return render_template("join.html")

@socketio.on("join_game")
def join_game(data):
    """Allows a player to join only after board selection."""
    game_id = data.get("game_id")

    if (
        game_id in games
        and games[game_id]["player"] is None
        and games[game_id]["board"]
    ):
        games[game_id]["player"] = request.sid
        join_room(game_id)
        app.logger.info(Fore.GREEN + f"{game_id} - Player joined game" + Style.RESET_ALL)
        emit("connected", {"status": "connected"}, room=game_id)

        # Get the board data for the game
        board_data = games[game_id]["board"]

        # Send start_game along with board data
        emit("start_game", {"status": "start", "board": board_data}, room=game_id)
        
        for _ in range(3):
            games[game_id]["cards_host"].append(random.randint(0, 7))
        app.logger.info(f"{game_id} - Host got cards: {games[game_id]['cards_host']}")
        emit(
            "update_cards",
            {
                "first": games[game_id]["cards_host"][0],
                "second": games[game_id]["cards_host"][1],
                "third": games[game_id]["cards_host"][2],
            },
            room=games[game_id]["host"]
        )
        
        for _ in range(3):
            games[game_id]["cards_player"].append(random.randint(0, 7))
        app.logger.info(f"{game_id} - Player got cards: {games[game_id]['cards_player']}")
        emit(
            "update_cards",
            {
                "first": games[game_id]["cards_player"][0],
                "second": games[game_id]["cards_player"][1],
                "third": games[game_id]["cards_player"][2],
            },
            room=games[game_id]["player"]
        )
    else:
        emit("error", {"status": "error", "message": "Invalid or full game"})

# TODO: Add a function to handle the scoring keeping track of cards played where
# SCORING: same type cards connected: 1 pt
# SCORING: two cards whose numbers differ 4, mod 8 (example, 0 and 4): 2 pts
# SCORING: chains of cards connected, where each card is one more than the previous one mod 8, (example, 5, 6, 7, 0, 1): 1 pt per card
# SCORING: chains of cards connected, where each card is one less than the previous one mod 8, (example, 1, 0, 7, 6): 1 pt per card
# SCORING IMPORTANT: One card may be part of many different scoring mechanisms
# SCORING IMPORTANT: Count them all as long as they are different in some way (ex: chain goes different way)
# SCORING VERY IMPORTANT: Do not count mechanisms that the newly placed card is not part of (ex: pair that does not contain the newly placed card)
# KEEPING TRACK OF CARDS: List of cards with their coordinates (x, y) and the card number

@socketio.on("play_card")
def play_card(data):
    game_id = data.get("game_id")
    if(game_id in games):
        if request.sid == games[game_id]["host"]:
            card = int(data.get("card"))
            if card >= 0 and card < len(games[game_id]["cards_host"]):
                oldcard = games[game_id]["cards_host"][card]
                newCard = random.randint(0, 7)
                games[game_id]["cards_host"][card] = newCard
                emit("change_card", {"card": newCard, "pos": card}, room=games[game_id]["host"])
                emit(
                    "played",
                    {
                        "status": "good",
                        "card": oldcard,
                        "player": "host",
                        "x" : data.get("x"),
                        "y" : data.get("y"),
                    },
                    room=game_id,
                )
            else:
                emit(
                    "error",
                    {"status": "error", "message": "Invalid card played"},
                    room=request.sid,
                )
        elif request.sid == games[game_id]["player"]:
            card = int(data.get("card"))
            if card >= 0 and card < len(games[game_id]["cards_player"]):
                oldcard = games[game_id]["cards_player"][card]
                newCard = random.randint(0, 7)
                games[game_id]["cards_player"][card] = newCard
                emit("change_card", {"card": newCard, "pos": card}, room=games[game_id]["player"])
                emit(
                    "played",
                    {
                        "status": "good",
                        "card": oldcard,
                        "player": "player",
                        "x" : data.get("x"),
                        "y" : data.get("y"),
                    },
                    room=game_id,
                )
            else:
                emit(
                    "error",
                    {"status": "error", "message": "Invalid card played"},
                    room=request.sid,
                )

@socketio.on("disconnect")
def handle_disconnect():
    """Handles player disconnection."""
    for game_id, game in games.items():
        if request.sid == game["host"]:
            app.logger.info(Fore.RED + f"{game_id} - Host disconnected" + Style.RESET_ALL)
            emit("disconnected", {"status": "disconnected"}, room=game["player"])
            del games[game_id]
            break
        elif request.sid == game["player"]:
            app.logger.info(Fore.RED + f"{game_id} - Player disconnected" + Style.RESET_ALL)
            emit("disconnected", {"status": "disconnected"}, room=game["host"])
            del games[game_id]
            break

if __name__ == "__main__":
    socketio.run(app, debug=True)
