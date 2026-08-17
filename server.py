#!/usr/bin/env python3
"""Local to-do server.

Standard library only - nothing to install. Serves the app from static/ and
keeps every task in todo.db, a plain SQLite file sitting next to this script.

    python server.py            start on http://localhost:8787 and open a browser
    python server.py --quiet    start without opening a browser
    python server.py --port N   use a different port
"""

import json
import os
import re
import sqlite3
import sys
import threading
import webbrowser
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
DB = os.path.join(HERE, "todo.db")

DUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_TEXT = 500
MAX_PLACE = 200
MAX_NAME = 60

# The lists a brand new database starts with. Rename them in the app by
# double-clicking a badge. Keep these generic - this file is version controlled.
SEED = [("Work", 1), ("Personal", 4), ("Errands", 6), ("Someday", 8)]

SCHEMA = """
CREATE TABLE IF NOT EXISTS lists (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT    NOT NULL,
    ink  INTEGER NOT NULL,
    pos  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS todos (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    text    TEXT    NOT NULL,
    done    INTEGER NOT NULL DEFAULT 0,
    due     TEXT,
    place   TEXT,
    list_id INTEGER NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
    created TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS todos_by_list ON todos(list_id);
"""


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

def connect():
    cx = sqlite3.connect(DB, timeout=10)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON")
    return cx


def setup():
    """Create the schema, and seed the starter lists only on a fresh file."""
    with closing(connect()) as cx, cx:
        cx.execute("PRAGMA journal_mode = WAL")
        cx.executescript(SCHEMA)
        if cx.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 0:
            cx.executemany(
                "INSERT INTO lists (name, ink, pos) VALUES (?, ?, ?)",
                [(name, ink, pos) for pos, (name, ink) in enumerate(SEED)],
            )


def row_to_todo(r):
    return {
        "id": r["id"],
        "text": r["text"],
        "done": bool(r["done"]),
        "due": r["due"],
        "place": r["place"],
        "list": r["list_id"],
    }


def read_state():
    with closing(connect()) as cx:
        lists = [
            {"id": r["id"], "name": r["name"], "ink": r["ink"]}
            for r in cx.execute("SELECT id, name, ink FROM lists ORDER BY pos, id")
        ]
        todos = [row_to_todo(r) for r in cx.execute("SELECT * FROM todos ORDER BY id")]
    return {"lists": lists, "todos": todos}


# --------------------------------------------------------------------------
# Field checks. Anything the app sends is treated as untrusted.
# --------------------------------------------------------------------------

class BadInput(Exception):
    pass


def clean_text(v, limit=MAX_TEXT, field="text"):
    if not isinstance(v, str) or not v.strip():
        raise BadInput(f"{field} is required")
    return v.strip()[:limit]


def clean_due(v):
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not DUE_RE.match(v):
        raise BadInput("due must look like YYYY-MM-DD")
    return v


def clean_place(v):
    if v in (None, ""):
        return None
    if not isinstance(v, str):
        raise BadInput("place must be text")
    return v.strip()[:MAX_PLACE] or None


def clean_ink(v):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise BadInput("ink must be a number")
    if not 1 <= n <= 8:
        raise BadInput("ink must be 1-8")
    return n


def list_exists(cx, list_id):
    return cx.execute("SELECT 1 FROM lists WHERE id = ?", (list_id,)).fetchone() is not None


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

