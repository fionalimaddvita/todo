# To Do

**[▶ Try it here](https://fionalimaddvita.github.io/todo/)** — no install, runs in
your browser.

A local to-do board. Tasks live in **SQLite** (`todo.db`), served by a small
Python script that needs nothing installed — `sqlite3` and `http.server` are
both in the standard library.

> The link above is a demo of the same interface that saves into browser storage,
> so it can be hosted as a static page. Run it properly (below) and every change
> goes to SQLite instead.

## What it looks like

Lists are coloured "lines"; each task is a stop on a spine that shifts hue
between them. Deadlines read like a departure board, overdue in red. Locations
open a map over the board. A farm frames the whole thing.

## Running it

Double-click **`start.bat`**, or from a terminal:

```
cd path\to\todo
python server.py
```

It opens <http://localhost:8787/> in your browser. Press `Ctrl+C` in the
terminal to stop it. Your tasks are already saved by then — nothing is held in
memory waiting to be flushed.

Options:

| Flag | What it does |
| --- | --- |
| `--quiet` | Start without opening a browser |
| `--port 8788` | Use a different port, if 8787 is taken |

## The app

- **Lists** — coloured badges across the top. Click one to filter, click again
  for all of them. Double-click to rename. `+ New list` adds one; a list can
  only be deleted once it's empty.
- **Deadlines** — optional. Items sort by what's due next, undated behind them,
  completed at the bottom. Overdue shows in red with how late it is.
- **Locations** — optional. Click one and a map opens over the board. That map
  is the only part of the app that needs the internet.
- **Ticking off** — click the station dot or the task text.

If the server stops while the page is open, a red strip appears at the top
saying so. The page never pretends a change was saved when it wasn't.

## Where the data is

Everything is in `todo.db` in this folder. To **back it up**, copy that file. To
**start over**, delete it — the next run recreates it with four starter lists.

Two extra files appear next to it while the server runs (`todo.db-wal`,
`todo.db-shm`). That's SQLite's write-ahead log; they're removed on a clean
shutdown, and you don't need to copy them.

Read it with anything that speaks SQLite:

```python
import sqlite3
cx = sqlite3.connect('todo.db')
for r in cx.execute("SELECT text, due, place FROM todos WHERE done = 0 ORDER BY due"):
    print(r)
```

### Schema

```
lists(id, name, ink, pos)
todos(id, text, done, due, place, list_id -> lists.id, created)
```

`ink` is 1–8 and picks the list's colour. `due` is `YYYY-MM-DD` or null.
Deleting a list cascades to its items, though the app won't let you delete one
that still has any.

## API

The page talks to these; so can you.

| | |
| --- | --- |
| `GET /api/state` | Everything, as `{lists, todos}` |
| `POST /api/todos` | `{text, due, place, list}` → the new row |
| `PATCH /api/todos/{id}` | Any of `text`, `done`, `due`, `place`, `list` |
| `DELETE /api/todos/{id}` | |
| `POST /api/lists` | `{name, ink}` → the new row |
| `PATCH /api/lists/{id}` | `{name}` |
| `DELETE /api/lists/{id}` | Refused if the list still holds items |
| `POST /api/import` | One-time bulk load; refused once the database has items |

Bad input comes back as `400` with `{"error": "..."}` rather than being stored.
The server binds to `127.0.0.1`, so it isn't reachable from other machines.

## Files

```
server.py                 the server and the database layer
static/index.html         the whole app - HTML, CSS and JS in one file
todo.db                   your tasks
start.bat                 double-click launcher
import-from-browser.html  one-time import from the old version (see below)
todo.html                 the old browser-storage version, kept for that import
```

## Moving tasks over from the old version

The first version saved tasks inside the browser rather than to a file. Browser
storage is tied to the address a page was opened from, so tasks saved by
`todo.html` (a `file://` page) are *not* visible to the served app at
`localhost` — they have to be handed across deliberately.

1. Start the server.
2. Open `import-from-browser.html` by double-clicking it.
3. It reports what it found; click **Import into SQLite**.

The import refuses to run once the database holds any items, so it can't
overwrite real work. Afterwards you can delete both `import-from-browser.html`
and `todo.html`.
