from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import json
import os
from pathlib import Path
import re
import sqlite3

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATABASE_FILE = DATA_DIR / "forum.db"
LEGACY_DATA_FILE = DATA_DIR / "posts.json"
app = Flask(__name__, static_folder="public", template_folder="templates")
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-this-secret"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


@contextmanager
def database():
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_database():
    DATA_DIR.mkdir(exist_ok=True)
    with database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                author_name TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS migrations (
                name TEXT PRIMARY KEY
            );
            """
        )
        migration = connection.execute(
            "SELECT name FROM migrations WHERE name = ?",
            ("import_legacy_posts",),
        ).fetchone()
        if migration is None:
            try:
                legacy_posts = json.loads(LEGACY_DATA_FILE.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                legacy_posts = []

            if isinstance(legacy_posts, list):
                for post in reversed(legacy_posts):
                    if not isinstance(post, dict):
                        continue
                    author_name = str(post.get("name", "Anonym")).strip()[:60] or "Anonym"
                    content = str(post.get("comment", "")).strip()[:1000]
                    if content:
                        connection.execute(
                            "INSERT INTO posts (author_name, content, created_at) VALUES (?, ?, ?)",
                            (
                                author_name,
                                content,
                                post.get("time") or datetime.now(timezone.utc).isoformat(),
                            ),
                        )
            connection.execute(
                "INSERT INTO migrations (name) VALUES (?)",
                ("import_legacy_posts",),
            )


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Logga in för att öppna forumet.")
            return redirect(url_for("index"))
        return view(*args, **kwargs)

    return wrapped_view


init_database()


@app.get("/")
def index():
    if "user_id" in session:
        return redirect(url_for("forum"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("forum"))
    if request.method == "GET":
        return render_template("register.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
        return render_template(
            "register.html",
            error="Användarnamnet ska vara 3–30 tecken och bara innehålla bokstäver, siffror eller _.",
        ), 400
    if len(password) < 8 or len(password) > 128:
        return render_template(
            "register.html", error="Lösenordet ska vara minst 8 tecken."
        ), 400

    try:
        with database() as connection:
            cursor = connection.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (
                    username,
                    generate_password_hash(password),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        return render_template(
            "register.html", error="Användarnamnet används redan."
        ), 400

    session.clear()
    session["user_id"] = user_id
    session["username"] = username
    return redirect(url_for("forum"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("forum"))
    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    with database() as connection:
        user = connection.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()

    if user is None or not check_password_hash(user["password_hash"], password):
        return render_template(
            "login.html", error="Fel användarnamn eller lösenord."
        ), 401

    session.clear()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    return redirect(url_for("forum"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/forum", methods=["GET", "POST"])
@login_required
def forum():
    error = None
    if request.method == "POST":
        content = request.form.get("content", "").strip()
        if not content or len(content) > 1000:
            error = "Skriv ett inlägg på högst 1000 tecken."
        else:
            with database() as connection:
                connection.execute(
                    "INSERT INTO posts (user_id, author_name, content, created_at) VALUES (?, ?, ?, ?)",
                    (
                        session["user_id"],
                        session["username"],
                        content,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            return redirect(url_for("forum"))

    with database() as connection:
        posts = connection.execute(
            "SELECT author_name, content, created_at FROM posts ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return render_template(
        "index.html", posts=posts, error=error, username=session["username"]
    )


if __name__ == "__main__":
    app.run(debug=True, port=3000)