def create_todo(body):
    text = clean_text(body.get("text"))
    due = clean_due(body.get("due"))
    place = clean_place(body.get("place"))
    list_id = body.get("list")

    with closing(connect()) as cx, cx:
        if not list_exists(cx, list_id):
            raise BadInput("that list no longer exists")
        cur = cx.execute(
            "INSERT INTO todos (text, done, due, place, list_id) VALUES (?, 0, ?, ?, ?)",
            (text, due, place, list_id),
        )
        row = cx.execute("SELECT * FROM todos WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_todo(row)


def update_todo(todo_id, body):
    sets, values = [], []

    if "text" in body:
        sets.append("text = ?")
        values.append(clean_text(body["text"]))
    if "done" in body:
        sets.append("done = ?")
        values.append(1 if body["done"] else 0)
    if "due" in body:
        sets.append("due = ?")
        values.append(clean_due(body["due"]))
    if "place" in body:
        sets.append("place = ?")
        values.append(clean_place(body["place"]))
    if "list" in body:
        sets.append("list_id = ?")
        values.append(body["list"])

    if not sets:
        raise BadInput("nothing to change")

    with closing(connect()) as cx, cx:
        if "list" in body and not list_exists(cx, body["list"]):
            raise BadInput("that list no longer exists")
        cx.execute(f"UPDATE todos SET {', '.join(sets)} WHERE id = ?", values + [todo_id])
        row = cx.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    if row is None:
        raise BadInput("no such item")
    return row_to_todo(row)


def delete_todo(todo_id):
    with closing(connect()) as cx, cx:
        cx.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    return {"ok": True}


def create_list(body):
    name = clean_text(body.get("name"), MAX_NAME, "name")
    ink = clean_ink(body.get("ink", 1))
    with closing(connect()) as cx, cx:
        pos = cx.execute("SELECT COALESCE(MAX(pos), -1) + 1 FROM lists").fetchone()[0]
        cur = cx.execute(
            "INSERT INTO lists (name, ink, pos) VALUES (?, ?, ?)", (name, ink, pos)
        )
        row = cx.execute("SELECT id, name, ink FROM lists WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def update_list(list_id, body):
    name = clean_text(body.get("name"), MAX_NAME, "name")
    with closing(connect()) as cx, cx:
        cx.execute("UPDATE lists SET name = ? WHERE id = ?", (name, list_id))
        row = cx.execute("SELECT id, name, ink FROM lists WHERE id = ?", (list_id,)).fetchone()
    if row is None:
        raise BadInput("no such list")
    return dict(row)


def delete_list(list_id):
    """Refuse while the list still holds items, so nothing is lost quietly."""
    with closing(connect()) as cx, cx:
        held = cx.execute("SELECT COUNT(*) FROM todos WHERE list_id = ?", (list_id,)).fetchone()[0]
        if held:
            raise BadInput("that list still has items in it")
        if cx.execute("SELECT COUNT(*) FROM lists").fetchone()[0] <= 1:
            raise BadInput("keep at least one list")
        cx.execute("DELETE FROM lists WHERE id = ?", (list_id,))
    return {"ok": True}


def import_state(body):
    """One-time lift of whatever the browser-only version had saved.

    Refuses once the database holds items, so it can never overwrite real work.
    """
    with closing(connect()) as cx, cx:
        if cx.execute("SELECT COUNT(*) FROM todos").fetchone()[0]:
            raise BadInput("this database already has items - import skipped")

        incoming_lists = body.get("lists") or []
        incoming_todos = body.get("todos") or []
        if not incoming_todos:
            raise BadInput("nothing to import")

        cx.execute("DELETE FROM lists")          # cascades to todos, which are none
        old_to_new = {}

        for pos, l in enumerate(incoming_lists):
            try:
                name = clean_text(l.get("name"), MAX_NAME, "name")
                ink = clean_ink(l.get("ink", 1))
            except BadInput:
                continue
            cur = cx.execute(
                "INSERT INTO lists (name, ink, pos) VALUES (?, ?, ?)", (name, ink, pos)
            )
            old_to_new[l.get("id")] = cur.lastrowid

        if not old_to_new:
            cur = cx.execute("INSERT INTO lists (name, ink, pos) VALUES (?, ?, 0)", ("General", 1))
            old_to_new = {None: cur.lastrowid}

        fallback = next(iter(old_to_new.values()))
        kept = 0
        for t in incoming_todos:
            try:
                text = clean_text(t.get("text"))
            except BadInput:
                continue
            cx.execute(
                "INSERT INTO todos (text, done, due, place, list_id) VALUES (?, ?, ?, ?, ?)",
                (
                    text,
                    1 if t.get("done") else 0,
                    clean_due(t.get("due")) if DUE_RE.match(str(t.get("due") or "")) else None,
                    clean_place(t.get("place")),
                    old_to_new.get(t.get("list"), fallback),
                ),
            )
            kept += 1

    return {"imported": kept}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
}

ID_ROUTE = re.compile(r"^/api/(todos|lists)/(\d+)$")


class Handler(BaseHTTPRequestHandler):
    server_version = "todo/1.0"
    protocol_version = "HTTP/1.1"

    # ---- plumbing --------------------------------------------------------
    def log_message(self, fmt, *args):
        if not self.path.startswith("/api/"):
            return
        sys.stderr.write("  %s %s\n" % (self.command, self.path))

    def send_json(self, payload, status=200):
        blob = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(blob)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise BadInput("that request was not valid JSON")

    def serve_file(self, path):
        rel = unquote(urlparse(path).path).lstrip("/")
        if rel in ("", "index.html"):
            rel = "index.html"

        full = os.path.normpath(os.path.join(STATIC, rel))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            self.send_error(404, "Not found")
            return

        with open(full, "rb") as fh:
            blob = fh.read()

        self.send_response(200)
        self.send_header("Content-Type", TYPES.get(os.path.splitext(full)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(blob)

    # ---- verbs -----------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/api/state":
            self.route(lambda: read_state())
        elif self.path.startswith("/api/"):
            self.send_json({"error": "no such endpoint"}, 404)
        else:
            self.serve_file(self.path)

    def do_POST(self):
        self.dispatch("POST")

    def do_PATCH(self):
        self.dispatch("PATCH")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def dispatch(self, verb):
        path = self.path.split("?")[0]
        hit = ID_ROUTE.match(path)

        if verb == "POST" and path == "/api/todos":
            self.route(lambda: create_todo(self.read_body()), 201)
        elif verb == "POST" and path == "/api/lists":
            self.route(lambda: create_list(self.read_body()), 201)
        elif verb == "POST" and path == "/api/import":
            self.route(lambda: import_state(self.read_body()))
        elif hit and hit.group(1) == "todos":
            rid = int(hit.group(2))
            if verb == "PATCH":
                self.route(lambda: update_todo(rid, self.read_body()))
            else:
                self.route(lambda: delete_todo(rid))
        elif hit and hit.group(1) == "lists":
            rid = int(hit.group(2))
            if verb == "PATCH":
                self.route(lambda: update_list(rid, self.read_body()))
            else:
                self.route(lambda: delete_list(rid))
        else:
            self.send_json({"error": "no such endpoint"}, 404)

    def route(self, work, status=200):
        try:
            self.send_json(work(), status)
        except BadInput as e:
            self.send_json({"error": str(e)}, 400)
        except sqlite3.Error as e:
            self.send_json({"error": "database error: %s" % e}, 500)


def main():
    port = 8787
    quiet = "--quiet" in sys.argv
    if "--port" in sys.argv:
        try:
            port = int(sys.argv[sys.argv.index("--port") + 1])
        except (IndexError, ValueError):
            sys.exit("--port needs a number, e.g. --port 9000")

    setup()
    url = "http://localhost:%d/" % port

    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        sys.exit(
            "Could not start on port %d (%s).\n"
            "Something else is using it - try: python server.py --port 8788" % (port, e)
        )

    print("To Do is running at %s" % url)
    print("Tasks are saved in %s" % DB)
    print("Press Ctrl+C to stop.\n")

    if not quiet:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped. Your tasks are saved.")
        httpd.server_close()


if __name__ == "__main__":
    main()
