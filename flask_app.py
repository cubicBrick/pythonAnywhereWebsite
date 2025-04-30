import logging
from logging import ERROR, INFO, WARNING
from colorama import Fore, Back, Style
import random
import string
import os
from functools import wraps
import re
from ansi2html import Ansi2HTMLConverter
from markupsafe import Markup
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_from_directory,
    abort,
    jsonify,
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from flask_socketio import SocketIO, emit, join_room
import bcrypt

# Setup logging
logging.basicConfig(
    filename="log.ansi", format="%(asctime)s - %(levelname)s: %(message)s", level=INFO
)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# Flask app setup
app = Flask(__name__)
app.secret_key = os.urandom(64)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///users.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
socketio = SocketIO(app)
CLEAR_ALL = Style.RESET_ALL
# Permissions
PERMISSIONS = {
    "MOON_GAME"      : 0b0000001,
    "MOON_GAME_ADMIN": 0b0000011,
    "MODIFY_USERS"   : 0b0000100,
    "VIEW_LOG"       : 0b0001000,
    "ADMINISTRATOR"  : 0b1111111
}

SENSITIVE_PERMISSIONS = PERMISSIONS["ADMINISTRATOR"] | PERMISSIONS["MODIFY_USERS"]


# Decorator to check permission bitmask
def requires_permission(required_perm):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(404)
            if current_user.permissions & required_perm != required_perm:
                abort(404)
            return f(*args, **kwargs)

        return decorated_function

    return decorator


# Database model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    permissions = db.Column(db.Integer, nullable=False, default=0)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.route("/get_users", methods=["GET"])
@login_required
@requires_permission(PERMISSIONS["MODIFY_USERS"])
def get_users():
    users = User.query.all()
    users_data = []
    for user in users:
        user_permissions = []
        for perm_name, perm_value in PERMISSIONS.items():
            if user.permissions & perm_value == perm_value:
                user_permissions.append(perm_name)
        users_data.append({"username": user.username, "permissions": user_permissions})
    return jsonify(users_data)


# Manage user route
@app.route("/manage_user", methods=["GET", "POST"])
@login_required
@requires_permission(PERMISSIONS["MODIFY_USERS"])
def manage_user():
    if request.method == "POST":
        action = request.form.get("action")
        username = request.form.get("username")
        target_user = User.query.filter_by(username=username).first()

        selected_perms = request.form.getlist("permissions")
        permission_value = 0
        for p in selected_perms:
            permission_value |= int(p)

        is_admin = (
            current_user.permissions & PERMISSIONS["ADMINISTRATOR"]
            == PERMISSIONS["ADMINISTRATOR"]
        )
        sensitive_requested = permission_value & SENSITIVE_PERMISSIONS

        # Admin-only restrictions
        if not is_admin and sensitive_requested:
            flash(
                "You are not authorized to assign ADMINISTRATOR or MANAGE_USER permissions.",
                "danger",
            )
            return redirect(url_for("manage_user"))

        if action == "delete":
            if target_user:
                if not is_admin and (target_user.permissions & SENSITIVE_PERMISSIONS):
                    flash("You are not authorized to delete this user.", "danger")
                    return redirect(url_for("manage_user"))

                app.logger.info(f"Deleting user {username}")
                db.session.delete(target_user)
                db.session.commit()
                flash(f"User '{username}' deleted.", "info")
            else:
                flash("User not found.", "danger")

        elif action == "edit":
            if target_user:
                if not is_admin and (permission_value & SENSITIVE_PERMISSIONS):
                    flash(
                        "You are not authorized to modify these permissions.", "danger"
                    )
                    return redirect(url_for("manage_user"))

                app.logger.info(f"Editing user {username} with permissions {permission_value}")
                target_user.permissions = permission_value
                db.session.commit()
                flash(f"Permissions updated for '{username}'.", "success")
            else:
                flash("User not found.", "danger")

        elif action == "add":
            password = request.form.get("password")
            if not password:
                flash("Password is required.", "danger")
            elif not target_user:
                if not is_admin and (permission_value & SENSITIVE_PERMISSIONS):
                    flash(
                        "You are not authorized to assign ADMINISTRATOR or MANAGE_USER permissions.",
                        "danger",
                    )
                    return redirect(url_for("manage_user"))

                app.logger.info(f"Creating user {username} with permissions {permission_value}")
                hashed = bcrypt.hashpw(
                    password.encode("utf-8"), bcrypt.gensalt()
                ).decode("utf-8")
                new_user = User(
                    username=username, password=hashed, permissions=permission_value
                )
                db.session.add(new_user)
                db.session.commit()
                flash(f"User '{username}' created.", "add_success")
            else:
                flash("User already exists.", "warning")

    users = User.query.all()
    sorted_permissions = dict(sorted(PERMISSIONS.items(), key=lambda item: -item[1]))
    return render_template(
        "manage_user.html",
        users=users,
        permissions=sorted_permissions,
        is_admin=current_user.permissions & PERMISSIONS["ADMINISTRATOR"]
        == PERMISSIONS["ADMINISTRATOR"],
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    next_page = request.args.get('next')
    
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()

        if user and bcrypt.checkpw(
            password.encode("utf-8"), user.password.encode("utf-8")
        ):
            app.logger.info(f"User {username} logged in")
            login_user(user)
            # If 'next' exists, redirect to that page; otherwise, redirect to home.
            return redirect(next_page or url_for("home"))
        else:
            app.logger.info(f"User {username} failed to log in")
            flash("Login failed. Check your username and/or password.", "danger")

    return render_template("login.html")

@app.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


######################################
######################################
######################################
######################################
######################################

games = {}  # Stores active game sessions

# Save original socketio.on
_original_on = socketio.on


def auto_logging_on(event, *args, **kwargs):
    def decorator(f):
        @wraps(f)
        def wrapped(*f_args, **f_kwargs):
            app.logger.info(
                Fore.CYAN
                + f"RECEIVE <- Event: {event}, Args: {f_args}, Kwargs: {f_kwargs}"
                + Style.RESET_ALL
            )
            return f(*f_args, **f_kwargs)

        return _original_on(event, *args, **kwargs)(wrapped)

    return decorator


socketio.on = auto_logging_on
_original_emit = socketio.emit


def auto_logging_emit(event, *args, **kwargs):
    app.logger.info(
        Fore.MAGENTA
        + f"SEND    -> Event: {event}, Args: {args}, Kwargs: {kwargs}"
        + Style.RESET_ALL
    )
    return _original_emit(event, *args, **kwargs)


def sanitize(data) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "", str(data))


