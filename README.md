# 🖼️ Proxmox Digital Signage

> **Schlanker Digital-Signage-Server** für Proxmox LXC.  
> Bilder & Videos hochladen – auf Tablets/Smart-TVs anzeigen.  
> **Keine Cloud, keine Abos, kein Vendor-Lock-in.**

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Supports aarch64 Architecture](https://img.shields.io/badge/aarch64-yes-green.svg)]()
[![Supports amd64 Architecture](https://img.shields.io/badge/amd64-yes-green.svg)]()

---

## 📺 Use-Case

Du betreibst ein **kleines Unternehmen** (Café, Laden, Friseur, Praxis) und willst:

- **Werbung / Angebote** auf einem Tablet oder Smart-TV zeigen?
- **Produktbilder** oder **kurze Videos** präsentieren?
- Den Content **einfach selbst aktualisieren** – ohne Agentur, ohne teure Software?

**Dann ist dieses Projekt genau richtig.** Ein Einzeiler auf deinem Proxmox-Server, und du hast einen eigenen Digital-Signage-Server – komplett lokal, DSGVO-konform, und für immer kostenlos.

---

## ✨ Features

| Feature | Beschreibung |
|---|---|
| 📤 **Drag-&-Drop-Upload** | Bilder (JPG, PNG, GIF, WebP) & Videos (MP4, WebM, MOV) per Admin-UI |
| 📋 **Playlist-Editor** | Reihenfolge per Drag&Drop, Dauer pro Bild, Shuffle-Modus |
| ✍️ **Text-Slides** | Schnelle Textmeldungen ("Heute geschlossen") direkt im Admin erstellen – ohne Canva/Design-Tool |
| ⏰ **Zeitsteuerung** | Wochentage & Uhrzeitfenster pro Element (z. B. Frühstückskarte nur Mo–Fr 7–11 Uhr) |
| 📅 **Ablaufdatum** | Zeitlich befristete Inhalte fallen automatisch aus der Wiedergabe, sobald abgelaufen |
| 🎬 **Fullscreen-Player** | Automatische Slideshow mit Überblend-Effekten (Fade / Slide) |
| 🎞️ **Ken-Burns-Effekt** | Optionales sanftes Zoomen bei Standbildern für mehr Lebendigkeit |
| 🖥️ **Split-Screen-Layouts** | Bildschirm in Bereiche teilen (Haupt + Ticker/Seitenleiste/2er-Split), jeder Bereich mit eigener unabhängiger Wiedergabe |
| 📺 **Jeder Browser** | Läuft auf Tablet, Smart-TV, Handy, Laptop – kein App-Store nötig |
| 🕐 **Live-Uhr** | Optional: Datum + Uhrzeit im Player |
| 🔧 **REST-API** | Alles programmierbar – für Automationen & eigene Tools |
| 🐧 **Proxmox LXC** | Minimaler Container (128–256 MB RAM, 1 CPU, 2 GB Disk) |
| 🚀 **Ein-Befehl-Install** | `bash <(curl -s ...)` auf deinem Proxmox-Host – fertig |

---

## 🚀 Quick Start

### 1. Auf Proxmox installieren (als root)

```bash
bash <(curl -s https://raw.githubusercontent.com/HatchetMan111/proxmox-signage/main/install-signage.sh)
```

Nach ca. **2 Minuten** erhältst du zwei URLs:

```
Admin:  http://192.168.x.y:8080/admin
Player: http://192.168.x.y:8080/player
```

### 2. Medien hochladen

👉 **Admin-URL** im Browser öffnen → Bilder/Videos per Drag & Drop in die Upload-Zone ziehen.

> 💡 Tipp: Bevor du Inhalte gestaltest (z. B. in Canva) – kurz den **[Design-Guide](DESIGN-GUIDE.md)** checken, damit Auflösung & Format zum Bildschirm passen.

![Admin-UI Screenshot](https://via.placeholder.com/800x450/1a1a2e/ffffff?text=Admin-Oberflaeche)

### 3. Auf dem Tablet / TV anzeigen

👉 **Player-URL** auf dem Tablet (oder Smart-TV im Browser) öffnen → **Vollbild** → fertig.

Tipp für Android-Tablets: [Fully Kiosk Browser](https://www.fully-kiosk.com/) oder den integrierten Browser im Kiosk-Modus nutzen.

---

## 📦 Manuelle Installation

```bash
# 1. Repository klonen
git clone https://github.com/HatchetMan111/proxmox-signage.git
cd proxmox-signage

# 2. Installations-Script ausführen
chmod +x install-signage.sh
sudo bash install-signage.sh

# Mit eigenen Optionen:
sudo bash install-signage.sh --id 220 --memory 512 --ip 192.168.1.100/24
```

### Optionen für `install-signage.sh`

| Argument | Default | Beschreibung |
|---|---|---|
| `--id` | `210` | LXC-Container-ID |
| `--hostname` | `signage` | Hostname des Containers |
| `--memory` | `256` | RAM in MB |
| `--storage` | `local-lvm` | Proxmox Storage-Pool |
| `--rootfs` | `2` | RootFS-Größe in GB |
| `--cores` | `1` | CPU-Kerne |
| `--ip` | `dhcp` | Statische IP (z. B. `192.168.1.100/24`) oder DHCP |
| `--password` | `signage` | Root-Passwort des Containers |
| `--bridge` | `vmbr0` | Netzwerk-Bridge |
| `--help` | – | Hilfe anzeigen |

---

## 🎮 Nutzung

### Admin-Oberfläche (`/admin`)

| Bereich | Funktion |
|---|---|
| **Upload-Zone** | Bilder/Videos per Drag & Drop oder Klick hochladen |
| **Text-Slide erstellen** | Textmeldung mit Farbe & Icon direkt erzeugen, ohne externes Tool |
| **Medien-Galerie** | Alle Inhalte mit Vorschau, Sortieren per Drag&Drop |
| **⏰ Zeitplan** | Pro Element: Wochentage, Uhrzeitfenster, Ablaufdatum, Bereich (bei Split-Layouts) festlegen |
| **🖥️ Layout** | Vollbild / Haupt+Ticker / Haupt+Seitenleiste / 2er-Split per Klick wählen |
| **Einstellungen** | Anzeigedauer, Übergangseffekt, Shuffle, Uhr, Ken-Burns-Effekt |
| **Player-URL** | Wird automatisch angezeigt – einfach kopieren |

### Player (`/player`)

- Vollbild-Slideshow mit CSS-Übergängen (Fade / Slide)
- Videos werden automatisch abgespielt und nahtlos eingebunden
- Text-Slides und zeitlich gesteuerte Inhalte werden automatisch berücksichtigt
- Live-Uhr (optional) unten rechts
- Läuft auf **jedem** Gerät mit modernem Browser

### REST-API

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/media` | Alle Medien abrufen |
| `POST` | `/api/upload` | Datei hochladen (multipart/form-data) |
| `DELETE` | `/api/media/<id>` | Datei oder Text-Slide löschen |
| `POST` | `/api/text-slide` | Text-Slide erstellen |
| `PUT` | `/api/text-slide/<id>` | Text-Slide bearbeiten |
| `PUT` | `/api/schedule/<id>` | Zeitplan/Ablaufdatum/Bereich (`zone: "main"\|"secondary"`) setzen |
| `DELETE` | `/api/schedule/<id>` | Zeitplan entfernen |
| `GET` | `/api/playlist` | Aktuelle Playlist + Config abrufen |
| `PUT` | `/api/playlist` | Config aktualisieren (JSON) |
| `GET` | `/api/player/next` | Nächste Medien-Items (für Player-JS) |

---

## 🎨 Design-Richtlinien für Inhalte

Damit Bilder/Videos auf dem Screen gut aussehen (richtige Auflösung, kein Beschnitt, lesbar auf Distanz), gibt es einen eigenen Guide für alle, die Inhalte gestalten (z. B. in Canva) – auch ohne technisches Vorwissen:

👉 **[DESIGN-GUIDE.md](DESIGN-GUIDE.md)**

Kurzfassung:

| Aufstellung | Canva-Leinwandgröße |
|---|---|
| Querformat (TV/Monitor) | `1920 x 1080 px` |
| Hochformat (Tablet) | `1080 x 1920 px` |

Der Player beschneidet Bilder nie – bei falschem Seitenverhältnis entstehen stattdessen Balken. Die Hintergrundfarbe/-bild in den Admin-Einstellungen kann das kaschieren. Details, Sicherheitsabstände (Uhr-Overlay unten rechts) und Datei-Empfehlungen: siehe Guide.

---

## 📁 Projekt-Struktur

```
proxmox-signage/
├── LICENSE                 ← MIT-Lizenz
├── README.md               ← Diese Datei
├── DESIGN-GUIDE.md         ← 🎨 Design-Richtlinien für Content-Ersteller
├── .gitignore              ← Git-Ignore-Regeln
├── install-signage.sh      ← 🔧 Proxmox Install-Script (Haupt-Deliverable)
└── signage-app/            ← 🐍 Flask-Web-App
    ├── app.py              ← Server mit allen API-Routen
    ├── requirements.txt    ← Python-Abhängigkeiten
    ├── media/              ← 📂 Hochgeladene Medien (wird beim Betrieb befüllt)
    ├── static/
    │   └── style.css
    └── templates/
        ├── admin.html      ← Admin-Oberfläche
        └── player.html     ← Fullscreen-Player
```

---

## 🧪 Lokale Entwicklung (ohne Proxmox)

```bash
cd signage-app
pip install -r requirements.txt
python3 app.py
# → http://localhost:8080/admin
```

---

## 🛡️ Lizenz

[MIT](LICENSE) © 2026 HatchetMan111

Du darfst das Projekt **frei nutzen, verändern, weitergeben und kommerziell einsetzen** – einzige Bedingung: Der Lizenzhinweis muss erhalten bleiben.

---

## 💡 FAQ

**Brauche ich eine Internetverbindung zum Betreiben?**  
Nur für die Installation (Paket-Download). Danach läuft alles lokal.

**Kann ich mehrere Player gleichzeitig bespielen?**  
Ja – jeder Player öffnet dieselbe URL. Änderungen an der Playlist sind sofort sichtbar.

**Welche Formate werden unterstützt?**  
Bilder: JPG, PNG, GIF, WebP, BMP. Videos: MP4 (empfohlen), WebM, MOV.

**Wie groß darf eine Datei sein?**  
Maximal 500 MB pro Datei.

**Läuft das auch ohne Proxmox?**  
Ja – die Web-App ist reines Python/Flask und läuft auf jedem Linux-Server, Raspberry Pi, oder Docker-Container. Das Install-Script ist auf Proxmox optimiert, aber die `signage-app/` ist universell.
