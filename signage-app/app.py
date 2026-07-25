#!/usr/bin/env python3
"""
Digital Signage Server for Proxmox LXC
=======================================
Simple web-based digital signage for small businesses.
Upload images/videos, manage playlists, and stream to any browser.

(c) 2026 – Open Source MIT License
"""

import os
import sys
import json
import time
import random
import secrets
import threading
from pathlib import Path
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, jsonify,
    send_from_directory, redirect, url_for, session
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

APP_DIR = Path(__file__).parent.resolve()
MEDIA_DIR = APP_DIR / "media"
CONFIG_FILE = APP_DIR / "config.json"

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".mp4", ".webm", ".mov"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov"}

MAX_CONTENT_LENGTH = 500 * 1024 * 1024
HOST = os.environ.get("SIGNAGE_HOST", "0.0.0.0")
PORT = int(os.environ.get("SIGNAGE_PORT", 8080))

MIN_PASSWORD_LENGTH = 8
DEFAULT_CONFIG = {
    "display_duration": 8,
    "transition": "fade",
    "shuffle": False,
    "show_clock": True,
    "show_filename": False,
    "admin_password_hash": generate_password_hash("admin"),
    "force_password_change": True,
    "playlist": [],
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.secret_key = os.environ.get("SIGNAGE_SECRET") or secrets.token_hex(32)


@app.after_request
def set_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


if not os.environ.get("SIGNAGE_SECRET"):
    print("⚠️  SIGNAGE_SECRET nicht gesetzt – Sessions werden bei jedem Neustart ungültig. "
          "Für stabile Logins die Umgebungsvariable SIGNAGE_SECRET setzen.", file=sys.stderr)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

_config_lock = threading.Lock()


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️  config.json ungültig oder nicht lesbar ({e}) – "
                  f"verwende Standard-Konfiguration, bis sie neu gespeichert wird.", file=sys.stderr)
            return dict(DEFAULT_CONFIG)
        merged = dict(DEFAULT_CONFIG)
        merged.update(data)
        # Migration: alte Klartext-Passwörter aus früheren Versionen zu Hash konvertieren
        if merged.get("admin_password"):
            merged["admin_password_hash"] = generate_password_hash(merged.pop("admin_password"))
            save_config(merged)
        return merged
    return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    # Atomar schreiben: erst in Temp-Datei, dann per rename ersetzen.
    # Verhindert eine korrupte config.json bei Absturz/Stromausfall mitten im Schreiben.
    with _config_lock:
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False))
        tmp.replace(CONFIG_FILE)


