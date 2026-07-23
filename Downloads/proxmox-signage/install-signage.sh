#!/usr/bin/env bash
# =============================================================================
#  🖼️ Proxmox Digital Signage – One-Click Installer
#  https://github.com/HatchetMan111/proxmox-signage
#
#  Installation (auf Proxmox VE als root):
#    bash <(curl -s https://raw.githubusercontent.com/HatchetMan111/proxmox-signage/main/install-signage.sh)
#
#  Mit Optionen:
#    bash <(curl -s ...) --id 220 --memory 512 --ip 192.168.1.100/24
#
#  Update:
#    bash <(curl -s ...) --update --id 210
#
#  Deinstallieren:
#    bash <(curl -s ...) --uninstall --id 210
#
#  Status:
#    bash <(curl -s ...) --status --id 210
# =============================================================================

set -euo pipefail

# ── GitHub-Quelle ───────────────────────────────────────────────────────────
REPO_RAW="https://raw.githubusercontent.com/HatchetMan111/proxmox-signage/main"

# ── Farben & Logging ───────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

info()  { echo -e "${BLUE}ℹ${NC}  $1"; }
ok()    { echo -e "${GREEN}✔${NC}  $1"; }
warn()  { echo -e "${YELLOW}⚠${NC}  $1"; }
err()   { echo -e "${RED}✘${NC}  $1" >&2; }
die()   { err "$1"; exit 1; }
header(){ echo -e "\n${CYAN}${BOLD}━━━ $1 ━━━${NC}"; }

# ── Defaults ────────────────────────────────────────────────────────────────
CT_ID=210
CT_HOSTNAME="signage"
CT_STORAGE="local-lvm"
CT_ROOTFS=2
CT_CORES=1
CT_MEMORY=256
CT_SWAP=0
CT_BRIDGE="vmbr0"
CT_IP="dhcp"
CT_PASSWORD="signage"
CT_TEMPLATE=""
UNINSTALL=false
UPDATE=false
STATUS_CHECK=false
LOCAL_MODE=false
APP_SRC=""
TMP_DIR=""

# ── Cleanup ─────────────────────────────────────────────────────────────────
cleanup() {
    [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]] && rm -rf "$TMP_DIR"
}
trap cleanup EXIT

# ── Download-Helfer ─────────────────────────────────────────────────────────
download_file() {
    local url="$1" dest="$2"
    if command -v curl &>/dev/null; then
        curl -fsSL --connect-timeout 10 --retry 2 "$url" -o "$dest"
    elif command -v wget &>/dev/null; then
        wget -qO "$dest" --timeout=10 --tries=2 "$url"
    else
        die "Weder curl noch wget gefunden. Bitte installieren: apt install curl"
    fi
}

# ── Argumente parsen ───────────────────────────────────────────────────────
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --id)        CT_ID="$2"; shift 2 ;;
            --hostname)  CT_HOSTNAME="$2"; shift 2 ;;
            --storage)   CT_STORAGE="$2"; shift 2 ;;
            --rootfs)    CT_ROOTFS="$2"; shift 2 ;;
            --cores)     CT_CORES="$2"; shift 2 ;;
            --memory)    CT_MEMORY="$2"; shift 2 ;;
            --swap)      CT_SWAP="$2"; shift 2 ;;
            --bridge)    CT_BRIDGE="$2"; shift 2 ;;
            --ip)        CT_IP="$2"; shift 2 ;;
            --password)  CT_PASSWORD="$2"; shift 2 ;;
            --template)  CT_TEMPLATE="$2"; shift 2 ;;
            --uninstall) UNINSTALL=true; shift ;;
            --update)    UPDATE=true; shift ;;
            --status)    STATUS_CHECK=true; shift ;;
            --local)     LOCAL_MODE=true; shift ;;
            --help|-h)   usage; exit 0 ;;
            *)           die "Unbekanntes Argument: $1 (--help für Hilfe)" ;;
        esac
    done
}

