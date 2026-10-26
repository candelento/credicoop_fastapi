import hashlib
import json
import os
import sqlite3
from decimal import Decimal, InvalidOperation
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

_xlsx_write_lock = Lock()


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
                actualizado TEXT, actor TEXT NOT NULL DEFAULT 'API', resumen TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (tipo, id_origen))''')
            operation_columns = {row['name'] for row in conn.execute('PRAGMA table_info(operaciones)')}
            if 'actor' not in operation_columns:
                conn.execute("ALTER TABLE operaciones ADD COLUMN actor TEXT NOT NULL DEFAULT 'API'")
            if 'resumen' not in operation_columns:
                conn.execute("ALTER TABLE operaciones ADD COLUMN resumen TEXT NOT NULL DEFAULT '{}'")
            conn.execute('''CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT NOT NULL,
                username TEXT NOT NULL, action TEXT NOT NULL, resource TEXT NOT NULL,
                status_code INTEGER, details TEXT NOT NULL DEFAULT '{}')''')
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

    def reserve(self, kind, body, actor='API'):
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        items = body.get('beneficiarios') or body.get('echeqs') or []
        names = [item.get('nombre') or item.get('beneficiarioNombre') or item.get('beneficiarioRazonSocial')
                 for item in items if isinstance(item, dict)]
        names = [name for name in names if name]
        amount = Decimal('0')
        has_amount = False
        for item in items:
            if not isinstance(item, dict) or item.get('monto') is None:
                continue
            try:
                amount += Decimal(str(item['monto']))
                has_amount = True
            except InvalidOperation:
                continue
        summary = {}
        if names:
            summary['beneficiario'] = ', '.join(names[:3]) + (f' y {len(names)-3} más' if len(names) > 3 else '')
        elif body.get('accion'):
            summary['beneficiario'] = f"Gestión {body['accion']}"
        if has_amount:
            summary.update(importe=format(amount, 'f'), moneda='ARS')
        if items:
            summary['cantidad'] = len(items)
        fingerprint_summary = json.dumps(summary, ensure_ascii=False)
        with self.connect() as conn:
            try:
                conn.execute('''INSERT INTO operaciones
                    (tipo,id_origen,hash,estado,resultado,actualizado,actor,resumen) VALUES (?,?,?,?,?,?,?,?)''',
                    (kind, body['idOrigen'], fingerprint, 'ENVIO_INICIADO', None,
                     datetime.now(timezone(timedelta(hours=-3))).isoformat(), actor, fingerprint_summary))
            except sqlite3.IntegrityError:
                raise DuplicateInstruction('idOrigen ya registrado. Consultar el estado; no reenviar ni cambiar el ID para repetir un pago.') from None
        self.write_daily_workbook()

    def finish(self, kind, origin, state, result):
        with self.connect() as conn:
            conn.execute('UPDATE operaciones SET estado=?, resultado=?, actualizado=? WHERE tipo=? AND id_origen=?',
                         (state, json.dumps(result, ensure_ascii=False), datetime.now(timezone(timedelta(hours=-3))).isoformat(), kind, origin))
        self.write_daily_workbook()

    def get(self, kind, origin):
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM operaciones WHERE tipo=? AND id_origen=?', (kind, origin)).fetchone()
        if not row:
            return None
        result = dict(row)
        result.pop('hash')
        result['resultado'] = json.loads(result['resultado']) if result['resultado'] else None
        result['resumen'] = json.loads(result['resumen']) if result['resumen'] else {}
        return result

    def save_bank_status(self, kind: str, origin: str, result: dict):
        with self.connect() as conn:
            row = conn.execute('SELECT resultado FROM operaciones WHERE tipo=? AND id_origen=?',
                               (kind, origin)).fetchone()
            if row is None:
                return False
            stored = json.loads(row['resultado']) if row['resultado'] else {}
            if not isinstance(stored, dict):
                stored = {'respuesta_inicial': stored}
            stored['consulta_estado'] = result
            conn.execute('UPDATE operaciones SET resultado=? WHERE tipo=? AND id_origen=?',
                         (json.dumps(stored, ensure_ascii=False), kind, origin))
        return True

    def list_operations(self, date_from: str, date_to: str, actor: str | None = None,
                        kind: str | None = None):
        query = 'SELECT * FROM operaciones WHERE substr(actualizado,1,10)>=? AND substr(actualizado,1,10)<=?'
        params = [date_from, date_to]
        if actor:
            query += ' AND actor=?'
            params.append(actor)
        if kind:
            query += ' AND tipo=?'
            params.append(kind)
        query += ' ORDER BY actualizado DESC LIMIT 5000'
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        operations = []
        for row in rows:
            item = dict(row)
            item.pop('hash', None)
            item['resultado'] = json.loads(item['resultado']) if item['resultado'] else None
            item['resumen'] = json.loads(item['resumen']) if item['resumen'] else {}
            operations.append(item)
        return operations

    def record_event(self, username: str, action: str, resource: str, status_code: int):
        with self.connect() as conn:
            conn.execute('''INSERT INTO audit_events
                (occurred_at,username,action,resource,status_code,details) VALUES (?,?,?,?,?,?)''',
                (datetime.now(timezone(timedelta(hours=-3))).isoformat(), username, action, resource, status_code, '{}'))
        self.write_daily_workbook()

    def write_daily_workbook(self):
        from .reports import workbook_output

        today = datetime.now(timezone(timedelta(hours=-3))).date().isoformat()
        with self.connect() as conn:
            operation_rows = conn.execute(
                'SELECT tipo,id_origen,estado,resultado,actualizado,actor FROM operaciones WHERE substr(actualizado,1,10)=? ORDER BY actualizado',
                (today,),
            ).fetchall()
            event_rows = conn.execute(
                'SELECT occurred_at,username,action,resource,status_code,details FROM audit_events WHERE substr(occurred_at,1,10)=? ORDER BY occurred_at',
                (today,),
            ).fetchall()
        types = sorted({row['tipo'] for row in operation_rows}) or ['operaciones']
        sheets = {}
        for kind in types:
            rows = [[row['actualizado'], row['actor'], row['id_origen'], row['estado'], row['resultado']]
                    for row in operation_rows if row['tipo'] == kind]
            sheets[kind[:31]] = (['Fecha y hora', 'Usuario', 'idOrigen', 'Estado', 'Resultado'], rows)
        sheets['actividad'] = (['Fecha y hora', 'Usuario', 'Acción', 'Recurso', 'HTTP', 'Detalles'],
            [[row['occurred_at'], row['username'], row['action'], row['resource'], row['status_code'], row['details']]
             for row in event_rows])
        target = self.path.parent / f'auditoria-{today}.xlsx'
        temporary = target.with_name(f'.{target.stem}-{uuid4().hex}.tmp')
        with _xlsx_write_lock:
            try:
                temporary.write_bytes(workbook_output(sheets).getvalue())
                os.replace(temporary, target)
            except OSError:
                temporary.unlink(missing_ok=True)

    def list_audit(self, date_from: str, date_to: str, username: str | None = None):
        query = 'SELECT * FROM audit_events WHERE substr(occurred_at,1,10)>=? AND substr(occurred_at,1,10)<=?'
        params = [date_from, date_to]
        if username:
            query += ' AND username=?'
            params.append(username)
        query += ' ORDER BY occurred_at DESC LIMIT 5000'
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def store_order(self, order):
        now = datetime.now(timezone(timedelta(hours=-3))).isoformat()
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
                 datetime.now(timezone(timedelta(hours=-3))).isoformat(), drive_file_id),
            )