def get_media_files() -> list[dict]:
    config = load_config()
    playlist = config.get("playlist", [])
    files = []
    for f in sorted(MEDIA_DIR.iterdir()):
        if f.suffix.lower() in ALLOWED_EXTENSIONS and f.is_file():
            is_video = f.suffix.lower() in VIDEO_EXTENSIONS
            stat = f.stat()
            files.append({
                "filename": f.name,
                "type": "video" if is_video else "image",
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
    by_name = {f["filename"]: f for f in files}
    ordered = []
    for name in playlist:
        if name in by_name:
            ordered.append(by_name.pop(name))
    ordered.extend(sorted(by_name.values(), key=lambda x: x["filename"]))
    return ordered


def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


_filename_lock = threading.Lock()


def safe_filename(filename: str) -> str:
    # Lock + sofortiges Anlegen der Datei verhindert, dass zwei gleichzeitige
    # Uploads mit identischem Namen sich denselben freien Dateinamen "aussuchen"
    # und sich gegenseitig überschreiben (Race Condition / TOCTOU).
    safe = secure_filename(filename)
    if not safe:
        safe = "unnamed" + Path(filename).suffix
    stem = Path(safe).stem
    ext = Path(safe).suffix
    with _filename_lock:
        fp = MEDIA_DIR / safe
        counter = 1
        while fp.exists():
            safe = f"{stem}_{counter}{ext}"
            fp = MEDIA_DIR / safe
            counter += 1
        fp.touch()  # Namen sofort reservieren
    return safe


# ── Auth ──

LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60
_login_attempts: dict[str, list[float]] = {}
_login_attempts_lock = threading.Lock()


def _client_ip() -> str:
    return request.remote_addr or "unknown"


def is_login_locked(ip: str) -> bool:
    with _login_attempts_lock:
        attempts = _login_attempts.get(ip, [])
        cutoff = time.time() - LOGIN_LOCKOUT_SECONDS
        attempts = [t for t in attempts if t > cutoff]
        _login_attempts[ip] = attempts
        return len(attempts) >= LOGIN_MAX_ATTEMPTS


def register_login_failure(ip: str) -> None:
    with _login_attempts_lock:
        _login_attempts.setdefault(ip, []).append(time.time())


def clear_login_failures(ip: str) -> None:
    with _login_attempts_lock:
        _login_attempts.pop(ip, None)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def api_login_required(f):
    # Für Fetch/AJAX-Endpunkte: liefert bei fehlender Session ein klares 401 JSON
    # statt eines Redirects auf die Login-HTML-Seite (die der Client als ungültiges
    # JSON sähe und fälschlich als "Verbindungsfehler" anzeigen würde).
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return jsonify({"status": "error", "message": "Nicht angemeldet – bitte neu einloggen"}), 401
        return f(*args, **kwargs)
    return decorated


# ── Web Routes ──


@app.route("/")
def index():
    return redirect(url_for("admin"))


@app.route("/admin/login", methods=["GET", "POST"])
def login():
    config = load_config()
    error = None
    ip = _client_ip()
    if request.method == "POST":
        if is_login_locked(ip):
            error = f"Zu viele Fehlversuche. Bitte {LOGIN_LOCKOUT_SECONDS // 60} Minuten warten."
        else:
            pwd = request.form.get("password", "")
            pwd_hash = config.get("admin_password_hash", "")
            if pwd_hash and check_password_hash(pwd_hash, pwd):
                clear_login_failures(ip)
                session["admin_logged_in"] = True
                session.permanent = True
                next_url = request.args.get("next") or url_for("admin")
                return redirect(next_url)
            register_login_failure(ip)
            error = "Falsches Passwort"
    return render_template("login.html", error=error)


@app.route("/admin/logout")
def logout():
    session.pop("admin_logged_in", None)
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin")
@login_required
def admin():
    config = load_config()
    media = get_media_files()
    player_url = request.host_url.rstrip("/") + "/player"
    return render_template("admin.html", media=media, config=config, player_url=player_url)


@app.route("/player")
def player():
    config = load_config()
    return render_template("player.html", config=config)


# ── API Routes ──


@app.route("/api/media", methods=["GET"])
def api_list_media():
    media = get_media_files()
    if not session.get("admin_logged_in"):
        # Ausgeblendete Dateien sind nicht für die Wiedergabe gedacht und
        # sollen daher auch nicht über die öffentliche API auflistbar sein.
        hidden = set(load_config().get("hidden_items", []))
        media = [m for m in media if m["filename"] not in hidden]
    return jsonify(media)


@app.route("/api/media/<path:filename>", methods=["DELETE"])
@api_login_required
def api_delete_media(filename):
    safe = Path(filename).name
    fp = MEDIA_DIR / safe
    if fp.exists() and fp.is_file():
        fp.unlink()
        config = load_config()
        config["playlist"] = [f for f in config["playlist"] if f != safe]
        save_config(config)
        return jsonify({"status": "ok"})
    return jsonify({"status": "error", "message": "Datei nicht gefunden"}), 404


@app.route("/api/upload", methods=["POST"])
@api_login_required
def api_upload():
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "Keine Datei"}), 400
    files = request.files.getlist("file")
    uploaded = []
    errors = []
    for f in files:
        if not f.filename:
            continue
        if not allowed_file(f.filename):
            errors.append(f"{f.filename}: nicht erlaubtes Format")
            continue
        safe = safe_filename(f.filename)
        f.save(str(MEDIA_DIR / safe))
        uploaded.append(safe)
        config = load_config()
        if safe not in config["playlist"]:
            config["playlist"].append(safe)
        save_config(config)
    result = {"status": "ok", "files": uploaded}
    if errors:
        result["errors"] = errors
    return jsonify(result)


