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
from datetime import datetime, date, time as dtime
from functools import wraps
from contextlib import contextmanager
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
IMAGE_COMPRESS_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}  # .gif bewusst ausgenommen (Animation würde verloren gehen)
MAX_IMAGE_DIMENSION = 2560  # px, längste Seite - alles darüber wird beim Upload verkleinert
HOURS_WIDGET_ID = "__hours_widget__"

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

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
    "ken_burns": False,
    "layout": "fullscreen",
    "secondary_background_color": "#000000",
    "admin_password_hash": generate_password_hash("admin"),
    "force_password_change": True,
    "playlist": [],
    "item_schedule": {},   # {key: {"days":[0-6], "start":"HH:MM", "end":"HH:MM", "expires":"YYYY-MM-DD"}}
    "text_slides": {},     # {id: {"text":..., "bg_color":..., "text_color":..., "icon":..., "created_at":...}}
    "item_zone": {},       # {key: "secondary"} - fehlender Eintrag = "main" (Standard-Bereich)
    "emergency": None,     # None oder {"text":..., "bg_color":..., "text_color":..., "icon":...}
    "opening_hours": {
        "enabled": False,
        "display_mode": "banner",  # "banner" (immer sichtbar, unten) oder "slide" (rotiert wie ein normales Element)
        "hours": {},        # {"0":{"open":"08:00","close":"18:00"}, ...} - Mo=0..So=6, fehlender Tag = geschlossen
        "bg_color": "#0f766e",
        "text_color": "#ffffff",
        "closed_text": "Geschlossen",
        "open_prefix": "Geöffnet bis",
    },
}

VALID_LAYOUTS = {"fullscreen", "main_ticker", "main_sidebar", "split_2up"}

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

# Einfacher "Zuletzt online"-Status für den Player: bewusst NUR im Arbeitsspeicher
# gehalten, nicht in config.json geschrieben. Der Player pollt regelmäßig
# (alle 30s) - würde jeder Poll einen config_transaction()-Schreibzyklus
# auslösen, wäre das unnötiger Disk-I/O nur für einen Zeitstempel. Bei einem
# Neustart des Dienstes ist der Status "war noch nie online" wieder korrekt,
# das ist für diesen einfachen Zweck ausreichend (kein Multi-Geräte-Tracking).
_last_seen_lock = threading.Lock()
_last_seen_at: datetime | None = None


def _read_config_file() -> dict:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️  config.json ungültig oder nicht lesbar ({e}) – "
                  f"verwende Standard-Konfiguration, bis sie neu gespeichert wird.", file=sys.stderr)
            return dict(DEFAULT_CONFIG)
        merged = dict(DEFAULT_CONFIG)
        merged.update(data)
        return merged
    return dict(DEFAULT_CONFIG)


def _write_config_file_locked(config: dict) -> None:
    # Muss innerhalb von _config_lock aufgerufen werden.
    # Atomar schreiben: erst in Temp-Datei, dann per rename ersetzen.
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False))
    tmp.replace(CONFIG_FILE)


def load_config() -> dict:
    """Für reine Lesezugriffe (z.B. GET-Routen). Für Lese-Ändern-Schreiben-Zyklen
    IMMER config_transaction() verwenden – load_config()+save_config() als zwei
    getrennte Schritte ist NICHT nebenläufigkeitssicher (Lost-Update-Risiko,
    empirisch nachgewiesen: bei 10 gleichzeitigen Schreibzugriffen gingen ohne
    diesen Fix bis zu 40% der Änderungen still verloren, trotz HTTP 200)."""
    with _config_lock:
        config = _read_config_file()
        if config.get("admin_password"):
            # Migration alter Klartext-Passwörter aus früheren Versionen
            config["admin_password_hash"] = generate_password_hash(config.pop("admin_password"))
            _write_config_file_locked(config)
        return config


def save_config(config: dict) -> None:
    """Für in sich geschlossene Schreibvorgänge ohne vorheriges Lesen im selben
    Request. Für Lese-Ändern-Schreiben-Zyklen stattdessen config_transaction()."""
    with _config_lock:
        _write_config_file_locked(config)


