import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class DuplicateInstruction(Exception):
    pass


class Journal:
    """Reserva durable previa al POST: un timeout nunca habilita un reenvío."""
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS operaciones (
                tipo TEXT, id_origen TEXT, hash TEXT, estado TEXT, resultado TEXT,
                actualizado TEXT, PRIMARY KEY (tipo, id_origen))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS ordenes_pago (
                drive_file_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, nombre_archivo TEXT NOT NULL,
                estado TEXT NOT NULL, datos TEXT NOT NULL, actualizado TEXT NOT NULL)''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_ordenes_pago_sha256 ON ordenes_pago (sha256)')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def reserve(self, kind, body):
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        with self.connect() as conn:
            try:
                conn.execute('INSERT INTO operaciones VALUES (?, ?, ?, ?, ?, ?)',
                    (kind, body['idOrigen'], fingerprint, 'ENVIO_INICIADO', None, datetime.now(timezone.utc).isoformat()))
            except sqlite3.IntegrityError:
                raise DuplicateInstruction('idOrigen ya registrado. Consultar el estado; no reenviar ni cambiar el ID para repetir un pago.') from None

    def finish(self, kind, origin, state, result):
        with self.connect() as conn:
            conn.execute('UPDATE operaciones SET estado=?, resultado=?, actualizado=? WHERE tipo=? AND id_origen=?',
                         (state, json.dumps(result, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), kind, origin))

    def get(self, kind, origin):
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM operaciones WHERE tipo=? AND id_origen=?', (kind, origin)).fetchone()
        if not row:
            return None
        result = dict(row)
        result.pop('hash')
        result['resultado'] = json.loads(result['resultado']) if result['resultado'] else None
        return result

    def store_order(self, order):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            existing = conn.execute(
                'SELECT sha256, datos FROM ordenes_pago WHERE drive_file_id=?', (order['source_id'],)
            ).fetchone()
            if existing:
                previous = json.loads(existing['datos'])
                if existing['sha256'] == order['sha256']:
                    if (previous['status'] == 'NEEDS_REVIEW'
                            and not previous.get('content_changed_after_import')
                            and order['status'] == 'READY'):
                        conn.execute(
                            'UPDATE ordenes_pago SET estado=?, datos=?, actualizado=? WHERE drive_file_id=?',
                            (order['status'], json.dumps(order, ensure_ascii=False),
                             now, order['source_id']),
                        )
                        return order
                    return previous
                previous['content_changed_after_import'] = True
                previous['new_sha256'] = order['sha256']
                previous['reason'] = 'El contenido del PDF cambió después de importarlo; no se puede enviar automáticamente.'
                if previous['status'] == 'READY':
                    previous['status'] = 'NEEDS_REVIEW'
                conn.execute(
                    'UPDATE ordenes_pago SET sha256=?, estado=?, datos=?, actualizado=? WHERE drive_file_id=?',
                    (order['sha256'], previous['status'], json.dumps(previous, ensure_ascii=False),
                     now, order['source_id']),
                )
                return previous
            duplicate = conn.execute(
                'SELECT drive_file_id FROM ordenes_pago WHERE sha256=? ORDER BY actualizado LIMIT 1',
                (order['sha256'],),
            ).fetchone()
            if duplicate:
                order = dict(order)
                order['status'] = 'DUPLICATE'
                order['reason'] = 'El contenido ya se importó desde otra orden de Drive.'
                order['duplicate_of'] = duplicate['drive_file_id']
            conn.execute(
                'INSERT INTO ordenes_pago VALUES (?, ?, ?, ?, ?, ?)',
                (order['source_id'], order['sha256'], order['source_name'], order['status'],
                 json.dumps(order, ensure_ascii=False), now),
            )
        return order

    def get_order(self, drive_file_id):
        with self.connect() as conn:
            row = conn.execute(
                'SELECT datos FROM ordenes_pago WHERE drive_file_id=?', (drive_file_id,)
            ).fetchone()
        return json.loads(row['datos']) if row else None

    def list_orders(self):
        with self.connect() as conn:
            rows = conn.execute('SELECT datos FROM ordenes_pago ORDER BY nombre_archivo, drive_file_id').fetchall()
        return [json.loads(row['datos']) for row in rows]

    def retain_only_orders(self, drive_file_ids):
        expected = tuple(dict.fromkeys(str(file_id) for file_id in drive_file_ids if file_id))
        with self.connect() as conn:
            if expected:
                placeholders = ','.join('?' for _ in expected)
                conn.execute(f'DELETE FROM ordenes_pago WHERE drive_file_id NOT IN ({placeholders})', expected)
            else:
                conn.execute('DELETE FROM ordenes_pago')

    def update_order_status(self, drive_file_id, status, reason=None):
        with self.connect() as conn:
            row = conn.execute(
                'SELECT datos FROM ordenes_pago WHERE drive_file_id=?', (drive_file_id,)
            ).fetchone()
            if not row:
                return
            order = json.loads(row['datos'])
            order['status'] = status
            order['reason'] = reason
            conn.execute(
                'UPDATE ordenes_pago SET estado=?, datos=?, actualizado=? WHERE drive_file_id=?',
                (status, json.dumps(order, ensure_ascii=False),
                 datetime.now(timezone.utc).isoformat(), drive_file_id),
            )

    def list_operations(self, tipo: str | None = None):
        """Retorna todas las operaciones registradas o filtradas por tipo."""
        with self.connect() as conn:
            if tipo:
                rows = conn.execute('SELECT tipo, id_origen, estado, resultado, actualizado FROM operaciones WHERE tipo=? ORDER BY actualizado DESC', (tipo,)).fetchall()
            else:
                rows = conn.execute('SELECT tipo, id_origen, estado, resultado, actualizado FROM operaciones ORDER BY actualizado DESC').fetchall()
        result = []
        for row in rows:
            r = dict(row)
            try:
                r['resultado'] = json.loads(r['resultado']) if r['resultado'] else None
            except Exception:
                r['resultado'] = r['resultado']
            result.append(r)
        return result
