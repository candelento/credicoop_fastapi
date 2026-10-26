import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class AuthNotConfigured(Exception):
    pass


class InvalidCredentials(Exception):
    pass


class AccountLocked(Exception):
    pass


class AuthError(Exception):
    pass


class UserAuth:
    max_attempts = 5
    lock_seconds = 15 * 60
    absolute_session_seconds = 8 * 60 * 60
    reauthentication_seconds = 30 * 60

    def __init__(self, database_path: Path, initial_users_json: str = '', idle_minutes: int = 15):
        self.database_path = database_path
        self.initial_users_json = initial_users_json
        self.idle_seconds = idle_minutes * 60
        self.hasher = PasswordHasher()
        self.dummy_hash = self.hasher.hash(secrets.token_urlsafe(32))
        self.initialize()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.database_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS app_users (
                username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, role TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1, failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until REAL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                last_login_at TEXT)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS web_sessions (
                token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, created_at REAL NOT NULL,
                last_seen_at REAL NOT NULL, expires_at REAL NOT NULL,
                FOREIGN KEY(username) REFERENCES app_users(username))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT NOT NULL,
                username TEXT NOT NULL, action TEXT NOT NULL, resource TEXT NOT NULL,
                status_code INTEGER, details TEXT NOT NULL DEFAULT '{}')''')
        self._seed_initial_users()

    def _seed_initial_users(self):
        if not self.initial_users_json:
            return
        try:
            users = json.loads(self.initial_users_json)
        except (json.JSONDecodeError, TypeError):
            raise AuthNotConfigured('CREDICOOP_AUTH_USERS_JSON no contiene JSON válido.') from None
        if not isinstance(users, list) or not users:
            raise AuthNotConfigured('CREDICOOP_AUTH_USERS_JSON debe ser una lista de usuarios.')
        now = self._now_text()
        prepared = []
        for user in users:
            if not isinstance(user, dict):
                raise AuthNotConfigured('Cada usuario inicial requiere username, password_hash y role.')
            username, password_hash, role = user.get('username'), user.get('password_hash'), user.get('role')
            if (not isinstance(username, str) or not username.strip() or len(username) > 64
                    or not isinstance(password_hash, str) or not password_hash.startswith('$argon2id$')
                    or role not in ('admin', 'user')):
                raise AuthNotConfigured('Usuario inicial inválido; generar un hash Argon2id y declarar role admin/user.')
            prepared.append((username.strip(), password_hash, role, now, now))
        with self.connect() as conn:
            existing = conn.execute('SELECT COUNT(*) FROM app_users').fetchone()[0]
            if existing == 0:
                conn.executemany('INSERT INTO app_users (username,password_hash,role,created_at,updated_at) VALUES (?,?,?,?,?)', prepared)

    @staticmethod
    def _now_text():
        return datetime.now(timezone(timedelta(hours=-3))).isoformat()

    @staticmethod
    def _event(conn, username: str, action: str, resource: str, status_code=None, details=None):
        conn.execute('INSERT INTO audit_events (occurred_at,username,action,resource,status_code,details) VALUES (?,?,?,?,?,?)',
                     (UserAuth._now_text(), username, action, resource, status_code,
                      json.dumps(details or {}, ensure_ascii=False)))

    def _hash(self, token: str) -> str:
        return hashlib.sha256(token.encode('ascii')).hexdigest()

    def login(self, username: str, password: str) -> tuple[str, dict]:
        now = time.time()
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM app_users WHERE username=?', (username,)).fetchone()
            if row is None:
                try:
                    self.hasher.verify(self.dummy_hash, password)
                except (VerificationError, InvalidHashError):
                    pass
                self._event(conn, username[:64] or 'anonymous', 'login_failed', '/login', 401)
                conn.commit()
                if not self.initial_users_json and not conn.execute('SELECT 1 FROM app_users LIMIT 1').fetchone():
                    raise AuthNotConfigured('Configurar CREDICOOP_AUTH_USERS_JSON con usuarios y hashes Argon2id.')
                raise InvalidCredentials('Usuario o contraseña inválidos.')
            if row['locked_until'] and row['locked_until'] > now:
                self._event(conn, username, 'login_locked', '/login', 423)
                conn.commit()
                raise AccountLocked('Cuenta bloqueada temporalmente por intentos fallidos.')
            valid = False
            try:
                valid = self.hasher.verify(row['password_hash'], password)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                pass
            if not valid or not row['active']:
                attempts = row['failed_attempts'] + 1
                locked_until = now + self.lock_seconds if attempts >= self.max_attempts else None
                conn.execute('UPDATE app_users SET failed_attempts=?,locked_until=?,updated_at=? WHERE username=?',
                             (0 if locked_until else attempts, locked_until, self._now_text(), username))
                self._event(conn, username, 'login_failed', '/login', 423 if locked_until else 401)
                conn.commit()
                if locked_until:
                    raise AccountLocked('Cuenta bloqueada temporalmente por intentos fallidos.')
                raise InvalidCredentials('Usuario o contraseña inválidos.')
            if self.hasher.check_needs_rehash(row['password_hash']):
                conn.execute('UPDATE app_users SET password_hash=? WHERE username=?', (self.hasher.hash(password), username))
            created = self._now_text()
            conn.execute('UPDATE app_users SET failed_attempts=0,locked_until=NULL,last_login_at=?,updated_at=? WHERE username=?',
                         (created, created, username))
            token = secrets.token_urlsafe(32)
            conn.execute('INSERT INTO web_sessions VALUES (?,?,?,?,?)',
                         (self._hash(token), username, now, now, now + self.absolute_session_seconds))
            self._event(conn, username, 'login', '/login', 200)
            return token, {'username': username, 'role': row['role']}

    def session_user(self, token: str | None) -> dict | None:
        if not token or len(token) > 200:
            return None
        now = time.time()
        with self.connect() as conn:
            row = conn.execute('''SELECT s.*,u.role,u.active FROM web_sessions s
                JOIN app_users u ON u.username=s.username WHERE s.token_hash=?''', (self._hash(token),)).fetchone()
            if row is None:
                return None
            if not row['active'] or row['expires_at'] <= now or now - row['last_seen_at'] > self.idle_seconds:
                conn.execute('DELETE FROM web_sessions WHERE token_hash=?', (row['token_hash'],))
                return None
            remaining = max(0, self.reauthentication_seconds - (now - row['created_at']))
            if remaining > 0:
                conn.execute('UPDATE web_sessions SET last_seen_at=? WHERE token_hash=?', (now, row['token_hash']))
            return {'username': row['username'], 'role': row['role'], 'auth_method': 'session',
                    'reauthentication_required': remaining <= 0, 'reauthenticate_in_seconds': remaining}

    def logout(self, token: str | None):
        if token:
            with self.connect() as conn:
                row = conn.execute('SELECT username FROM web_sessions WHERE token_hash=?', (self._hash(token),)).fetchone()
                conn.execute('DELETE FROM web_sessions WHERE token_hash=?', (self._hash(token),))
                if row:
                    self._event(conn, row['username'], 'logout', '/logout', 200)

    def change_password(self, username: str, current_password: str, new_password: str):
        with self.connect() as conn:
            row = conn.execute('SELECT password_hash FROM app_users WHERE username=? AND active=1', (username,)).fetchone()
            if not row:
                raise InvalidCredentials('No se pudo validar la contraseña actual.')
            try:
                self.hasher.verify(row['password_hash'], current_password)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                self._event(conn, username, 'password_change_failed', '/auth/password', 401)
                conn.commit()
                raise InvalidCredentials('No se pudo validar la contraseña actual.') from None
            conn.execute('UPDATE app_users SET password_hash=?,updated_at=? WHERE username=?',
                         (self.hasher.hash(new_password), self._now_text(), username))
            conn.execute('DELETE FROM web_sessions WHERE username=?', (username,))
            self._event(conn, username, 'password_changed', '/auth/password', 200)

    def list_users(self):
        with self.connect() as conn:
            rows = conn.execute('''SELECT username,role,active,created_at,updated_at,last_login_at,locked_until
                FROM app_users ORDER BY username''').fetchall()
        return [dict(row) for row in rows]

    def add_user(self, username: str, password: str, role: Literal['admin', 'user']):
        now = self._now_text()
        try:
            with self.connect() as conn:
                conn.execute('INSERT INTO app_users (username,password_hash,role,created_at,updated_at) VALUES (?,?,?,?,?)',
                             (username, self.hasher.hash(password), role, now, now))
                self._event(conn, username, 'user_created', '/usuarios', 201)
        except sqlite3.IntegrityError:
            raise AuthError('El usuario ya existe.') from None

    def update_user(self, actor: str, username: str, *, password: str | None = None,
                    role: Literal['admin', 'user'] | None = None, active: bool | None = None):
        with self.connect() as conn:
            row = conn.execute('SELECT role,active FROM app_users WHERE username=?', (username,)).fetchone()
            if not row:
                raise AuthError('El usuario no existe.')
            next_role = role or row['role']
            next_active = row['active'] if active is None else int(active)
            if row['role'] == 'admin' and row['active'] and (next_role != 'admin' or not next_active):
                admins = conn.execute("SELECT COUNT(*) FROM app_users WHERE role='admin' AND active=1").fetchone()[0]
                if admins <= 1:
                    raise AuthError('No se puede desactivar o degradar al último administrador.')
            fields, values = ['role=?', 'active=?', 'updated_at=?'], [next_role, next_active, self._now_text()]
            if password is not None:
                fields.append('password_hash=?')
                values.append(self.hasher.hash(password))
                conn.execute('DELETE FROM web_sessions WHERE username=?', (username,))
            values.append(username)
            conn.execute(f"UPDATE app_users SET {','.join(fields)} WHERE username=?", values)
            self._event(conn, actor, 'user_updated', f'/usuarios/{username}', 200,
                        {'role': next_role, 'active': bool(next_active), 'password_reset': password is not None})

    def audit_request(self, username: str, action: str, resource: str, status_code: int):
        with self.connect() as conn:
            self._event(conn, username, action, resource, status_code)

    def list_audit(self, date_from: str, date_to: str, username: str | None = None):
        query = 'SELECT * FROM audit_events WHERE substr(occurred_at,1,10)>=? AND substr(occurred_at,1,10)<=?'
        params: list[object] = [date_from, date_to]
        if username:
            query += ' AND username=?'
            params.append(username)
        query += ' ORDER BY occurred_at DESC LIMIT 5000'
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['details'] = json.loads(item['details'])
            result.append(item)
        return result