@contextmanager
def config_transaction():
    """Hält den Lock über den GESAMTEN Lese-Ändern-Schreiben-Zyklus statt nur
    über den finalen Schreibvorgang. Das ist der eigentliche Fix für das
    Lost-Update-Problem: vorher konnten zwei parallele Requests beide dieselbe
    (veraltete) Kopie der Config lesen, unabhängig voneinander ändern und
    speichern – der zweite Schreibvorgang hat den ersten dann überschrieben.
    Nutzung: `with config_transaction() as config: config["x"] = y`
    """
    with _config_lock:
        config = _read_config_file()
        yield config
        _write_config_file_locked(config)


def compute_hours_status(config: dict, now: datetime | None = None) -> dict:
    """Berechnet den aktuellen Öffnungsstatus aus der Wochentag-Konfiguration.
    Behandelt explizit Zeitfenster über Mitternacht (z.B. 18:00-01:00): dafür
    muss sowohl das HEUTIGE Fenster (ab Öffnung) als auch ein GESTRIGES
    Fenster, das noch bis in den frühen Morgen von heute hineinreicht,
    geprüft werden - ein reiner "open <= jetzt <= close"-Vergleich schlägt
    fehl, sobald open > close numerisch ist."""
    now = now or datetime.now()
    oh = config.get("opening_hours", {})
    hours = oh.get("hours", {})
    t = now.time()
    open_prefix = oh.get("open_prefix", "Geöffnet bis")

    today = hours.get(str(now.weekday()))
    if today and today.get("open") and today.get("close"):
        try:
            o, c = _parse_hhmm(today["open"]), _parse_hhmm(today["close"])
            if o <= c:
                if o <= t <= c:
                    return {"open_now": True, "text": f"{open_prefix} {today['close']} Uhr"}
            elif t >= o:
                # Über Mitternacht, und wir sind im Abend-Teil (nach Öffnung, vor Mitternacht)
                return {"open_now": True, "text": f"{open_prefix} {today['close']} Uhr"}
        except (ValueError, KeyError):
            pass

    yesterday = hours.get(str((now.weekday() - 1) % 7))
    if yesterday and yesterday.get("open") and yesterday.get("close"):
        try:
            o, c = _parse_hhmm(yesterday["open"]), _parse_hhmm(yesterday["close"])
            if o > c and t <= c:
                # Gestriges Fenster ging über Mitternacht und reicht noch bis jetzt (früher Morgen)
                return {"open_now": True, "text": f"{open_prefix} {yesterday['close']} Uhr"}
        except (ValueError, KeyError):
            pass

    return {"open_now": False, "text": oh.get("closed_text", "Geschlossen")}


def build_hours_widget_item(config: dict, now: datetime | None = None) -> dict:
    """Baut das Öffnungszeiten-Widget als normales Text-Item - dadurch braucht
    weder Admin-Galerie noch Player irgendeine Sonderbehandlung für den Typ,
    beides rendert es wie einen ganz normalen Text-Slide."""
    status = compute_hours_status(config, now)
    oh = config.get("opening_hours", {})
    return {
        "filename": HOURS_WIDGET_ID,
        "type": "text",
        "text": status["text"],
        "bg_color": oh.get("bg_color", "#0f766e"),
        "text_color": oh.get("text_color", "#ffffff"),
        "icon": "✅" if status["open_now"] else "🔒",
    }


def maybe_compress_image(filepath: Path) -> None:
    """Verkleinert zu große Bilder beim Upload automatisch (max. 2560px lange
    Seite). GIFs werden bewusst übersprungen, damit Animationen nicht durch
    das Neuspeichern als Standbild verloren gehen. Scheitert die Kompression
    aus irgendeinem Grund, bleibt die Originaldatei unangetastet - der Upload
    selbst darf dadurch nie fehlschlagen."""
    if not PIL_AVAILABLE or filepath.suffix.lower() not in IMAGE_COMPRESS_EXTENSIONS:
        return
    try:
        with Image.open(filepath) as img:
            w, h = img.size
            if max(w, h) <= MAX_IMAGE_DIMENSION:
                return
            scale = MAX_IMAGE_DIMENSION / max(w, h)
            resized = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
            save_kwargs = {}
            if filepath.suffix.lower() in (".jpg", ".jpeg"):
                if resized.mode in ("RGBA", "P"):
                    resized = resized.convert("RGB")
                save_kwargs = {"quality": 85, "optimize": True}
            resized.save(filepath, **save_kwargs)
    except Exception as e:
        print(f"⚠️  Bildkomprimierung übersprungen für {filepath.name}: {e}", file=sys.stderr)


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
    for tid, slide in config.get("text_slides", {}).items():
        files.append({
            "filename": tid,
            "type": "text",
            "text": slide.get("text", ""),
            "bg_color": slide.get("bg_color", "#111827"),
            "text_color": slide.get("text_color", "#ffffff"),
            "icon": slide.get("icon", ""),
            "mtime": slide.get("created_at", ""),
        })
    oh_cfg = config.get("opening_hours", {})
    if oh_cfg.get("enabled") and oh_cfg.get("display_mode", "banner") == "slide":
        files.append(build_hours_widget_item(config))
    by_name = {f["filename"]: f for f in files}
    ordered = []
    for name in playlist:
        if name in by_name:
            ordered.append(by_name.pop(name))
    ordered.extend(sorted(by_name.values(), key=lambda x: x["filename"]))
    return ordered


