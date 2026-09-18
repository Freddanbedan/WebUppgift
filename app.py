from datetime import datetime, timezone
import json
from pathlib import Path

from flask import Flask, render_template, request


BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "data" / "posts.json"
app = Flask(__name__, static_folder="public", template_folder="templates")


def read_posts():
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_posts(posts):
    DATA_FILE.write_text(
        json.dumps(posts, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


@app.route("/", methods=["GET", "POST"])
def index():
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        comment = request.form.get("comment", "").strip()

        invalid = (
            not name
            or not comment
            or len(name) > 60
            or len(email) > 100
            or len(comment) > 500
        )
        if invalid:
            error = "Fyll i namn och meddelande. Kontrollera också maxlängderna."
        else:
            post = {
                "name": name,
                "email": email,
                "comment": comment,
                "time": datetime.now(timezone.utc).isoformat(),
            }
            posts = read_posts()
            posts.insert(0, post)
            save_posts(posts)

    return render_template("index.html", posts=read_posts(), error=error)


if __name__ == "__main__":
    app.run(debug=True, port=3000)