@app.route("/api/playlist", methods=["GET", "PUT"])
def api_playlist():
    if request.method == "GET":
        cfg = load_config()
        cfg["media"] = get_media_files()
        cfg.pop("admin_password", None)
        cfg.pop("admin_password_hash", None)
        return jsonify(cfg)
    if not session.get("admin_logged_in"):
        return jsonify({"status": "error", "message": "Nicht autorisiert"}), 401
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "Ungültige JSON-Daten"}), 400
    config = load_config()
    for key in ("playlist", "display_duration", "transition", "shuffle", "show_clock", "show_filename"):
        if key in data:
            if key == "playlist":
                config[key] = [f for f in data[key] if (MEDIA_DIR / f).is_file()]
            elif key == "display_duration":
                try:
                    config[key] = max(1, min(3600, int(data[key])))
                except (TypeError, ValueError):
                    pass  # ungültigen Wert ignorieren statt mit 500 abzustürzen
            elif key in ("shuffle", "show_clock", "show_filename"):
                config[key] = bool(data[key])
            else:
                config[key] = data[key]
    if "hidden_items" in data:
        config["hidden_items"] = data["hidden_items"]
    if "background_color" in data:
        config["background_color"] = data["background_color"]
    if "background_image" in data:
        config["background_image"] = data["background_image"]
    pw_error = None
    if "admin_password" in data:
        pwd = str(data["admin_password"]).strip()
        if len(pwd) >= MIN_PASSWORD_LENGTH:
            config["admin_password_hash"] = generate_password_hash(pwd)
            config["force_password_change"] = False
        else:
            pw_error = f"Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen haben"
    save_config(config)
    if pw_error:
        return jsonify({"status": "error", "message": pw_error}), 400
    return jsonify({"status": "ok"})


@app.route("/api/player/next")
def api_player_next():
    config = load_config()
    playlist = list(config.get("playlist", []))
    hidden = set(config.get("hidden_items", []))
    playlist = [f for f in playlist if f not in hidden]
    if config.get("shuffle"):
        random.shuffle(playlist)
    items = []
    for name in playlist:
        fp = MEDIA_DIR / name
        if fp.is_file():
            items.append({
                "filename": name,
                "url": url_for("serve_media", filename=name),
                "type": "video" if fp.suffix.lower() in VIDEO_EXTENSIONS else "image",
            })
    return jsonify({
        "items": items,
        "display_duration": config.get("display_duration", 8),
        "transition": config.get("transition", "fade"),
        "show_clock": config.get("show_clock", True),
        "show_filename": config.get("show_filename", False),
        "background_color": config.get("background_color", "#000000"),
        "background_image": config.get("background_image", ""),
    })


@app.route("/media/<path:filename>")
def serve_media(filename):
    safe = Path(filename).name
    if not session.get("admin_logged_in"):
        hidden = set(load_config().get("hidden_items", []))
        if safe in hidden:
            return jsonify({"status": "error", "message": "Nicht gefunden"}), 404
    return send_from_directory(str(MEDIA_DIR), safe)


# ── Error Handler ──


@app.errorhandler(413)
def _413(_e):
    return jsonify({"status": "error", "message": "Datei zu gross (max. 500 MB)"}), 413


@app.errorhandler(404)
def _404(_e):
    return jsonify({"status": "error", "message": "Nicht gefunden"}), 404


if __name__ == "__main__":
    print("=" * 56, file=sys.stderr)
    print("  🖼️  Digital Signage Server", file=sys.stderr)
    print(f"  Admin:  http://{HOST if HOST != '0.0.0.0' else 'localhost'}:{PORT}/admin", file=sys.stderr)
    print(f"  Player: http://{HOST if HOST != '0.0.0.0' else 'localhost'}:{PORT}/player", file=sys.stderr)
    print("=" * 56, file=sys.stderr)
    app.run(host=HOST, port=PORT, debug=False)