def _parse_hhmm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def is_item_active(key: str, config: dict, now: datetime | None = None) -> bool:
    """Prüft, ob ein Playlist-Item (Datei oder Text-Slide) laut Zeitplan
    und Ablaufdatum gerade angezeigt werden soll. Kein Eintrag = immer aktiv."""
    rule = config.get("item_schedule", {}).get(key)
    if not rule:
        return True
    now = now or datetime.now()
    expires = rule.get("expires")
    if expires:
        try:
            if now.date() > date.fromisoformat(expires):
                return False
        except ValueError:
            pass
    days = rule.get("days")
    if days:
        if now.weekday() not in days:
            return False
    start, end = rule.get("start"), rule.get("end")
    if start and end:
        try:
            t = now.time()
            s, e = _parse_hhmm(start), _parse_hhmm(end)
            if s <= e:
                if not (s <= t <= e):
                    return False
            else:  # Zeitfenster über Mitternacht, z.B. 22:00–02:00
                if not (t >= s or t <= e):
                    return False
        except ValueError:
            pass
    return True


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
    schedules = config.get("item_schedule", {})
    zones = config.get("item_zone", {})
    now = datetime.now()
    for item in media:
        rule = schedules.get(item["filename"])
        item["has_schedule"] = bool(rule)
        item["expired"] = bool(
            rule and rule.get("expires") and now.date() > date.fromisoformat(rule["expires"])
        ) if rule and rule.get("expires") else False
        item["zone"] = zones.get(item["filename"], "main")

    # Playlist kann "logisch leer" sein (Zeitplan aktiv, Bereich nie zugewiesen),
    # ohne dass man das im Admin auf den ersten Blick sieht - der Player zeigt
    # dann einfach "Keine Medien". Das hier baut konkrete Hinweise dazu auf.
    layout = config.get("layout", "fullscreen")
    if layout not in VALID_LAYOUTS:
        layout = "fullscreen"
    hidden = set(config.get("hidden_items", []))
    main_total = main_active = secondary_total = secondary_active = 0
    for name in config.get("playlist", []):
        if name in hidden:
            continue
        zone = zones.get(name, "main") if layout != "fullscreen" else "main"
        active = is_item_active(name, config, now)
        if zone == "secondary":
            secondary_total += 1
            if active:
                secondary_active += 1
        else:
            main_total += 1
            if active:
                main_active += 1

    playlist_warnings = []
    if config.get("emergency"):
        pass  # Während des Notfall-Modus ist der normale Playlist-Zustand irrelevant - keine Doppel-Banner
    elif layout == "fullscreen":
        if main_total > 0 and main_active == 0:
            playlist_warnings.append(
                f"Aktuell werden 0 von {main_total} Elementen angezeigt – vermutlich greift gerade ein Zeitplan (⏰)."
            )
    else:
        if secondary_total == 0:
            playlist_warnings.append(
                "Der Sekundär-Bereich ist noch leer – zieh unten Medien ins Tray, damit dort etwas läuft."
            )
        elif secondary_active == 0:
            playlist_warnings.append(
                f"Aktuell werden 0 von {secondary_total} Elementen im Sekundär-Bereich angezeigt – vermutlich greift gerade ein Zeitplan (⏰)."
            )
        if main_total == 0:
            playlist_warnings.append("Der Haupt-Bereich ist leer – lade Medien hoch.")
        elif main_active == 0:
            playlist_warnings.append(
                f"Aktuell werden 0 von {main_total} Elementen im Haupt-Bereich angezeigt – vermutlich greift gerade ein Zeitplan (⏰)."
            )

    player_url = request.host_url.rstrip("/") + "/player"

    weekday_labels = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    oh = config.get("opening_hours", {})
    oh_display_mode = oh.get("display_mode", "banner")
    if oh_display_mode not in ("banner", "slide"):
        oh_display_mode = "banner"
    oh_days = []
    for i, label in enumerate(weekday_labels):
        day = oh.get("hours", {}).get(str(i))
        oh_days.append({
            "idx": i, "label": label,
            "open": day.get("open") if day else "",
            "close": day.get("close") if day else "",
            "closed": day is None,
        })

    return render_template("admin.html", media=media, config=config, player_url=player_url,
                            playlist_warnings=playlist_warnings, oh_days=oh_days,
                            oh_display_mode=oh_display_mode)