socketio.emit = auto_logging_emit

app.logger.info(Fore.YELLOW + "Flask app started" + Style.RESET_ALL)


def generate_game_id(n=6):
    return "".join(random.choices(string.digits, k=n))


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


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/log")
@requires_permission(PERMISSIONS["VIEW_LOG"])
def view_log():
    with open("log.ansi", "r") as log_file:
        content = log_file.read()

    conv = Ansi2HTMLConverter(inline=True)
    html_content = conv.convert(content, full=False)

    return f"""
    <html>
        <head>
            <title>Server log file</title>
            <meta name="color-scheme" content="light dark">
        </head>
        <body>
            <pre style="word-wrap: break-word; white-space: pre-wrap;">{Markup(html_content)}</pre>
        </body>
    </html>
    """

@app.route("/calculator")
def calculator():
    return render_template("calculator.html")


@app.errorhandler(404)
def page_not_found(error):
    return render_template("notFound.html"), 404


@app.route(f"/moon")
# @login_required
@requires_permission(PERMISSIONS["MOON_GAME"])
def moon():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "templates"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )


@app.route(f"/host")
@requires_permission(PERMISSIONS["MOON_GAME"])
def host():
    """Generate game ID but do not send it to the frontend until board is chosen."""
    game_id = generate_game_id()
    games[game_id] = {"host": request.remote_addr, "player": None, "board": None}
    return render_template("host.html", game_id=game_id, boards=game_boards)


@app.route("/disconnected")
def disconnected():
    return render_template("disconnected.html")


@socketio.on("select_board")
@requires_permission(PERMISSIONS["MOON_GAME"])
def select_board(data):
    """Handles board selection and reveals game ID."""
    game_id = sanitize(data.get("game_id"))
    board_key = sanitize(data.get("board"))

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
                Fore.BLUE + f"{game_id} - Board {board_key} selected" + Style.RESET_ALL
            )
        else:
            emit("error", {"status": "error", "message": "Invalid board selection"})
    else:
        emit(
            "error",
            {"status": "error", "message": "Game not found or board already chosen"},
        )


@app.route(f"/join")
@requires_permission(PERMISSIONS["MOON_GAME"])
def join_page():
    return render_template("join.html")


