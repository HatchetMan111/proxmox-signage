#!/usr/bin/env python3
"""
Digital Signage Server for Proxmox LXC
=======================================
Simple web-based digital signage for small businesses.
Upload images/videos, manage playlists, and stream to any browser.

(c) 2026 – Open Source MIT License
"""

import os
import json
import random
import secrets
from pathlib import Path
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, jsonify,
    send_from_directory, redirect, url_for, session
)
from werkzeug.utils import secure_filename

# ── Configuration ──────────────────────────────────────────────────────────

APP_DIR = Path(__file__).parent.resolve()
MEDIA_DIR = APP_DIR / 'media'
CONFIG_FILE = APP_DIR / 'config.json'

ALLOWED_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp',
    '.webp', '.mp4', '.webm', '.mov',
}
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mov'}

MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500 MB
HOST = os.environ.get('SIGNAGE_HOST', '0.0.0.0')
PORT = int(os.environ.get('SIGNAGE_PORT', 8080))

DEFAULT_CONFIG = {
    'display_duration': 8,
    'transition': 'fade',
    'shuffle': False,
    'show_clock': True,
    'show_filename': False,
    'admin_password': 'admin',
    'playlist': [],
}

# ── App Initialization ─────────────────────────────────────────────────────

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.secret_key = os.environ.get('SIGNAGE_SECRET', secrets.token_hex(32))

MEDIA_DIR.mkdir(parents=True, exist_ok=True)

# ── Helpers ────────────────────────────────────────────────────────────────


def load_config() -> dict:
    if CONFIG_FILE.exists():
        data = json.loads(CONFIG_FILE.read_text())
        merged = dict(DEFAULT_CONFIG)
        merged.update(data)
        return merged
    return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False))


def get_media_files() -> list[dict]:
    """Return all valid media files, respecting playlist order."""
    config = load_config()
    playlist = config.get('playlist', [])

    files = []
    for f in sorted(MEDIA_DIR.iterdir()):
        if f.suffix.lower() in ALLOWED_EXTENSIONS and f.is_file():
            is_video = f.suffix.lower() in VIDEO_EXTENSIONS
            stat = f.stat()
            files.append({
                'filename': f.name,
                'type': 'video' if is_video else 'image',
                'size': stat.st_size,
                'mtime': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })

    by_name = {f['filename']: f for f in files}
    ordered = []
    for name in playlist:
        if name in by_name:
            ordered.append(by_name.pop(name))
    ordered.extend(sorted(by_name.values(), key=lambda x: x['filename']))
    return ordered


def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def safe_filename(filename: str) -> str:
    """Return a unique filename inside MEDIA_DIR."""
    safe = secure_filename(filename)
    if not safe:
        safe = 'unnamed' + Path(filename).suffix
    fp = MEDIA_DIR / safe
    stem = fp.stem
    ext = fp.suffix
    counter = 1
    while fp.exists():
        safe = f"{stem}_{counter}{ext}"
        fp = MEDIA_DIR / safe
        counter += 1
    return safe


# ── Auth ────────────────────────────────────────────────────────────────────


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated


# ── Web Routes ─────────────────────────────────────────────────────────────


@app.route('/')
def index():
    return redirect(url_for('admin'))


@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    config = load_config()
    error = None
    if request.method == 'POST':
        pwd = request.form.get('password', '')
        if pwd == config.get('admin_password', 'admin'):
            session['admin_logged_in'] = True
            session.permanent = True
            next_url = request.args.get('next') or url_for('admin')
            return redirect(next_url)
        error = '❌ Falsches Passwort'
    return render_template('login.html', error=error)


@app.route('/admin/logout')
def logout():
    session.pop('admin_logged_in', None)
    session.clear()
    return redirect(url_for('login'))


@app.route('/admin')
@login_required
def admin():
    config = load_config()
    media = get_media_files()
    player_url = request.host_url.rstrip('/') + '/player'
    return render_template('admin.html', media=media, config=config,
                           player_url=player_url)


@app.route('/player')
def player():
    config = load_config()
    return render_template('player.html', config=config)


