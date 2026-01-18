from flask import Flask, render_template, request, redirect, url_for, session, flash, g
import sqlite3
import secrets
from datetime import datetime
from functools import wraps
from config import Config

app = Flask(__name__)
app.config.from_object(Config)


# ==================== Hilfsfunktionen ====================

def generate_public_id(length=8):
    """Generiert eine zufällige öffentliche ID für Umfragen."""
    return secrets.token_urlsafe(length)[:length]


# ==================== Datenbank ====================

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS polls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            allow_changes BOOLEAN DEFAULT 0,
            only_yes_no BOOLEAN DEFAULT 0,
            hide_participants BOOLEAN DEFAULT 0,
            max_participants INTEGER,
            is_active BOOLEAN DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS poll_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            poll_id INTEGER NOT NULL,
            datetime TEXT NOT NULL,
            max_participants INTEGER,
            FOREIGN KEY (poll_id) REFERENCES polls(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            poll_id INTEGER NOT NULL,
            option_id INTEGER NOT NULL,
            participant_name TEXT NOT NULL,
            response_type TEXT DEFAULT 'yes',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (poll_id) REFERENCES polls(id) ON DELETE CASCADE,
            FOREIGN KEY (option_id) REFERENCES poll_options(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS poll_resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            poll_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            FOREIGN KEY (poll_id) REFERENCES polls(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS matrix_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            poll_id INTEGER NOT NULL,
            resource_id INTEGER NOT NULL,
            option_id INTEGER NOT NULL,
            participant_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (poll_id) REFERENCES polls(id) ON DELETE CASCADE,
            FOREIGN KEY (resource_id) REFERENCES poll_resources(id) ON DELETE CASCADE,
            FOREIGN KEY (option_id) REFERENCES poll_options(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_polls_public_id ON polls(public_id);
    ''')
    ensure_column('polls', 'poll_type', "TEXT DEFAULT 'standard'")
    ensure_column('polls', 'resource_label', 'TEXT')
    ensure_column('polls', 'allow_multi_bookings', 'BOOLEAN DEFAULT 0')
    db.commit()


@app.cli.command('init-db')
def init_db_command():
    init_db()
    print('Datenbank initialisiert.')


def get_poll_by_public_id(public_id):
    """Holt eine Umfrage anhand der öffentlichen ID."""
    db = get_db()
    return db.execute('SELECT * FROM polls WHERE public_id = ?', (public_id,)).fetchone()


def get_option_booking_count(option_id):
    """Zählt die Anzahl der 'yes' Buchungen für eine Option."""
    db = get_db()
    result = db.execute('''
        SELECT COUNT(*) as count FROM responses
        WHERE option_id = ? AND response_type = 'yes'
    ''', (option_id,)).fetchone()
    return result['count'] if result else 0


def get_option_max_participants(option, poll):
    """Ermittelt die max. Teilnehmerzahl für eine Option (Option überschreibt Poll-Default)."""
    if option['max_participants'] is not None:
        return option['max_participants']
    return poll['max_participants']


def ensure_column(table, column, definition):
    db = get_db()
    columns = db.execute(f'PRAGMA table_info({table})').fetchall()
    if column not in [c['name'] for c in columns]:
        db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')


def get_poll_resources(poll_id):
    db = get_db()
    return db.execute(
        'SELECT * FROM poll_resources WHERE poll_id = ? ORDER BY sort_order, id',
        (poll_id,)
    ).fetchall()


def get_matrix_booking_counts(poll_id):
    db = get_db()
    rows = db.execute('''
        SELECT resource_id, option_id, COUNT(*) as count
        FROM matrix_responses
        WHERE poll_id = ?
        GROUP BY resource_id, option_id
    ''', (poll_id,)).fetchall()
    counts = {}
    for row in rows:
        counts[(row['resource_id'], row['option_id'])] = row['count']
    return counts


# ==================== Auth Helper ====================

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


# ==================== Öffentliche Routen ====================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/poll/<public_id>')
def view_poll(public_id):
    poll = get_poll_by_public_id(public_id)
    if not poll:
        flash('Umfrage nicht gefunden.', 'error')
        return redirect(url_for('index'))

    db = get_db()
    options = db.execute(
        'SELECT * FROM poll_options WHERE poll_id = ? ORDER BY datetime',
        (poll['id'],)
    ).fetchall()

    # Prüfen ob abgelaufen
    is_expired = False
    if poll['expires_at']:
        expires = datetime.fromisoformat(poll['expires_at'])
        is_expired = expires < datetime.now()

    if poll['poll_type'] == 'matrix':
        resources = get_poll_resources(poll['id'])
        booking_counts = get_matrix_booking_counts(poll['id'])
        cell_info = {}
        for res in resources:
            cell_info[res['id']] = {}
            for opt in options:
                booked = booking_counts.get((res['id'], opt['id']), 0)
                max_p = get_option_max_participants(opt, poll)
                cell_info[res['id']][opt['id']] = {
                    'booked': booked,
                    'max': max_p,
                    'available': (max_p - booked) if max_p else None,
                    'is_full': (booked >= max_p) if max_p else False
                }
        return render_template(
            'poll/view_matrix.html',
            poll=poll,
            options=options,
            resources=resources,
            cell_info=cell_info,
            is_expired=is_expired
        )

    # Buchungszahlen und Limits pro Option berechnen
    option_info = {}
    for opt in options:
        booked = get_option_booking_count(opt['id'])
        max_p = get_option_max_participants(opt, poll)
        option_info[opt['id']] = {
            'booked': booked,
            'max': max_p,
            'available': (max_p - booked) if max_p else None,
            'is_full': (booked >= max_p) if max_p else False
        }

    return render_template(
        'poll/view.html',
        poll=poll,
        options=options,
        option_info=option_info,
        is_expired=is_expired
    )


@app.route('/poll/<public_id>/respond', methods=['POST'])
def respond_poll(public_id):
    poll = get_poll_by_public_id(public_id)

    if not poll or not poll['is_active']:
        flash('Umfrage nicht verfügbar.', 'error')
        return redirect(url_for('index'))

    db = get_db()

    # Prüfen ob abgelaufen
    if poll['expires_at']:
        expires = datetime.fromisoformat(poll['expires_at'])
        if expires < datetime.now():
            flash('Diese Umfrage ist abgelaufen.', 'error')
            return redirect(url_for('view_poll', public_id=public_id))

    participant_name = request.form.get('participant_name', '').strip()
    if not participant_name:
        flash('Bitte gib deinen Namen ein.', 'error')
        return redirect(url_for('view_poll', public_id=public_id))

    if poll['poll_type'] == 'matrix':
        resources = get_poll_resources(poll['id'])
        options = db.execute(
            'SELECT * FROM poll_options WHERE poll_id = ? ORDER BY datetime',
            (poll['id'],)
        ).fetchall()

        existing_bookings = db.execute('''
            SELECT resource_id, option_id FROM matrix_responses
            WHERE poll_id = ? AND participant_name = ?
        ''', (poll['id'], participant_name)).fetchall()
        has_existing = len(existing_bookings) > 0

        if has_existing and not poll['allow_changes']:
            flash('Du hast bereits gebucht. Änderungen sind bei dieser Umfrage nicht erlaubt.', 'error')
            return redirect(url_for('view_poll', public_id=public_id))

        existing_pairs = {(row['resource_id'], row['option_id']) for row in existing_bookings}

        selections = []
        if poll['allow_multi_bookings']:
            for res in resources:
                for opt in options:
                    field = f'cell_{res["id"]}_{opt["id"]}'
                    if request.form.get(field):
                        selections.append((res['id'], opt['id']))
        else:
            for res in resources:
                selected_option = request.form.get(f'resource_{res["id"]}', '').strip()
                if selected_option:
                    try:
                        opt_id = int(selected_option)
                    except ValueError:
                        continue
                    selections.append((res['id'], opt_id))

        option_counts = {}
        for res_id, opt_id in selections:
            option_counts[opt_id] = option_counts.get(opt_id, 0) + 1
        if any(count > 1 for count in option_counts.values()):
            flash('Du kannst pro Zeitpunkt nur eine Ressource auswählen.', 'error')
            return redirect(url_for('view_poll', public_id=public_id))

        booking_counts = get_matrix_booking_counts(poll['id'])

        # Kapazitäten prüfen
        for res_id, opt_id in selections:
            option = next((o for o in options if o['id'] == opt_id), None)
            if not option:
                continue
            max_p = get_option_max_participants(option, poll)
            if max_p:
                current_bookings = booking_counts.get((res_id, opt_id), 0)
                if (res_id, opt_id) in existing_pairs:
                    current_bookings -= 1
                if current_bookings >= max_p:
                    flash('Ein ausgewählter Termin ist leider bereits ausgebucht.', 'error')
                    return redirect(url_for('view_poll', public_id=public_id))

        if has_existing and poll['allow_changes']:
            db.execute(
                'DELETE FROM matrix_responses WHERE poll_id = ? AND participant_name = ?',
                (poll['id'], participant_name)
            )

        for res_id, opt_id in selections:
            db.execute('''
                INSERT INTO matrix_responses (poll_id, resource_id, option_id, participant_name)
                VALUES (?, ?, ?, ?)
            ''', (poll['id'], res_id, opt_id, participant_name))

        db.commit()
        flash('Deine Buchung wurde gespeichert!', 'success')
        return redirect(url_for('poll_results', public_id=public_id))

    # Prüfen ob Änderungen erlaubt sind oder neue Antwort
    existing = db.execute(
        'SELECT * FROM responses WHERE poll_id = ? AND participant_name = ?',
        (poll['id'], participant_name)
    ).fetchone()

    if existing and not poll['allow_changes']:
        flash('Du hast bereits abgestimmt. Änderungen sind bei dieser Umfrage nicht erlaubt.', 'error')
        return redirect(url_for('view_poll', public_id=public_id))

    # Optionen holen
    options = db.execute('SELECT * FROM poll_options WHERE poll_id = ?', (poll['id'],)).fetchall()

    # Prüfen ob Limits eingehalten werden (vor dem Löschen alter Antworten)
    for option in options:
        response_type = request.form.get(f'option_{option["id"]}', 'no')
        if response_type == 'yes':
            max_p = get_option_max_participants(option, poll)
            if max_p:
                current_bookings = get_option_booking_count(option['id'])
                # Wenn der Benutzer bereits gebucht hat, zählt seine Buchung nicht mit
                if existing:
                    old_response = db.execute('''
                        SELECT response_type FROM responses
                        WHERE poll_id = ? AND option_id = ? AND participant_name = ?
                    ''', (poll['id'], option['id'], participant_name)).fetchone()
                    if old_response and old_response['response_type'] == 'yes':
                        current_bookings -= 1
                if current_bookings >= max_p:
                    flash(f'Der Termin "{option["datetime"]}" ist leider bereits ausgebucht.', 'error')
                    return redirect(url_for('view_poll', public_id=public_id))

    # Alte Antworten löschen wenn Änderungen erlaubt
    if existing and poll['allow_changes']:
        db.execute(
            'DELETE FROM responses WHERE poll_id = ? AND participant_name = ?',
            (poll['id'], participant_name)
        )

    # Neue Antworten speichern
    for option in options:
        response_type = request.form.get(f'option_{option["id"]}', 'no')
        if response_type in ['yes', 'maybe', 'no']:
            db.execute('''
                INSERT INTO responses (poll_id, option_id, participant_name, response_type)
                VALUES (?, ?, ?, ?)
            ''', (poll['id'], option['id'], participant_name, response_type))

    db.commit()
    flash('Deine Antwort wurde gespeichert!', 'success')
    return redirect(url_for('poll_results', public_id=public_id))


@app.route('/poll/<public_id>/results')
def poll_results(public_id):
    poll = get_poll_by_public_id(public_id)
    if not poll:
        flash('Umfrage nicht gefunden.', 'error')
        return redirect(url_for('index'))

    db = get_db()
    options = db.execute(
        'SELECT * FROM poll_options WHERE poll_id = ? ORDER BY datetime',
        (poll['id'],)
    ).fetchall()

    if poll['poll_type'] == 'matrix':
        resources = get_poll_resources(poll['id'])
        rows = db.execute('''
            SELECT resource_id, option_id, participant_name
            FROM matrix_responses
            WHERE poll_id = ?
            ORDER BY participant_name
        ''', (poll['id'],)).fetchall()

        participants = db.execute('''
            SELECT DISTINCT participant_name FROM matrix_responses
            WHERE poll_id = ?
            ORDER BY participant_name
        ''', (poll['id'],)).fetchall()

        option_limits = {}
        for opt in options:
            option_limits[opt['id']] = get_option_max_participants(opt, poll)

        cell_entries = {}
        for res in resources:
            cell_entries[res['id']] = {}
            for opt in options:
                cell_entries[res['id']][opt['id']] = []

        for row in rows:
            cell_entries[row['resource_id']][row['option_id']].append(row['participant_name'])

        return render_template(
            'poll/results_matrix.html',
            poll=poll,
            options=options,
            resources=resources,
            participants=participants,
            cell_entries=cell_entries,
            option_limits=option_limits
        )

    # Alle Teilnehmer
    participants = db.execute('''
        SELECT DISTINCT participant_name FROM responses WHERE poll_id = ?
        ORDER BY participant_name
    ''', (poll['id'],)).fetchall()

    # Antworten als Dictionary strukturieren
    responses_dict = {}
    for p in participants:
        name = p['participant_name']
        responses_dict[name] = {}
        for opt in options:
            response = db.execute('''
                SELECT response_type FROM responses
                WHERE poll_id = ? AND option_id = ? AND participant_name = ?
            ''', (poll['id'], opt['id'], name)).fetchone()
            responses_dict[name][opt['id']] = response['response_type'] if response else 'no'

    # Zusammenfassung und Limits pro Option
    option_summary = {}
    for opt in options:
        counts = db.execute('''
            SELECT response_type, COUNT(*) as count FROM responses
            WHERE poll_id = ? AND option_id = ?
            GROUP BY response_type
        ''', (poll['id'], opt['id'])).fetchall()
        max_p = get_option_max_participants(opt, poll)
        option_summary[opt['id']] = {
            'yes': 0, 'maybe': 0, 'no': 0,
            'max': max_p
        }
        for c in counts:
            option_summary[opt['id']][c['response_type']] = c['count']

    return render_template('poll/results.html',
                         poll=poll,
                         options=options,
                         participants=participants,
                         responses=responses_dict,
                         summary=option_summary)


# ==================== Admin Routen ====================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == app.config['ADMIN_PASSWORD']:
            session['is_admin'] = True
            flash('Erfolgreich eingeloggt!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Falsches Passwort.', 'error')
    return render_template('admin/login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    flash('Ausgeloggt.', 'success')
    return redirect(url_for('index'))


@app.route('/admin')
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    db = get_db()
    polls = db.execute('SELECT * FROM polls ORDER BY created_at DESC').fetchall()
    return render_template('admin/dashboard.html', polls=polls)


@app.route('/admin/poll/create', methods=['GET', 'POST'])
@admin_required
def create_poll():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        allow_changes = request.form.get('allow_changes') == 'on'
        only_yes_no = request.form.get('only_yes_no') == 'on'
        hide_participants = request.form.get('hide_participants') == 'on'
        expires_at = request.form.get('expires_at', '').strip() or None
        max_participants_str = request.form.get('max_participants', '').strip()
        max_participants = int(max_participants_str) if max_participants_str else None
        poll_type = request.form.get('poll_type', 'standard')
        resource_label = request.form.get('resource_label', '').strip() or 'Ressourcen'
        allow_multi_bookings = request.form.get('allow_multi_bookings') == 'on'

        if poll_type == 'matrix':
            only_yes_no = False
            if max_participants is None:
                max_participants = 1

        if not title:
            flash('Titel ist erforderlich.', 'error')
            return render_template('admin/create_poll.html')

        # Termine aus dem Formular holen
        dates = request.form.getlist('option_date[]')
        times = request.form.getlist('option_time[]')
        max_parts = request.form.getlist('option_max[]')

        options = []
        for i, date in enumerate(dates):
            if date:
                time = times[i] if i < len(times) else ''
                max_p = max_parts[i] if i < len(max_parts) else ''
                dt_str = f"{date} {time}" if time else date
                opt_max = int(max_p) if max_p else None
                options.append((dt_str, opt_max))

        if not options:
            flash('Mindestens ein Termin ist erforderlich.', 'error')
            return render_template('admin/create_poll.html')

        resources = []
        if poll_type == 'matrix':
            resource_names = request.form.getlist('resource_name[]')
            for name in resource_names:
                clean = name.strip()
                if clean:
                    resources.append(clean)
            if not resources:
                flash('Mindestens eine Ressource ist erforderlich.', 'error')
                return render_template('admin/create_poll.html')

        # Eindeutige public_id generieren
        public_id = generate_public_id()
        db = get_db()
        while db.execute('SELECT id FROM polls WHERE public_id = ?', (public_id,)).fetchone():
            public_id = generate_public_id()

        cursor = db.execute('''
            INSERT INTO polls (public_id, title, description, allow_changes, only_yes_no,
                             hide_participants, max_participants, expires_at, poll_type,
                             resource_label, allow_multi_bookings)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (public_id, title, description, allow_changes, only_yes_no,
              hide_participants, max_participants, expires_at, poll_type,
              resource_label, allow_multi_bookings))
        poll_id = cursor.lastrowid

        for dt_str, opt_max in options:
            db.execute(
                'INSERT INTO poll_options (poll_id, datetime, max_participants) VALUES (?, ?, ?)',
                (poll_id, dt_str, opt_max)
            )

        if poll_type == 'matrix':
            for idx, name in enumerate(resources):
                db.execute(
                    'INSERT INTO poll_resources (poll_id, name, sort_order) VALUES (?, ?, ?)',
                    (poll_id, name, idx)
                )

        db.commit()
        flash(f'Umfrage erfolgreich erstellt! Link: /poll/{public_id}', 'success')
        return redirect(url_for('admin_dashboard'))

    return render_template('admin/create_poll.html')


@app.route('/admin/poll/<int:poll_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_poll(poll_id):
    db = get_db()
    poll = db.execute('SELECT * FROM polls WHERE id = ?', (poll_id,)).fetchone()
    if not poll:
        flash('Umfrage nicht gefunden.', 'error')
        return redirect(url_for('admin_dashboard'))

    options = db.execute(
        'SELECT * FROM poll_options WHERE poll_id = ? ORDER BY datetime',
        (poll_id,)
    ).fetchall()
    resources = get_poll_resources(poll_id) if poll['poll_type'] == 'matrix' else []

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        allow_changes = request.form.get('allow_changes') == 'on'
        only_yes_no = request.form.get('only_yes_no') == 'on'
        hide_participants = request.form.get('hide_participants') == 'on'
        is_active = request.form.get('is_active') == 'on'
        expires_at = request.form.get('expires_at', '').strip() or None
        max_participants_str = request.form.get('max_participants', '').strip()
        max_participants = int(max_participants_str) if max_participants_str else None
        resource_label = request.form.get('resource_label', '').strip() or 'Ressourcen'
        allow_multi_bookings = request.form.get('allow_multi_bookings') == 'on'

        if not title:
            flash('Titel ist erforderlich.', 'error')
            return render_template('admin/edit_poll.html', poll=poll, options=options, resources=resources)

        if poll['poll_type'] == 'matrix':
            only_yes_no = False
            if max_participants is None:
                max_participants = 1

        db.execute('''
            UPDATE polls SET title = ?, description = ?, allow_changes = ?,
            only_yes_no = ?, hide_participants = ?, max_participants = ?,
            is_active = ?, expires_at = ?, resource_label = ?, allow_multi_bookings = ?
            WHERE id = ?
        ''', (title, description, allow_changes, only_yes_no, hide_participants,
              max_participants, is_active, expires_at, resource_label,
              allow_multi_bookings, poll_id))

        # Option-Limits aktualisieren
        for opt in options:
            opt_max_str = request.form.get(f'option_max_{opt["id"]}', '').strip()
            opt_max = int(opt_max_str) if opt_max_str else None
            db.execute('UPDATE poll_options SET max_participants = ? WHERE id = ?',
                      (opt_max, opt['id']))

        if poll['poll_type'] == 'matrix':
            resource_names = request.form.getlist('resource_name[]')
            cleaned = [name.strip() for name in resource_names if name.strip()]
            if not cleaned:
                flash('Mindestens eine Ressource ist erforderlich.', 'error')
                return render_template('admin/edit_poll.html', poll=poll, options=options, resources=resources)

            db.execute('DELETE FROM poll_resources WHERE poll_id = ?', (poll_id,))
            for idx, name in enumerate(cleaned):
                db.execute(
                    'INSERT INTO poll_resources (poll_id, name, sort_order) VALUES (?, ?, ?)',
                    (poll_id, name, idx)
                )

        db.commit()

        flash('Umfrage aktualisiert!', 'success')
        return redirect(url_for('admin_dashboard'))

    return render_template('admin/edit_poll.html', poll=poll, options=options, resources=resources)


@app.route('/admin/poll/<int:poll_id>/delete', methods=['POST'])
@admin_required
def delete_poll(poll_id):
    db = get_db()
    db.execute('DELETE FROM matrix_responses WHERE poll_id = ?', (poll_id,))
    db.execute('DELETE FROM poll_resources WHERE poll_id = ?', (poll_id,))
    db.execute('DELETE FROM responses WHERE poll_id = ?', (poll_id,))
    db.execute('DELETE FROM poll_options WHERE poll_id = ?', (poll_id,))
    db.execute('DELETE FROM polls WHERE id = ?', (poll_id,))
    db.commit()
    flash('Umfrage gelöscht.', 'success')
    return redirect(url_for('admin_dashboard'))


# ==================== App Start ====================

if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True)