@socketio.on("join_game")
@requires_permission(PERMISSIONS["MOON_GAME"])
def join_game(data):
    game_id = sanitize(data.get("game_id"))

    if (
        game_id in games
        and games[game_id]["player"] is None
        and games[game_id]["board"]
    ):
        games[game_id]["player"] = request.sid
        join_room(game_id)
        app.logger.info(
            Fore.GREEN + f"{game_id} - Player joined game" + Style.RESET_ALL
        )
        emit("connected", {"status": "connected"}, room=game_id)

        # Get the board data for the game
        board_data = games[game_id]["board"]

        # Send start_game along with board data
        emit("start_game", {"status": "start", "board": board_data}, room=game_id)

        for _ in range(3):
            games[game_id]["cards_host"].append(random.randint(0, 7))
        emit(
            "update_cards",
            {
                "first": games[game_id]["cards_host"][0],
                "second": games[game_id]["cards_host"][1],
                "third": games[game_id]["cards_host"][2],
            },
            room=games[game_id]["host"],
        )

        for _ in range(3):
            games[game_id]["cards_player"].append(random.randint(0, 7))
        emit(
            "update_cards",
            {
                "first": games[game_id]["cards_player"][0],
                "second": games[game_id]["cards_player"][1],
                "third": games[game_id]["cards_player"][2],
            },
            room=games[game_id]["player"],
        )
    else:
        emit("error", {"status": "error", "message": "Invalid or full game"})


def calculate_score(placed_card, all_cards, connections, game_id=None):
    x0, y0, val0 = placed_card
    score = 0
    used_cards = set()

    board_map = {(x, y): v for (x, y, v) in all_cards}

    def is_connected(x1, y1, x2, y2):
        return [(x1, y1), (x2, y2)] in connections or [
            (x2, y2),
            (x1, y1),
        ] in connections

    def find_all_increasing_chains(start_pos):
        chains = []

        def dfs(path):
            last_pos = path[-1]
            last_val = board_map[last_pos]
            next_val = (last_val + 1) % 8
            extended = False
            for nx, ny, nv in all_cards:
                npos = (nx, ny)
                if (
                    npos not in path
                    and is_connected(last_pos[0], last_pos[1], nx, ny)
                    and nv == next_val
                ):
                    dfs(path + [npos])
                    extended = True
            if not extended:
                chains.append(path)

        dfs([start_pos])
        return chains

    all_chains = []
    for x, y, v in all_cards:
        chains_from_here = find_all_increasing_chains((x, y))
        all_chains.extend(chains_from_here)

    placed_pos = (x0, y0)
    chains_with_placed_card = [
        chain for chain in all_chains if placed_pos in chain and len(chain) >= 3
    ]

    def is_subset(small, big):
        for i in range(len(big) - len(small) + 1):
            if big[i : i + len(small)] == small:
                return True
        return False

    maximal_chains = []
    for c in chains_with_placed_card:
        if not any(
            c != other and is_subset(c, other) for other in chains_with_placed_card
        ):
            maximal_chains.append(c)

    for chain in maximal_chains:
        score += len(chain)
        used_cards.update(chain)
        app.logger.info(f"{game_id} - Scoring {len(chain)} points for chain {chain}")

    for x, y, v in all_cards:
        if (x, y) != placed_pos and is_connected(x0, y0, x, y):
            if v == val0:
                if (x0, y0) not in used_cards or (x, y) not in used_cards:
                    score += 1
                    used_cards.add((x0, y0))
                    used_cards.add((x, y))
                    if game_id:
                        app.logger.info(
                            f"{game_id} - Scoring 1 point for pair same cards at {(x0, y0)} and {(x, y)}"
                        )
            elif (val0 - v) % 8 == 4 or (v - val0) % 8 == 4:
                if (x0, y0) not in used_cards or (x, y) not in used_cards:
                    score += 2
                    used_cards.add((x0, y0))
                    used_cards.add((x, y))
                    if game_id:
                        app.logger.info(
                            f"{game_id} - Scoring 2 points for full moon pairs at {(x0, y0)} and {(x, y)}"
                        )

    return score, list(used_cards)


