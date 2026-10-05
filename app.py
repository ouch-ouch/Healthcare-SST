"""Web UI: upload the four source files, review open flags, look up an employee.

Deliberately thin -- every route calls straight into sot.cli's ingest/
list_open_flags/show_employee/resolve_flag_cmd, the same functions the CLI
uses. No separate UI-layer business logic, so the web view and the CLI can
never disagree about what the source of truth contains.
"""

import os
import tempfile

from flask import Flask, redirect, render_template_string, request, url_for

from sot.cli import ingest, list_open_flags, resolve_flag_cmd, show_employee
from sot.db import init_db

DB_PATH = os.environ.get("SOT_DB", "harborview.db")
UPLOAD_DIR = tempfile.mkdtemp(prefix="sot_uploads_")

app = Flask(__name__)

PAGE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Harborview Source of Truth</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 920px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }
  h1 { margin-bottom: .25rem; }
  .sub { color: #666; margin-top: 0; }
  .card { border: 1px solid #ddd; border-radius: 10px; padding: 1.25rem; margin-bottom: 1.5rem; }
  .card h2 { margin-top: 0; font-size: 1.05rem; }
  pre { background: #f6f6f6; padding: 1rem; border-radius: 6px; overflow-x: auto; white-space: pre-wrap; font-size: .9rem; }
  form { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; }
  input[type=text] { flex: 1; min-width: 180px; padding: .5rem; font-size: 1rem; border: 1px solid #ccc; border-radius: 6px; }
  button { padding: .5rem 1rem; font-size: 1rem; border: 0; border-radius: 6px; background: #1f6f5c; color: white; cursor: pointer; }
  button:hover { background: #185a4a; }
  .message { background: #eef7f1; border: 1px solid #bfe3cf; padding: .6rem 1rem; border-radius: 6px; margin-top: .75rem; white-space: pre-wrap; }
</style>
</head>
<body>

<h1>Harborview Source of Truth</h1>
<p class="sub">Ingest the four source files, review what got flagged, resolve what's confirmed.</p>

<div class="card">
  <h2>1. Ingest files</h2>
  <form method="post" action="/ingest" enctype="multipart/form-data">
    <input type="file" name="files" multiple required>
    <button type="submit">Ingest</button>
  </form>
  <p class="sub">Select or drag all four files at once (or any subset) -- order doesn't matter.</p>
  {% if message %}<div class="message">{{ message }}</div>{% endif %}
</div>

<div class="card">
  <h2>2. Open flags</h2>
  <pre>{{ flags_text }}</pre>
</div>

<div class="card">
  <h2>3. Look up an employee</h2>
  <form method="get" action="/employee">
    <input type="text" name="name" placeholder="e.g. Sofia Reyes" value="{{ emp_name or '' }}">
    <button type="submit">Look up</button>
  </form>
  {% if emp_text %}<pre>{{ emp_text }}</pre>{% endif %}
</div>

<div class="card">
  <h2>4. Resolve a flag</h2>
  <form method="post" action="/resolve">
    <input type="text" name="flag_id" placeholder="flag id (copy from above)" required>
    <input type="text" name="resolved_by" placeholder="your name" required>
    <input type="text" name="resolution" placeholder="what you decided" required>
    <button type="submit">Resolve</button>
  </form>
</div>

</body>
</html>
"""


def _get_conn():
    return init_db(DB_PATH)


@app.route("/")
def index():
    conn = _get_conn()
    return render_template_string(
        PAGE,
        message=request.args.get("message"),
        flags_text=list_open_flags(conn),
        emp_name=None,
        emp_text=None,
    )


@app.route("/ingest", methods=["POST"])
def do_ingest():
    uploads = [f for f in request.files.getlist("files") if f.filename]
    conn = _get_conn()

    results = []
    for uploaded in uploads:
        path = os.path.join(UPLOAD_DIR, uploaded.filename)
        uploaded.save(path)
        try:
            ingest(conn, path)
            results.append(f"Ingested {uploaded.filename}")
        except Exception as exc:  # noqa: BLE001 -- surface any one file's error without stopping the rest
            results.append(f"Error ingesting {uploaded.filename}: {exc}")

    message = "\n".join(results) if results else "No files selected."
    return redirect(url_for("index", message=message))


@app.route("/employee")
def employee():
    name = request.args.get("name", "")
    conn = _get_conn()
    emp_text = show_employee(conn, name) if name else None
    return render_template_string(
        PAGE,
        message=None,
        flags_text=list_open_flags(conn),
        emp_name=name,
        emp_text=emp_text,
    )


@app.route("/resolve", methods=["POST"])
def resolve():
    conn = _get_conn()
    flag_id = request.form["flag_id"]
    resolved_by = request.form["resolved_by"]
    resolution = request.form["resolution"]
    try:
        resolve_flag_cmd(conn, flag_id, resolved_by, resolution)
        message = f"Resolved flag {flag_id}"
    except Exception as exc:  # noqa: BLE001 -- surface a bad flag id instead of a stack trace
        message = f"Error resolving {flag_id}: {exc}"

    return redirect(url_for("index", message=message))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