@app.route("/player")
def player():
    config = load_config()
    return render_template("player.html", config=config)


# ── API Routes ──


@app.route("/api/status")
@api_login_required
def api_status():
    with _last_seen_lock:
        seen = _last_seen_at
    if seen is None:
        return jsonify({"last_seen": None, "seconds_ago": None})
    seconds_ago = (datetime.now() - seen).total_seconds()
    return jsonify({"last_seen": seen.isoformat(), "seconds_ago": round(seconds_ago)})


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
    if safe == HOURS_WIDGET_ID:
        return jsonify({"status": "error", "message": "Das Öffnungszeiten-Widget lässt sich nur über die Einstellungen deaktivieren, nicht löschen"}), 400
    fp = MEDIA_DIR / safe
    is_file = fp.exists() and fp.is_file()
    with config_transaction() as config:
        if is_file:
            fp.unlink()
        elif safe in config.get("text_slides", {}):
            del config["text_slides"][safe]
        else:
            return jsonify({"status": "error", "message": "Datei nicht gefunden"}), 404
        config["playlist"] = [f for f in config["playlist"] if f != safe]
        config.get("item_schedule", {}).pop(safe, None)
    return jsonify({"status": "ok"})


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
        try:
            f.save(str(MEDIA_DIR / safe))
        except Exception as e:
            # Reservierte Datei aus safe_filename() wieder entfernen, sonst bleibt
            # eine 0-Byte-Leiche liegen, die den Dateinamen dauerhaft blockiert
            # und als kaputtes Medium in der Playlist auftauchen würde.
            (MEDIA_DIR / safe).unlink(missing_ok=True)
            errors.append(f"{f.filename}: Speichern fehlgeschlagen ({e})")
            continue
        maybe_compress_image(MEDIA_DIR / safe)
        uploaded.append(safe)
    skip_playlist = request.form.get("skip_playlist") == "1"
    if uploaded and not skip_playlist:
        with config_transaction() as config:
            for safe in uploaded:
                if safe not in config["playlist"]:
                    config["playlist"].append(safe)
    result = {"status": "ok", "files": uploaded}
    if errors:
        result["errors"] = errors
    return jsonify(result)


MAX_TEXT_SLIDE_LENGTH = 280


@app.route("/api/text-slide", methods=["POST"])
@api_login_required
def api_create_text_slide():
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", "")).strip()[:MAX_TEXT_SLIDE_LENGTH]
    if not text:
        return jsonify({"status": "error", "message": "Text darf nicht leer sein"}), 400
    tid = "text_" + secrets.token_hex(4)
    with config_transaction() as config:
        config.setdefault("text_slides", {})[tid] = {
            "text": text,
            "bg_color": str(data.get("bg_color", "#111827"))[:20],
            "text_color": str(data.get("text_color", "#ffffff"))[:20],
            "icon": str(data.get("icon", ""))[:8],
            "created_at": datetime.now().isoformat(),
        }
        config["playlist"].append(tid)
    return jsonify({"status": "ok", "id": tid})


