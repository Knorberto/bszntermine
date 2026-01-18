# BSZN Termintool - Projektdokumentation

## Projektübersicht

Ein Doodle-ähnliches Terminfindungs-Tool für das BSZN (Berufliches Schulzentrum).

## Technologie-Stack

- **Backend:** Flask (Python)
- **Frontend:** Jinja2 Templates + HTML/CSS
- **Datenbank:** SQLite (lokal), später PostgreSQL in Docker
- **Umgebung:** Python venv

## Rollen-System (Endausbau)

| Rolle | Beschreibung | Funktionen |
|-------|--------------|------------|
| **Gast** | Kein Login erforderlich | Termine in bestehenden Umfragen buchen |
| **Nutzer** | Mit Login | Eigene Umfragen erstellen und verwalten |
| **Admin** | Mit Login | Alle Umfragen sehen, editieren, eigene erstellen |

## Entwicklungsphasen

### Phase 1 - MVP (Erledigt)
- [x] Projektdokumentation erstellen (Agent.md)
- [x] Projektstruktur anlegen
- [x] Flask-App mit SQLite aufsetzen
- [x] Einfacher Admin-Zugang mit Passwort (`admin123`)
- [x] Umfragen erstellen (als Admin) mit Kalender-Widget
- [x] Umfragen beantworten (als Gast, ohne Login)
- [x] Umfrage-Auswertung anzeigen
- [x] Konfigurierbare Optionen: Änderungen erlauben, Ablaufdatum

### Phase 2 - Benutzer-System
- [ ] Richtiges Login-System mit Passwort-Hashing
- [ ] Benutzer-Registrierung
- [ ] Nutzer-Rolle implementieren
- [ ] Admin-Rolle mit erweiterten Rechten

### Phase 3 - Docker & Produktion
- [ ] Docker-Container erstellen
- [ ] PostgreSQL statt SQLite
- [ ] Deployment-Konfiguration

## Datenbank-Schema (Phase 1)

```sql
-- Umfragen
CREATE TABLE polls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id TEXT UNIQUE NOT NULL,    -- Zufälliger Hash für öffentliche URLs
    title TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,              -- Optional: Verfallsdatum
    allow_changes BOOLEAN DEFAULT 0,   -- Dürfen Teilnehmer Antworten ändern?
    only_yes_no BOOLEAN DEFAULT 0,     -- Nur Ja/Nein (ohne Vielleicht)
    hide_participants BOOLEAN DEFAULT 0, -- Teilnehmernamen verbergen
    max_participants INTEGER,          -- Default-Limit pro Termin
    is_active BOOLEAN DEFAULT 1
);

-- Terminoptionen für eine Umfrage
CREATE TABLE poll_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id INTEGER NOT NULL,
    datetime TEXT NOT NULL,
    max_participants INTEGER,          -- Überschreibt Poll-Default wenn gesetzt
    FOREIGN KEY (poll_id) REFERENCES polls(id) ON DELETE CASCADE
);

-- Antworten/Buchungen
CREATE TABLE responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id INTEGER NOT NULL,
    option_id INTEGER NOT NULL,
    participant_name TEXT NOT NULL,
    response_type TEXT DEFAULT 'yes',  -- 'yes', 'no', 'maybe'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (poll_id) REFERENCES polls(id) ON DELETE CASCADE,
    FOREIGN KEY (option_id) REFERENCES poll_options(id) ON DELETE CASCADE
);
```

## Projektstruktur (geplant)

```
bszn-termintool/
├── app.py                 # Flask-Hauptanwendung
├── config.py              # Konfiguration
├── requirements.txt       # Python-Abhängigkeiten
├── instance/
│   └── database.db        # SQLite-Datenbank
├── templates/
│   ├── base.html          # Basis-Template
│   ├── index.html         # Startseite
│   ├── admin/
│   │   ├── login.html     # Admin-Login
│   │   ├── dashboard.html # Admin-Dashboard
│   │   └── create_poll.html # Umfrage erstellen
│   └── poll/
│       ├── view.html      # Umfrage anzeigen & beantworten
│       └── results.html   # Ergebnisse anzeigen
└── static/
    └── style.css          # CSS-Styles
```

## API-Endpunkte (Phase 1)

| Route | Methode | Beschreibung |
|-------|---------|--------------|
| `/` | GET | Startseite mit Liste aktiver Umfragen |
| `/admin/login` | GET, POST | Admin-Login (Passwort: admin123) |
| `/admin/dashboard` | GET | Admin-Dashboard mit allen Umfragen |
| `/admin/poll/create` | GET, POST | Neue Umfrage erstellen |
| `/admin/poll/<id>/edit` | GET, POST | Umfrage bearbeiten |
| `/admin/poll/<id>/delete` | POST | Umfrage löschen |
| `/poll/<id>` | GET | Umfrage anzeigen |
| `/poll/<id>/respond` | POST | Auf Umfrage antworten |
| `/poll/<id>/results` | GET | Ergebnisse anzeigen |

## Geklärte Anforderungen

| Frage | Entscheidung |
|-------|--------------|
| Antworten ändern? | Konfigurierbar pro Umfrage (beim Erstellen festlegen) |
| Terminauswahl UI? | Kalender-Widget (visueller Datepicker) |
| Verfallsdatum? | Optional pro Umfrage (beim Erstellen festlegen) |
| Nur Ja/Nein? | Konfigurierbar pro Umfrage (ohne "Vielleicht"-Option) |
| Namen verbergen? | Konfigurierbar pro Umfrage (Teilnehmer sehen keine anderen Namen, Admin sieht alles) |
| Max. Teilnehmer? | Konfigurierbar als Default pro Umfrage + individuell pro Termin überschreibbar |
| Umfrage-IDs? | Zufällige 8-Zeichen-Hashes statt durchnummerierter IDs (nicht erratbar) |
| Termin-Wizard? | Drei Modi: Wöchentlich, Täglich, Zeitslots - generiert Termine automatisch |
| E-Mail-Benachrichtigung? | Später (nicht in Phase 1) |

## Schnellstart

```bash
# venv aktivieren und App starten
source venv/bin/activate
python app.py
```

Die App läuft dann unter http://127.0.0.1:5000

- **Startseite:** Liste aller aktiven Umfragen
- **Admin-Login:** http://127.0.0.1:5000/admin/login (Passwort: `admin123`)
- **Admin-Dashboard:** Umfragen erstellen, bearbeiten, löschen

## Nächste Schritte (Phase 2)

1. Richtiges Login-System mit Passwort-Hashing
2. Benutzer-Registrierung
3. Nutzer-/Admin-Rollen mit Berechtigungen

---

*Letzte Aktualisierung: 18.01.2026*