@socketio.on("play_card")
@requires_permission(PERMISSIONS["MOON_GAME"])
def play_card(data):
    game_id = sanitize(data.get("game_id"))
    if game_id not in games:
        emit(
            "error", {"status": "error", "message": "Invalid game ID"}, room=request.sid
        )
        return

    game = games[game_id]

    if request.sid == game["host"]:
        player_type = "host"
        cards = game["cards_host"]
        owner_id = 0
    elif request.sid == game["player"]:
        player_type = "player"
        cards = game["cards_player"]
        owner_id = 1
    else:
        emit(
            "error",
            {"status": "error", "message": "You are not part of this game"},
            room=request.sid,
        )
        return

    card_index = int(sanitize(data.get("card", -1)))
    if not (0 <= card_index < len(cards)):
        emit(
            "error",
            {"status": "error", "message": "Invalid card index"},
            room=request.sid,
        )
        return

    try:
        x = int(sanitize(data.get("x")))
        y = int(sanitize(data.get("y")))
    except (TypeError, ValueError):
        emit(
            "error",
            {"status": "error", "message": "Invalid coordinates"},
            room=request.sid,
        )
        return

    old_card_value = cards[card_index]
    new_card_value = random.randint(0, 7)
    cards[card_index] = new_card_value

    if player_type == "host":
        game["cards_host"] = cards
    else:
        game["cards_player"] = cards

    emit("change_card", {"card": new_card_value, "pos": card_index}, room=request.sid)

    if "played_cards" not in game:
        game["played_cards"] = []
    if "ownership" not in game:
        game["ownership"] = []

    placed_card = (x, y, old_card_value)
    game["played_cards"].append(placed_card)

    ownership_entry = next(
        (c for c in game["ownership"] if c["x"] == x and c["y"] == y), None
    )
    if ownership_entry:
        ownership_entry["value"] = old_card_value
    else:
        game["ownership"].append(
            {"x": x, "y": y, "value": old_card_value, "owner": None}
        )

    score, scored_cards = calculate_score(
        placed_card,
        game["played_cards"],
        game["board"]["connections"],
        game_id,
    )
    if "host_score" not in game:
        game["host_score"] = 0
    if "player_score" not in game:
        game["player_score"] = 0

    if score > 0:
        if player_type == "host":
            game["host_score"] += score
        else:
            game["player_score"] += score

        # Assign ownership to all scored cards (used_cards)
        for (
            cx,
            cy,
        ) in (
            scored_cards
        ):  # scored_cards is returned from calculate_score as list of (x,y)
            for card_data in game["ownership"]:
                if card_data["x"] == cx and card_data["y"] == cy:
                    card_data["owner"] = owner_id

    emit(
        "played",
        {
            "status": "good",
            "card": old_card_value,
            "player": player_type,
            "x": x,
            "y": y,
        },
        room=game_id,
    )

    emit(
        "score_update",
        {
            "total_score": (
                game["player_score"] if player_type == "player" else game["host_score"]
            ),
            "player": player_type,
            "score_this_move": score,
            "ownership": game["ownership"],
        },
        room=game_id,
    )

    emit("ownership_update", {"ownership": game["ownership"]}, room=game_id)

    if len(game["board"]["nodes"]) == len(game["played_cards"]):
        hostBonus = 0
        playerBonus = 0
        for i in game["ownership"]:
            if i["owner"] == 0:
                hostBonus += 1
            if i["owner"] == 1:
                playerBonus += 1
        game["host_score"] += hostBonus
        game["player_score"] += playerBonus
        winner = (
            "host"
            if game["host_score"] > game["player_score"]
            else ("player" if game["host_score"] < game["player_score"] else "tie")
        )
        app.logger.info(
            f"{game_id} - Game over, host bonus: {hostBonus}, player bonus: {playerBonus}, winner: {winner}"
        )
        emit(
            "game_over",
            {
                "status": "game_over",
                "winner": winner,
                "hb": hostBonus,
                "pb": playerBonus,
                "host": game["host_score"],
                "player": game["player_score"],
            },
            room=game_id,
        )
        del games[game_id]


@socketio.on("disconnect")
@requires_permission(PERMISSIONS["MOON_GAME"])
def handle_disconnect():
    game_id = sanitize(game_id)
    """Handles player disconnection."""
    for game_id, game in games.items():
        if request.sid == game["host"]:
            app.logger.info(
                Fore.RED + f"{game_id} - Host disconnected" + Style.RESET_ALL
            )
            emit("disconnected", {"status": "disconnected"}, room=game["player"])
            del games[game_id]
            break
        elif request.sid == game["player"]:
            app.logger.info(
                Fore.RED + f"{game_id} - Player disconnected" + Style.RESET_ALL
            )
            emit("disconnected", {"status": "disconnected"}, room=game["host"])
            del games[game_id]
            break


if __name__ == "__main__":
    socketio.run(app, debug=False, host="0.0.0.0", port=5000)