@app.route("/api/text-slide/<slide_id>", methods=["PUT"])
@api_login_required
def api_update_text_slide(slide_id):
    data = request.get_json(silent=True) or {}
    if "text" in data:
        text = str(data["text"]).strip()[:MAX_TEXT_SLIDE_LENGTH]
        if not text:
            return jsonify({"status": "error", "message": "Text darf nicht leer sein"}), 400
    else:
        text = None
    with config_transaction() as config:
        if slide_id not in config.get("text_slides", {}):
            return jsonify({"status": "error", "message": "Text-Slide nicht gefunden"}), 404
        slide = config["text_slides"][slide_id]
        if text is not None:
            slide["text"] = text
        if "bg_color" in data:
            slide["bg_color"] = str(data["bg_color"])[:20]
        if "text_color" in data:
            slide["text_color"] = str(data["text_color"])[:20]
        if "icon" in data:
            slide["icon"] = str(data["icon"])[:8]
    return jsonify({"status": "ok"})


@app.route("/api/emergency", methods=["POST", "DELETE"])
@api_login_required
def api_emergency():
    if request.method == "DELETE":
        with config_transaction() as config:
            config["emergency"] = None
        return jsonify({"status": "ok"})
    data = request.get_json(silent=True) or {}
    media = data.get("media")
    if media:
        safe = Path(media).name
        if not (MEDIA_DIR / safe).is_file():
            return jsonify({"status": "error", "message": "Datei nicht gefunden"}), 404
        with config_transaction() as config:
            config["emergency"] = {"media": safe}
        return jsonify({"status": "ok"})
    text = str(data.get("text", "")).strip()[:200]
    if not text:
        return jsonify({"status": "error", "message": "Text darf nicht leer sein"}), 400
    with config_transaction() as config:
        config["emergency"] = {
            "text": text,
            "bg_color": str(data.get("bg_color", "#dc2626"))[:20],
            "text_color": str(data.get("text_color", "#ffffff"))[:20],
            "icon": str(data.get("icon", "🚨"))[:8],
        }
    return jsonify({"status": "ok"})


@app.route("/api/opening-hours", methods=["PUT"])
@api_login_required
def api_set_opening_hours():
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled"))
    hours_in = data.get("hours", {}) if isinstance(data.get("hours"), dict) else {}
    hours = {}
    for day in range(7):
        entry = hours_in.get(str(day))
        if entry and entry.get("open") and entry.get("close"):
            try:
                _parse_hhmm(entry["open"])
                _parse_hhmm(entry["close"])
                hours[str(day)] = {"open": entry["open"], "close": entry["close"]}
            except (ValueError, TypeError):
                return jsonify({"status": "error", "message": "Ungültige Uhrzeit (Format HH:MM)"}), 400
    with config_transaction() as config:
        config.setdefault("opening_hours", dict(DEFAULT_CONFIG["opening_hours"]))
        config["opening_hours"]["enabled"] = enabled
        config["opening_hours"]["hours"] = hours
        display_mode = data.get("display_mode")
        if display_mode not in ("banner", "slide"):
            display_mode = config["opening_hours"].get("display_mode", "banner")
        config["opening_hours"]["display_mode"] = display_mode
        if "bg_color" in data:
            config["opening_hours"]["bg_color"] = str(data["bg_color"])[:20]
        if "text_color" in data:
            config["opening_hours"]["text_color"] = str(data["text_color"])[:20]
        # Playlist-Zugehörigkeit sauber halten: das Widget ist nur im Slide-Modus
        # ein rotierendes Element. Im Banner-Modus (oder wenn deaktiviert) darf
        # es dort nicht als "Geister-Slide" liegen bleiben.
        if enabled and display_mode == "slide":
            if HOURS_WIDGET_ID not in config["playlist"]:
                config["playlist"].append(HOURS_WIDGET_ID)
        else:
            config["playlist"] = [f for f in config["playlist"] if f != HOURS_WIDGET_ID]
    return jsonify({"status": "ok"})


@app.route("/api/zone/<key>", methods=["PUT"])
@api_login_required
def api_set_zone(key):
    # Eigener, schlanker Endpunkt nur für die Bereichs-Zuweisung (Drag&Drop-Tray
    # im Admin). Bewusst getrennt von /api/schedule/<key>: der Zeitplan-Endpunkt
    # baut sein "rule"-Objekt bei jedem PUT komplett neu auf (days/start/end/
    # expires) - würde man von dort aus nur {"zone": "..."} senden, ginge ein
    # eventuell bestehender Zeitplan des Elements verloren. Dieser Endpunkt
    # fasst ausschließlich item_zone an.
    safe = Path(key).name
    data = request.get_json(silent=True) or {}
    zone = data.get("zone", "main")
    if zone not in ("main", "secondary"):
        zone = "main"
    with config_transaction() as config:
        valid = (MEDIA_DIR / safe).is_file() or safe in config.get("text_slides", {}) or safe == HOURS_WIDGET_ID
        if not valid:
            return jsonify({"status": "error", "message": "Element nicht gefunden"}), 404
        config.setdefault("item_zone", {})
        if zone == "secondary":
            config["item_zone"][safe] = "secondary"
        else:
            config["item_zone"].pop(safe, None)
    return jsonify({"status": "ok"})