usage() {
    cat <<'USAGE'
🖼️  Proxmox Digital Signage – One-Click Installer

Usage:
  bash <(curl -s https://raw.githubusercontent.com/HatchetMan111/proxmox-signage/main/install-signage.sh) [OPTIONS]

Options:
  --id NUM        Container-ID (Default: 210)
  --hostname TEXT Hostname (Default: signage)
  --storage TEXT  Proxmox Storage (Default: local-lvm)
  --rootfs NUM    RootFS in GB (Default: 2)
  --cores NUM     CPU-Kerne (Default: 1)
  --memory NUM    RAM in MB (Default: 256)
  --ip ADDR       Statische IP oder "dhcp" (Default: dhcp)
  --password TEXT Root-Passwort (Default: signage)
  --update        App-Dateien aktualisieren (Container bleibt)
  --uninstall     Container vollständig entfernen
  --status        Service-Status anzeigen
  --local         Lokale Dateien verwenden (statt GitHub-Download)
  --help          Diese Hilfe

Examples:
  # Standard-Installation:
  bash <(curl -s https://raw.githubusercontent.com/HatchetMan111/proxmox-signage/main/install-signage.sh)

  # Mit eigener IP und mehr RAM:
  bash <(curl -s ...) --id 220 --memory 512 --ip 192.168.1.100/24

  # Update:
  bash <(curl -s ...) --update --id 210

  # Deinstallieren:
  bash <(curl -s ...) --uninstall --id 210
USAGE
}

# ── Voraussetzungen prüfen ─────────────────────────────────────────────────
check_prerequisites() {
    header "Prüfe Voraussetzungen"

    [[ $EUID -ne 0 ]] && die "Bitte als root ausführen (sudo bash ...)"
    command -v pct &>/dev/null || die "pct nicht gefunden – läuft dieses Script auf einem Proxmox VE Host?"
    command -v pveam &>/dev/null || die "pveam nicht gefunden – ist Proxmox VE korrekt installiert?"

    # Template automatisch finden
    if [[ -z "$CT_TEMPLATE" ]]; then
        local t
        t=$(pveam list local 2>/dev/null | grep -i "debian-12-standard" | head -1 || true)
        if [[ -z "$t" ]]; then
            info "Lade Debian-12-Template herunter (einmalig)..."
            pveam download local debian-12-standard_12.12-1_amd64.tar.zst 2>&1 | tail -3
            t=$(pveam list local 2>/dev/null | grep -i "debian-12-standard" | head -1 || true)
            [[ -z "$t" ]] && die "Kein Debian-12-Template verfügbar.\n  Bitte zuerst: pveam download local debian-12-standard_12.2-1_amd64.tar.zst"
        fi
        CT_TEMPLATE=$(echo "$t" | awk '{print $1}')
        CT_TEMPLATE=$(basename "$CT_TEMPLATE")
    fi
    ok "Template: $CT_TEMPLATE"

    # Container-ID prüfen (nur bei Neuinstallation)
    if ! $UNINSTALL && ! $UPDATE && ! $STATUS_CHECK; then
        local orig_id="$CT_ID"
        while pct list 2>/dev/null | grep -q "^${CT_ID}\b"; do
            CT_ID=$((CT_ID + 1))
        done
        if [[ "$CT_ID" != "$orig_id" ]]; then
            info "Container $orig_id ist belegt – verwende stattdessen ID $CT_ID"
        fi
    fi
}

# ── Deinstallieren ─────────────────────────────────────────────────────────
do_uninstall() {
    header "Entferne Container $CT_ID"
    if pct list 2>/dev/null | grep -q "^${CT_ID}\b"; then
        pct stop "$CT_ID" 2>/dev/null || true
        sleep 2
        pct destroy "$CT_ID" --purge 2>/dev/null
        ok "Container $CT_ID entfernt"
    else
        warn "Container $CT_ID existiert nicht"
    fi
    exit 0
}

# ── Status ──────────────────────────────────────────────────────────────────
do_status() {
    header "Status: Container $CT_ID"
    if pct list 2>/dev/null | grep -q "^${CT_ID}\b"; then
        local state
        state=$(pct status "$CT_ID" 2>/dev/null || echo "unknown")
        info "Container: $state"
        if [[ "$state" == *"running"* ]]; then
            pct exec "$CT_ID" -- systemctl status signage --no-pager 2>/dev/null || true
        fi
    else
        warn "Container $CT_ID existiert nicht"
    fi
    exit 0
}

# ── App-Dateien laden ──────────────────────────────────────────────────────
download_app() {
    header "Lade App-Dateien"

    # Lokaler Modus: Dateien liegen neben dem Script
    if $LOCAL_MODE; then
        local script_dir
        script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo ".")"
        if [[ -f "$script_dir/signage-app/app.py" ]]; then
            APP_SRC="$script_dir/signage-app"
            ok "Lokale Dateien: $APP_SRC"
            return 0
        fi
        die "--local: signage-app/ nicht gefunden neben dem Script"
    fi

    # GitHub-Download
    TMP_DIR=$(mktemp -d /tmp/signage-install-XXXXXX)
    mkdir -p "$TMP_DIR/signage-app/templates" \
             "$TMP_DIR/signage-app/static" \
             "$TMP_DIR/signage-app/media"

    local base="${REPO_RAW}/signage-app"
    local files=(
        "app.py"
        "requirements.txt"
        "static/style.css"
        "templates/admin.html"
        "templates/player.html"
    )

    for f in "${files[@]}"; do
        info "  ↓ $f"
        if ! download_file "${base}/${f}" "$TMP_DIR/signage-app/${f}"; then
            die "Download fehlgeschlagen: $f\n  Repository erreichbar? https://github.com/HatchetMan111/proxmox-signage"
        fi
    done

    touch "$TMP_DIR/signage-app/media/.gitkeep"
    APP_SRC="$TMP_DIR/signage-app"
    ok "App-Dateien geladen"
}

# ── LXC erstellen ──────────────────────────────────────────────────────────
create_container() {
    header "Erstelle LXC-Container (ID: $CT_ID)"

    pct create "$CT_ID" "local:vztmpl/${CT_TEMPLATE}" \
        --hostname "$CT_HOSTNAME" \
        --storage "$CT_STORAGE" \
        --rootfs "${CT_STORAGE}:${CT_ROOTFS}" \
        --cores "$CT_CORES" \
        --memory "$CT_MEMORY" \
        --swap "$CT_SWAP" \
        --net0 "name=eth0,bridge=${CT_BRIDGE},ip=${CT_IP}" \
        --password "$CT_PASSWORD" \
        --unprivileged 1 \
        --features nesting=1 \
        --onboot 1 \
        --start 0 \
        2>&1 | tail -3

    ok "Container $CT_ID erstellt"
}

# ── Container einrichten ───────────────────────────────────────────────────
setup_container() {
    header "Richte Container ein"

    pct start "$CT_ID" 2>&1 | tail -2
    ok "Container gestartet"

    # Warten auf Netzwerk
    info "Warte auf Netzwerk..."
    local i
    for i in $(seq 1 30); do
        pct exec "$CT_ID" -- ping -c1 -W1 1.1.1.1 &>/dev/null && break
        sleep 1
    done

    # Python + Flask installieren
    info "Installiere Python + Flask..."
    pct exec "$CT_ID" -- apt-get update -qq 2>&1 | tail -1
    pct exec "$CT_ID" -- apt-get install -y -qq \
        python3 python3-pip python3-flask python3-werkzeug \
        2>&1 | tail -3
    ok "Python + Flask installiert"

    # App-Dateien kopieren
    info "Kopiere App-Dateien..."
    pct exec "$CT_ID" -- mkdir -p /opt/signage/media /opt/signage/templates /opt/signage/static

    pct push "$CT_ID" "$APP_SRC/app.py" /opt/signage/app.py
    pct push "$CT_ID" "$APP_SRC/requirements.txt" /opt/signage/requirements.txt

    for tmpl in "$APP_SRC"/templates/*.html; do
        [[ -f "$tmpl" ]] && pct push "$CT_ID" "$tmpl" "/opt/signage/templates/$(basename "$tmpl")"
    done
    for f in "$APP_SRC"/static/*; do
        [[ -f "$f" ]] && pct push "$CT_ID" "$f" "/opt/signage/static/$(basename "$f")"
    done
    ok "Dateien kopiert"

    # Konfiguration anlegen
    pct exec "$CT_ID" -- bash -c 'cat > /opt/signage/config.json <<CFGEOF
{
    "display_duration": 8,
    "transition": "fade",
    "shuffle": false,
    "show_clock": true,
    "show_filename": false,
    "playlist": []
}
CFGEOF'

    # systemd-Service einrichten
    info "Richte systemd-Service ein..."
    pct exec "$CT_ID" -- bash -c 'cat > /etc/systemd/system/signage.service <<SVCEOF
[Unit]
Description=Digital Signage Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/signage
ExecStart=/usr/bin/python3 /opt/signage/app.py
Restart=always
RestartSec=5
Environment=SIGNAGE_HOST=0.0.0.0
Environment=SIGNAGE_PORT=8080

[Install]
WantedBy=multi-user.target
SVCEOF'

    pct exec "$CT_ID" -- systemctl daemon-reload
    pct exec "$CT_ID" -- systemctl enable signage
    pct exec "$CT_ID" -- systemctl start signage

    sleep 2
    if pct exec "$CT_ID" -- systemctl is-active --quiet signage; then
        ok "Signage-Service läuft"
    else
        warn "Service läuft nicht – prüfe: pct enter $CT_ID && journalctl -u signage"
    fi
}

# ── Update (nur App-Dateien) ───────────────────────────────────────────────
update_container() {
    header "Aktualisiere App in Container $CT_ID"

    pct list 2>/dev/null | grep -q "^${CT_ID}\b" || \
        die "Container $CT_ID existiert nicht. Bitte zuerst installieren."

    download_app

    info "Kopiere neue Dateien..."
    pct push "$CT_ID" "$APP_SRC/app.py" /opt/signage/app.py
    pct push "$CT_ID" "$APP_SRC/requirements.txt" /opt/signage/requirements.txt
    for tmpl in "$APP_SRC"/templates/*.html; do
        [[ -f "$tmpl" ]] && pct push "$CT_ID" "$tmpl" "/opt/signage/templates/$(basename "$tmpl")"
    done
    for f in "$APP_SRC"/static/*; do
        [[ -f "$f" ]] && pct push "$CT_ID" "$f" "/opt/signage/static/$(basename "$f")"
    done

    pct exec "$CT_ID" -- systemctl restart signage
    sleep 2

    if pct exec "$CT_ID" -- systemctl is-active --quiet signage; then
        ok "Update abgeschlossen – Service läuft"
    else
        warn "Service läuft nicht nach Update – prüfe: pct enter $CT_ID && journalctl -u signage"
    fi
    exit 0
}

# ── Zusammenfassung ────────────────────────────────────────────────────────
print_summary() {
    header "✅  Digital Signage ist bereit!"

    local ct_ip
    if [[ "$CT_IP" == "dhcp" ]]; then
        ct_ip=$(pct exec "$CT_ID" -- hostname -I 2>/dev/null | awk '{print $1}')
    else
        ct_ip="${CT_IP%%/*}"
    fi
    [[ -z "$ct_ip" ]] && ct_ip="<IP-ADRESSE>"

    echo ""
    echo -e "  ${GREEN}${BOLD}════════════════════════════════════════════════════════${NC}"
    echo -e "  ${GREEN}  📋 Admin:    http://${ct_ip}:8080/admin${NC}"
    echo -e "  ${GREEN}  📺 Player:   http://${ct_ip}:8080/player${NC}"
    echo -e "  ${GREEN}  🐚 Terminal: pct enter ${CT_ID}${NC}"
    echo -e "  ${GREEN}${BOLD}════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${CYAN}So geht's weiter:${NC}"
    echo "  1. Admin-URL im Browser öffnen → Bilder/Videos hochladen"
    echo "  2. Player-URL auf Tablet/Smart-TV öffnen → Slideshow läuft"
    echo ""
}

# ── Hauptprogramm ──────────────────────────────────────────────────────────
main() {
    parse_args "$@"

    echo ""
    echo -e "  ${BOLD}🖼️  Proxmox Digital Signage – Installer${NC}"
    echo -e "  ${CYAN}https://github.com/HatchetMan111/proxmox-signage${NC}"
    echo ""

    check_prerequisites

    # Sondermodi
    if $UNINSTALL; then do_uninstall; fi
    if $STATUS_CHECK; then do_status; fi
    if $UPDATE; then download_app; update_container; fi

    # Standard: Neuinstallation
    download_app
    create_container
    setup_container
    print_summary
}

main "$@"
