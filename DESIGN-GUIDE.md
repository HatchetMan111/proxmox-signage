# 🎨 Design-Guide für Signage-Inhalte

Kurzanleitung für alle, die Bilder/Videos für den Signage-Screen gestalten – z. B. in Canva, Photoshop oder PowerPoint. Kein technisches Wissen nötig, nur diese Punkte beachten.

---

## 1. Zuerst: Bildschirm-Format herausfinden

Bevor du irgendwas gestaltest, schau dir kurz den tatsächlichen Bildschirm an (Tablet, TV), auf dem die Inhalte laufen. Das bestimmt die Leinwandgröße in Canva.

| Aufstellung | Leinwandgröße in Canva | Seitenverhältnis |
|---|---|---|
| **Querformat** – TV/Monitor an der Wand | `1920 x 1080 px` | 16:9 |
| **Hochformat** – Tablet im Schaufenster, Stele | `1080 x 1920 px` | 9:16 |
| **Quadratisch** – Insta-Style-Display | `1080 x 1080 px` | 1:1 |

⚠️ **Wichtig:** Immer die exakte Auflösung/Seitenverhältnis des Ziel-Bildschirms verwenden. Manche Tablets sind nicht klassisch 16:9 – im Zweifel kurz nachmessen bzw. in den Geräte-Einstellungen nachschauen, nicht raten. Passt das Format nicht exakt, entstehen schwarze Balken oben/unten oder links/rechts (der Player beschneidet nichts, sondern setzt Bilder immer proportional ein).

---

## 2. Canva einrichten (einmalig)

1. Canva öffnen → **"Leere Design erstellen"**
2. Oben rechts auf die Maßeinheit/Größe klicken → **"Benutzerdefinierte Größe"**
3. Breite/Höhe aus der Tabelle oben eintragen (z. B. `1920 x 1080 px`)
4. Tipp: Dieses Design als **Vorlage/Team-Ordner** speichern, damit jede neue Datei automatisch die richtige Größe hat.

---

## 3. Sicherheitsabstand für die Uhr-Anzeige

Der Player zeigt standardmäßig eine kleine Uhr **unten rechts** im Bild an (halbtransparent, weiß). Wenn dort wichtige Design-Elemente oder eine helle/weiße Fläche liegen, wird entweder die Uhr unleserlich oder sie stört dein Design.

```
┌──────────────────────────────────┐
│                                   │
│                                   │
│         DEIN DESIGN HIER         │
│                                   │
│                                   │
│                       🕐 12:34   │  ← ca. 300×150 px
└──────────────────────────────────┘    unten rechts freihalten
```

Faustregel: unteres rechtes Sechstel des Bildes eher ruhig/dunkel halten, keine wichtigen Texte oder Logos dort platzieren. (Falls die Uhr in den Einstellungen deaktiviert ist, spielt das keine Rolle.)

---

## 4. Datei-Format & Größe

### Bilder
| Format | Wann verwenden |
|---|---|
| **JPG** | Fotos, Angebote mit Bildern – kleine Dateigröße |
| **PNG** | Grafiken mit Text, Logos, transparenten Flächen |

Export-Qualität in Canva: **"Mittel"** reicht für Bildschirm-Darstellung völlig aus (spart Speicherplatz, ohne sichtbaren Qualitätsverlust). Auch unterstützt: GIF, WebP, BMP.

### Videos
- **MP4** exportieren (Canva macht das automatisch beim Video-Download) – läuft in jedem Browser zuverlässig. WebM und MOV funktionieren ebenfalls.
- Videos werden **ohne Ton** abgespielt (technische Notwendigkeit für Autoplay im Browser). Wichtige Infos also nie nur per Sprache vermitteln – immer auch als Text/visuell zeigen.
- Realistische Dateigröße für 1920×1080: ein 20–30-Sekunden-Clip landet meist bei 10–30 MB. Technisches Limit sind 500 MB, aber deutlich kleinere Dateien laden schneller und sparen Speicherplatz auf dem Server.

---

## 5. Damit der Screen auch wirkt

- **Groß schreiben.** Faustregel: mindestens 1 cm Buchstabenhöhe pro 3 m Betrachtungsabstand. Lieber zu groß als zu klein – Leute lesen im Vorbeigehen, nicht am Schreibtisch.
- **Starker Kontrast.** Helle Schrift auf dunklem Grund (oder umgekehrt), kein hellgrau auf weiß – das wirkt am Bildschirm schnell verwaschen.
- **Eine Kernaussage pro Slide.** Kein Fließtext, kein Absatz. Ein Angebot, ein Bild, ein Satz.
- **Nicht überladen.** Ein klarer Blickfang statt einer Collage aus fünf Elementen.
- **Genug Zeit einplanen.** Die Standard-Anzeigedauer ist 8 Sekunden pro Bild. Braucht ein Slide mehr Lesezeit (z. B. viel Text), kann die Anzeigedauer in den Admin-Einstellungen individuell hochgesetzt werden – lieber das anpassen, als Text zu klein zu quetschen.

---

## 6. Checkliste vor dem Hochladen

- [ ] Leinwandgröße entspricht dem Ziel-Bildschirm (siehe Tabelle oben)
- [ ] Unten rechts (Uhr-Bereich) ist frei von wichtigen Elementen
- [ ] Export als JPG/PNG (Bild) oder MP4 (Video), Qualität "Mittel"
- [ ] Wichtige Infos stehen als Text im Bild, nicht nur gesprochen im Video
- [ ] Schrift groß und kontrastreich genug für Blickdistanz im Raum
- [ ] Nur eine Kernaussage pro Slide

---

## 7. Häufige Fehler

| Fehler | Auswirkung |
|---|---|
| Design in "irgendeiner" Größe statt exaktem Seitenverhältnis | Schwarze Balken auf dem Screen |
| Zu kleine Schrift ("sieht am Laptop gut aus") | Am Screen aus 3+ Metern nicht lesbar |
| Wichtiger Text unten rechts platziert | Überlagert von der Uhr-Anzeige |
| Maximale Canva-Export-Qualität für jedes Bild | Unnötig große Dateien, langsamere Ladezeit |
| Viel Fließtext auf einem Slide | Niemand liest das in 8 Sekunden fertig |

---

*Technische Details zum Betrieb des Signage-Systems: siehe [README.md](README.md).*