@app.route("/api/schedule/<key>", methods=["PUT", "DELETE"])
@api_login_required
def api_set_schedule(key):
    safe = Path(key).name
    zone = None
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}
        zone = data.get("zone")
        if zone not in ("main", "secondary"):
            zone = "main"
        rule = {}
        days = data.get("days")
        if isinstance(days, list) and days:
            try:
                rule["days"] = sorted({int(d) for d in days if 0 <= int(d) <= 6})
            except (TypeError, ValueError):
                pass
        start, end = data.get("start"), data.get("end")
        if start and end:
            try:
                _parse_hhmm(start)
                _parse_hhmm(end)
                rule["start"], rule["end"] = start, end
            except (ValueError, AttributeError):
                return jsonify({"status": "error", "message": "Ungültige Uhrzeit (Format HH:MM)"}), 400
        expires = data.get("expires")
        if expires:
            try:
                date.fromisoformat(expires)
                rule["expires"] = expires
            except ValueError:
                return jsonify({"status": "error", "message": "Ungültiges Datum (Format YYYY-MM-DD)"}), 400
    with config_transaction() as config:
        valid = (MEDIA_DIR / safe).is_file() or safe in config.get("text_slides", {}) or safe == HOURS_WIDGET_ID
        if not valid:
            return jsonify({"status": "error", "message": "Element nicht gefunden"}), 404
        config.setdefault("item_schedule", {})
        config.setdefault("item_zone", {})
        if request.method == "DELETE":
            config["item_schedule"].pop(safe, None)
            config["item_zone"].pop(safe, None)
        else:
            if rule:
                config["item_schedule"][safe] = rule
            else:
                config["item_schedule"].pop(safe, None)
            if zone == "secondary":
                config["item_zone"][safe] = "secondary"
            else:
                config["item_zone"].pop(safe, None)
    return jsonify({"status": "ok"})


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
    pw_error = None
    with config_transaction() as config:
        for key in ("playlist", "display_duration", "transition", "shuffle", "show_clock", "show_filename", "ken_burns", "layout"):
            if key in data:
                if key == "playlist":
                    text_ids = set(config.get("text_slides", {}).keys())
                    oh_cfg = config.get("opening_hours", {})
                    if oh_cfg.get("enabled") and oh_cfg.get("display_mode", "banner") == "slide":
                        text_ids.add(HOURS_WIDGET_ID)
                    config[key] = [f for f in data[key] if (MEDIA_DIR / f).is_file() or f in text_ids]
                elif key == "layout":
                    if data[key] in VALID_LAYOUTS:
                        config[key] = data[key]
                elif key == "display_duration":
                    try:
                        config[key] = max(1, min(3600, int(data[key])))
                    except (TypeError, ValueError):
                        pass  # ungültigen Wert ignorieren statt mit 500 abzustürzen
                elif key in ("shuffle", "show_clock", "show_filename", "ken_burns"):
                    config[key] = bool(data[key])
                else:
                    config[key] = data[key]
        if "hidden_items" in data:
            config["hidden_items"] = data["hidden_items"]
        if "background_color" in data:
            config["background_color"] = data["background_color"]
        if "background_image" in data:
            config["background_image"] = data["background_image"]
        if "secondary_background_color" in data:
            config["secondary_background_color"] = data["secondary_background_color"]
        if "admin_password" in data:
            pwd = str(data["admin_password"]).strip()
            if len(pwd) >= MIN_PASSWORD_LENGTH:
                config["admin_password_hash"] = generate_password_hash(pwd)
                config["force_password_change"] = False
            else:
                pw_error = f"Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen haben"
    if pw_error:
        return jsonify({"status": "error", "message": pw_error}), 400
    return jsonify({"status": "ok"})