# ── API Routes ─────────────────────────────────────────────────────────────


@app.route('/api/media', methods=['GET'])
def api_list_media():
    return jsonify(get_media_files())


@app.route('/api/media/<path:filename>', methods=['DELETE'])
@login_required
def api_delete_media(filename):
    safe = Path(filename).name
    fp = MEDIA_DIR / safe
    if fp.exists() and fp.is_file():
        fp.unlink()
        config = load_config()
        config['playlist'] = [f for f in config['playlist'] if f != safe]
        save_config(config)
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error', 'message': 'Datei nicht gefunden'}), 404


@app.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': 'Keine Datei'}), 400

    files = request.files.getlist('file')
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
        if safe not in config['playlist']:
            config['playlist'].append(safe)
        save_config(config)

    result = {'status': 'ok', 'files': uploaded}
    if errors:
        result['errors'] = errors
    return jsonify(result)


@app.route('/api/playlist', methods=['GET', 'PUT'])
def api_playlist():
    if request.method == 'GET':
        config = load_config()
        config['media'] = get_media_files()
        config.pop('admin_password', None)
        return jsonify(config)

    # PUT – admin only
    if not session.get('admin_logged_in'):
        return jsonify({'status': 'error', 'message': 'Nicht autorisiert'}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'status': 'error', 'message': 'Ungültige JSON-Daten'}), 400

    config = load_config()
    if 'playlist' in data:
        valid = [f for f in data['playlist'] if (MEDIA_DIR / f).is_file()]
        config['playlist'] = valid
    if 'display_duration' in data:
        config['display_duration'] = max(1, min(3600,
                                          int(data['display_duration'])))
    if 'transition' in data:
        config['transition'] = data['transition']
    if 'shuffle' in data:
        config['shuffle'] = bool(data['shuffle'])
    if 'show_clock' in data:
        config['show_clock'] = bool(data['show_clock'])
    if 'show_filename' in data:
        config['show_filename'] = bool(data['show_filename'])
    if 'admin_password' in data:
        pwd = str(data['admin_password']).strip()
        if len(pwd) >= 4:
            config['admin_password'] = pwd
    save_config(config)
    return jsonify({'status': 'ok'})


@app.route('/api/player/next')
def api_player_next():
    """Return the ordered playlist for the player JS."""
    config = load_config()
    playlist = list(config.get('playlist', []))

    if config.get('shuffle'):
        random.shuffle(playlist)

    items = []
    for name in playlist:
        fp = MEDIA_DIR / name
        if fp.is_file():
            is_video = fp.suffix.lower() in VIDEO_EXTENSIONS
            items.append({
                'filename': name,
                'url': url_for('serve_media', filename=name),
                'type': 'video' if is_video else 'image',
            })

    return jsonify({
        'items': items,
        'display_duration': config.get('display_duration', 8),
        'transition': config.get('transition', 'fade'),
        'show_clock': config.get('show_clock', True),
        'show_filename': config.get('show_filename', False),
    })


@app.route('/media/<path:filename>')
def serve_media(filename):
    safe = Path(filename).name
    return send_from_directory(str(MEDIA_DIR), safe)


# ── Error Handlers ─────────────────────────────────────────────────────────


@app.errorhandler(413)
def request_entity_too_large(_error):
    return jsonify({'status': 'error',
                    'message': 'Datei zu gross (max. 500 MB)'}), 413


@app.errorhandler(404)
def not_found(_error):
    return jsonify({'status': 'error', 'message': 'Nicht gefunden'}), 404


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    print("=" * 56, file=sys.stderr)
    print("  🖼️  Digital Signage Server", file=sys.stderr)
    print(f"  Admin:  http://{HOST if HOST != '0.0.0.0' else 'localhost'}:{PORT}/admin", file=sys.stderr)
    print(f"  Player: http://{HOST if HOST != '0.0.0.0' else 'localhost'}:{PORT}/player", file=sys.stderr)
    print("=" * 56, file=sys.stderr)
    app.run(host=HOST, port=PORT, debug=False)