@app.route("/api/player/next")
def api_player_next():
    global _last_seen_at
    with _last_seen_lock:
        _last_seen_at = datetime.now()
    config = load_config()

    # Notfall-Override hat absoluten Vorrang vor allem anderen (Playlist,
    # Zeitpläne, Layout/Zonen) - zeigt IMMER nur die Notfallmeldung, fullscreen,
    # unabhängig vom sonst konfigurierten Layout, damit sie maximal auffällt.
    emergency = config.get("emergency")
    if emergency:
        emergency_item = None
        if emergency.get("media"):
            fp = MEDIA_DIR / emergency["media"]
            if fp.is_file():
                emergency_item = {
                    "filename": emergency["media"],
                    "type": "video" if fp.suffix.lower() in VIDEO_EXTENSIONS else "image",
                    "zone": "main",
                    "url": url_for("serve_media", filename=emergency["media"]),
                }
            # Falls die Datei zwischenzeitlich gelöscht wurde, während der Notfall
            # aktiv war: nicht mit einem kaputten Bild hängenbleiben, sondern auf
            # eine generische Textmeldung zurückfallen.
        if emergency_item is None:
            emergency_item = {
                "filename": "__emergency__",
                "type": "text",
                "zone": "main",
                "text": emergency.get("text") or "Notfall aktiv",
                "bg_color": emergency.get("bg_color", "#dc2626"),
                "text_color": emergency.get("text_color", "#ffffff"),
                "icon": emergency.get("icon", "🚨"),
            }
        return jsonify({
            "items": [emergency_item],
            "layout": "fullscreen",
            "display_duration": config.get("display_duration", 8),
            "transition": "none",
            "show_clock": config.get("show_clock", True),
            "show_filename": False,
            "background_color": emergency.get("bg_color", "#dc2626"),
            "background_image": "",
            "secondary_background_color": "#000000",
            "ken_burns": False,
            "opening_hours_banner": None,
        })

    playlist = list(config.get("playlist", []))
    hidden = set(config.get("hidden_items", []))
    now = datetime.now()
    playlist = [f for f in playlist if f not in hidden and is_item_active(f, config, now)]
    if config.get("shuffle"):
        random.shuffle(playlist)
    text_slides = config.get("text_slides", {})
    item_zone = config.get("item_zone", {})
    layout = config.get("layout", "fullscreen")
    if layout not in VALID_LAYOUTS:
        layout = "fullscreen"
    items = []
    for name in playlist:
        zone = item_zone.get(name, "main") if layout != "fullscreen" else "main"
        if name == HOURS_WIDGET_ID:
            oh_cfg_loop = config.get("opening_hours", {})
            if oh_cfg_loop.get("enabled") and oh_cfg_loop.get("display_mode", "banner") == "slide":
                widget = build_hours_widget_item(config, now)
                widget["zone"] = zone
                items.append(widget)
            continue
        if name in text_slides:
            slide = text_slides[name]
            items.append({
                "filename": name,
                "type": "text",
                "zone": zone,
                "text": slide.get("text", ""),
                "bg_color": slide.get("bg_color", "#111827"),
                "text_color": slide.get("text_color", "#ffffff"),
                "icon": slide.get("icon", ""),
            })
            continue
        fp = MEDIA_DIR / name
        if fp.is_file():
            items.append({
                "filename": name,
                "url": url_for("serve_media", filename=name),
                "type": "video" if fp.suffix.lower() in VIDEO_EXTENSIONS else "image",
                "zone": zone,
            })
    oh_cfg = config.get("opening_hours", {})
    opening_hours_banner = None
    if oh_cfg.get("enabled") and oh_cfg.get("display_mode", "banner") == "banner":
        status = compute_hours_status(config, now)
        opening_hours_banner = {
            "text": status["text"],
            "bg_color": oh_cfg.get("bg_color", "#0f766e"),
            "text_color": oh_cfg.get("text_color", "#ffffff"),
            "icon": "✅" if status["open_now"] else "🔒",
        }

    return jsonify({
        "items": items,
        "layout": layout,
        "display_duration": config.get("display_duration", 8),
        "transition": config.get("transition", "fade"),
        "show_clock": config.get("show_clock", True),
        "show_filename": config.get("show_filename", False),
        "background_color": config.get("background_color", "#000000"),
        "background_image": config.get("background_image", ""),
        "secondary_background_color": config.get("secondary_background_color", "#000000"),
        "ken_burns": config.get("ken_burns", False),
        "opening_hours_banner": opening_hours_banner,
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
