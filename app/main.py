import json
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from .auth import AccountLocked, AuthError, AuthNotConfigured, InvalidCredentials, UserAuth
from fastapi.security import APIKeyHeader
from .client import BankError, CredicoopClient
from .config import Settings, argentina_today
from .journal import DuplicateInstruction, Journal
from .models import (
    EcheqListRequest, EcheqManagementRequest, EcheqRequest, FCI_SIGNER_DNI,
    FciMovementsRequest, FciPositionRequest, FciRedemptionRequest, FciSubscriptionRequest,
    LoginRequest, OrderDebitAccount, PasswordChangeRequest, TransferRequest,
    UserCreateRequest, UserUpdateRequest, echeq_list_payload, echeq_management_payload,
    fci_instruction_payload, instruction_payload,
)
from .orders import (DriveOrderError, DriveOrderService, OrderParseError, SupplierMasterError,
                     build_order_instruction)
from .reports import workbook_response

api_key_header = APIKeyHeader(name='X-API-Key', auto_error=False)


def create_app(settings: Settings | None = None, client: CredicoopClient | None = None, *, demo: bool = False):
    # La raíz no tiene handlers (uvicorn sólo configura los suyos); sin esto los INFO no se imprimen.
    # basicConfig no hace nada si la raíz ya tiene handlers, así que no pisa una configuración previa.
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    cfg = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.bank = client or CredicoopClient(cfg)
        app.state.journal = Journal(cfg.journal_path)
        app.state.auth = UserAuth(cfg.journal_path, cfg.auth_users_json, cfg.session_idle_minutes)
        app.state.drive_orders = DriveOrderService(cfg, project_root)
        yield
        await app.state.bank.close()

    app = FastAPI(title='Sistema Bancario | RONANFER', version='1.3.0', lifespan=lifespan,
        description='Consultas de cuentas, movimientos y FCI. Transferencias, eCheqs, suscripciones y rescates se envían a la firma; la autorización y activación se realizan en Banca Internet Empresa.')

    async def authorized(request: Request, key: Annotated[str | None, Security(api_key_header)]):
        user = None
        if key and secrets.compare_digest(key, cfg.api_key.get_secret_value()):
            user = {'username': 'API', 'role': 'api', 'auth_method': 'api_key'}
        else:
            user = request.app.state.auth.session_user(request.cookies.get('ronanfer_session'))
        if user is None:
            raise HTTPException(401, 'Sesión vencida o credenciales inválidas.')
        request.state.user = user
        if user.get('reauthentication_required') and request.url.path not in ('/auth/me', '/logout'):
            raise HTTPException(428, 'Por seguridad, ingresá nuevamente tu contraseña para continuar.')

    def admin_session(request: Request):
        user = getattr(request.state, 'user', None)
        if not user or user.get('role') != 'admin' or user.get('auth_method') != 'session':
            raise HTTPException(403, 'Se requiere una sesión de administrador.')

    def fci_scope_enabled():
        if 'fciConFirma' not in cfg.scopes.split():
            raise HTTPException(503, 'Falta el scope fciConFirma en CREDICOOP_SCOPES. Confirmá antes con el banco que el adherente esté habilitado.')

    def echeq_scope_enabled():
        if 'echeqConFirma' not in cfg.scopes.split():
            raise HTTPException(503, 'Falta el scope echeqConFirma en CREDICOOP_SCOPES. Confirmá antes con el banco que el adherente esté habilitado.')

    def bank(request: Request):
        return request.app.state.bank

    auth = [Depends(authorized)]
    admin_auth = auth + [Depends(admin_session)]
    fci_auth = auth + [Depends(fci_scope_enabled)]
    echeq_auth = auth + [Depends(echeq_scope_enabled)]
    project_root = Path(__file__).resolve().parents[1]
    app.mount('/static', StaticFiles(directory=project_root / 'app' / 'static'), name='static')

    @app.middleware('http')
    async def audit_http_activity(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path != '/salud' and not path.startswith('/static') and path not in ('/login', '/logout', '/auth/password'):
            user = getattr(request.state, 'user', None) or {}
            actor = user.get('username', 'anonymous')
            try:
                request.app.state.journal.record_event(actor, f'{request.method.lower()}_request', path, response.status_code)
            except Exception:
                logging.getLogger('app.audit').exception('No se pudo registrar actividad HTTP en auditoría.')
        return response

    @app.get('/', response_class=HTMLResponse, include_in_schema=False)
    async def home():
        return HTMLResponse((project_root / 'app' / 'static' / 'index.html').read_text(encoding='utf-8'),
                            headers={'Cache-Control': 'no-store', 'X-Frame-Options': 'DENY',
                                     'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"})

    @app.get('/homologacion/beneficiarios', dependencies=auth)
    async def test_beneficiaries():
        if not cfg.is_homologation:
            raise HTTPException(404, 'Los datos de prueba sólo se ofrecen en homologación.')
        data = json.loads((project_root / 'ejemplos' / 'beneficiarios_homologacion.json').read_text(encoding='utf-8'))
        data['beneficiarios'] = [b for b in data['beneficiarios'] if b['uso'] == 'emision']
        data['aviso'] = 'Lista de prueba entregada por el banco; verificar cada beneficiario en la agenda del adherente.'
        return data

    @app.get('/homologacion/ordenes', dependencies=auth)
    async def test_orders():
        if not cfg.is_homologation:
            raise HTTPException(404, 'Las órdenes de ejemplo sólo se ofrecen en homologación.')
        return json.loads((project_root / 'ejemplos' / 'ordenes_prueba.json').read_text(encoding='utf-8'))

    @app.exception_handler(BankError)
    async def bank_error(request, exc):
        return JSONResponse(status_code=exc.status, content={'error': str(exc), 'detalle_banco': exc.details,
                                                           'resultado_incierto': exc.ambiguous})

    @app.exception_handler(DuplicateInstruction)
    async def duplicate(request, exc):
        return JSONResponse(status_code=409, content={'error': str(exc)})

    @app.exception_handler(DriveOrderError)
    async def drive_order_error(request, exc):
        return JSONResponse(status_code=502, content={'error': str(exc)})

    @app.exception_handler(SupplierMasterError)
    async def supplier_master_error(request, exc):
        return JSONResponse(status_code=503, content={'error': str(exc)})

    @app.post('/login')
    async def login(credentials: LoginRequest, request: Request, response: Response):
        try:
            token, user = request.app.state.auth.login(credentials.username.strip(), credentials.password)
        except AuthNotConfigured as exc:
            request.app.state.journal.write_daily_workbook()
            raise HTTPException(503, str(exc)) from None
        except AccountLocked as exc:
            request.app.state.journal.write_daily_workbook()
            raise HTTPException(423, str(exc)) from None
        except InvalidCredentials as exc:
            request.app.state.journal.write_daily_workbook()
            raise HTTPException(401, str(exc)) from None
        request.app.state.auth.logout(request.cookies.get('ronanfer_session'))
        request.app.state.journal.write_daily_workbook()
        response.set_cookie('ronanfer_session', token, max_age=UserAuth.absolute_session_seconds,
                            httponly=True, secure=cfg.session_cookie_secure, samesite='strict', path='/')
        return {'usuario': user, 'revalidar_en_segundos': UserAuth.reauthentication_seconds}

    @app.post('/logout')
    async def logout(request: Request, response: Response):
        request.app.state.auth.logout(request.cookies.get('ronanfer_session'))
        request.app.state.journal.write_daily_workbook()
        response.delete_cookie('ronanfer_session', path='/', secure=cfg.session_cookie_secure,
                               httponly=True, samesite='strict')
        return {'cerrada': True}

    @app.get('/auth/me', dependencies=auth)
    async def current_user(request: Request):
        user = request.state.user
        return {'usuario': user.get('username'), 'rol': user.get('role'),
                'autenticacion': user.get('auth_method'),
                'revalidacion_requerida': user.get('reauthentication_required', False),
                'revalidar_en_segundos': user.get('reauthenticate_in_seconds')}

    @app.post('/auth/password', dependencies=auth)
    async def change_password(data: PasswordChangeRequest, request: Request):
        user = request.state.user
        if user.get('auth_method') != 'session':
            raise HTTPException(403, 'El cambio de contraseña requiere una sesión de usuario.')
        try:
            request.app.state.auth.change_password(user['username'], data.current_password, data.new_password)
        except InvalidCredentials as exc:
            request.app.state.journal.write_daily_workbook()
            raise HTTPException(401, str(exc)) from None
        request.app.state.journal.write_daily_workbook()
        return {'actualizada': True, 'aviso': 'Volvé a iniciar sesión con la nueva contraseña.'}

    @app.get('/usuarios', dependencies=admin_auth)
    async def list_users(request: Request):
        return {'usuarios': request.app.state.auth.list_users()}

    @app.post('/usuarios', status_code=201, dependencies=admin_auth)
    async def create_user(data: UserCreateRequest, request: Request):
        try:
            request.app.state.auth.add_user(data.username, data.password, data.role)
        except AuthError as exc:
            raise HTTPException(409, str(exc)) from None
        return {'creado': True, 'usuario': data.username}

    @app.patch('/usuarios/{username}', dependencies=admin_auth)
    async def update_user(username: str, data: UserUpdateRequest, request: Request):
        try:
            request.app.state.auth.update_user(request.state.user['username'], username,
                                               password=data.password, role=data.role, active=data.active)
        except AuthError as exc:
            raise HTTPException(409, str(exc)) from None
        return {'actualizado': True}

    @app.get('/salud')
    async def health():
        return {'estado': 'ok', 'modalidad': 'firma posterior en BIE'}

    @app.get('/dashboard', dependencies=auth)
    async def dashboard(request: Request, b: CredicoopClient = Depends(bank)):
        account_data = await b.accounts()
        accounts = account_data.get('clarifCuentas', account_data.get('clarifcuentas', []))
        today = argentina_today().isoformat()
        operations = request.app.state.journal.list_operations(today, today)
        fci_balances = []
        if 'fciConFirma' in cfg.scopes.split():
            try:
                fci_data = await b.fci_accounts()
                comitentes = fci_data.get('data', {}).get('cuentasComitentes', [])
                for account in comitentes[:20]:
                    payload = {'cuentaComitente': account, 'numeroAdherente': cfg.adherente, 'idOrigen': str(uuid4())}
                    balance_data = await b.request('POST', '/api/fci/v1/cuenta-comitente-saldos', body=payload)
                    details = balance_data.get('data', {}).get('saldoDetalle', [])
                    if isinstance(details, list):
                        fci_balances.extend(details)
            except BankError as exc:
                logging.getLogger('app.dashboard').warning('No se pudo actualizar el resumen FCI: %s', exc)
        pending = [row for row in operations if row['estado'] in ('ENVIO_INICIADO', 'RESPUESTA_RECIBIDA', 'RESULTADO_INCIERTO')]
        failed = [row for row in operations if row['estado'] == 'ERROR']
        recent = request.app.state.journal.list_audit(today, today)
        last_sync = next((event['occurred_at'] for event in recent
                          if event['status_code'] == 200 and event['resource'] in ('/cuentas', '/fci/cuentas-comitentes', '/fci/fondos')),
                         None)
        return {'fecha': today, 'cuentas': accounts if isinstance(accounts, list) else [],
                        'saldos_fci': fci_balances,
                        'cantidad_cuentas': len(accounts) if isinstance(accounts, list) else 0,
                'operaciones_hoy': operations,
                'transferencias_pendientes_firma': sum(row['tipo'] == 'transferencia' and row['estado'] == 'RESPUESTA_RECIBIDA' for row in operations),
                'echeqs_pendientes_firma': sum(row['tipo'] in ('echeq', 'echeq_gestion') and row['estado'] == 'RESPUESTA_RECIBIDA' for row in operations),
                'operaciones_con_error': len(failed),
                                'ultima_sincronizacion_banco': last_sync}

    @app.get('/operaciones', dependencies=auth)
    async def list_operations(request: Request, fecha_desde: date | None = None, fecha_hasta: date | None = None,
                              usuario: str | None = None,
                              tipo: Literal['transferencia', 'echeq', 'echeq_gestion', 'fci_suscripcion', 'fci_rescate'] | None = None):
        end = fecha_hasta or argentina_today()
        start = fecha_desde or end
        if start > end:
            raise HTTPException(422, 'fecha_desde debe ser menor o igual a fecha_hasta.')
        current = request.state.user
        actor = usuario if current['role'] == 'admin' else current['username']
        return {'operaciones': request.app.state.journal.list_operations(
            start.isoformat(), end.isoformat(), actor, kind=tipo)}

    @app.get('/operaciones/export.xlsx', dependencies=auth)
    async def export_operations(request: Request, fecha_desde: date | None = None, fecha_hasta: date | None = None,
                               usuario: str | None = None):
        end = fecha_hasta or argentina_today()
        start = fecha_desde or end
        if start > end:
            raise HTTPException(422, 'fecha_desde debe ser menor o igual a fecha_hasta.')
        current = request.state.user
        actor = usuario if current['role'] == 'admin' else current['username']
        operations = request.app.state.journal.list_operations(start.isoformat(), end.isoformat(), actor)
        rows = []
        for item in operations:
            result = item.get('resultado') or {}
            bank_result = result.get('consulta_estado', result) if isinstance(result, dict) else {}
            bank_data = bank_result.get('data', {}) if isinstance(bank_result, dict) else {}
            summary = item.get('resumen') or {}
            bank_state = bank_data.get('estadoOperacion')
            bank_state = bank_state.get('descripcion') if isinstance(bank_state, dict) else bank_state
            rows.append([item['actualizado'], item['actor'], item['tipo'], summary.get('beneficiario'),
                         summary.get('importe'), bank_state or item['estado'],
                         bank_data.get('idOperacion'), item['id_origen']])
        headers = ['Fecha y hora', 'Usuario', 'Operación', 'Beneficiario', 'Importe', 'Estado', 'idOperacion', 'idOrigen']
        return workbook_response(f'operaciones-{start.isoformat()}-{end.isoformat()}.xlsx',
                                 {'operaciones': (headers, rows)})

    @app.get('/auditoria', dependencies=auth)
    async def audit_history(request: Request, fecha_desde: date | None = None, fecha_hasta: date | None = None,
                            usuario: str | None = None):
        end = fecha_hasta or argentina_today()
        start = fecha_desde or end
        if start > end:
            raise HTTPException(422, 'fecha_desde debe ser menor o igual a fecha_hasta.')
        current = request.state.user
        actor = usuario if current['role'] == 'admin' else current['username']
        return {'eventos': request.app.state.journal.list_audit(start.isoformat(), end.isoformat(), actor)}

    @app.get('/auditoria/export.xlsx', dependencies=auth)
    async def export_audit(request: Request, fecha_desde: date | None = None, fecha_hasta: date | None = None):
        end = fecha_hasta or argentina_today()
        start = fecha_desde or end
        if start > end:
            raise HTTPException(422, 'fecha_desde debe ser menor o igual a fecha_hasta.')
        current = request.state.user
        actor = None if current['role'] == 'admin' else current['username']
        operations = request.app.state.journal.list_operations(start.isoformat(), end.isoformat(), actor)
        events = request.app.state.journal.list_audit(start.isoformat(), end.isoformat(), actor)
        kinds = sorted({row['tipo'] for row in operations}) or ['operaciones']
        sheets = {}
        for kind in kinds:
            rows = [[row['actualizado'], row['actor'], row['tipo'], row['estado'], row['id_origen'],
                     json.dumps(row['resultado'], ensure_ascii=False)] for row in operations if row['tipo'] == kind]
            sheets[kind[:31]] = (['Fecha y hora', 'Usuario', 'Tipo', 'Estado', 'idOrigen', 'Resultado'], rows)
        sheets['actividad'] = (['Fecha y hora', 'Usuario', 'Acción', 'Recurso', 'HTTP', 'Detalles'],
            [[row['occurred_at'], row['username'], row['action'], row['resource'], row['status_code'], row['details']]
             for row in events])
        return workbook_response(f'historial-{start.isoformat()}-{end.isoformat()}.xlsx', sheets)

    @app.get('/configuracion', dependencies=auth)
    async def configuration():
        return {'adherente': cfg.adherente, 'fecha_actual_argentina': argentina_today().isoformat(),
                'fecha_operativa_banco': cfg.operational_today().isoformat(),
                'homologacion': cfg.is_homologation,
                'simulacion': demo,
                                'echeq_scope_habilitado': 'echeqConFirma' in cfg.scopes.split(),
                                'fci_scope_habilitado': 'fciConFirma' in cfg.scopes.split(),
                'fci_firmante_dni': FCI_SIGNER_DNI,
                'movimientos_hasta_predeterminado': 'fecha actual de Argentina'}

    @app.get('/cuentas', dependencies=auth)
    async def accounts(b: CredicoopClient = Depends(bank)):
        return await b.accounts()

    @app.get('/export/cuentas.xlsx', dependencies=auth)
    async def export_accounts(b: CredicoopClient = Depends(bank)):
        data = await b.accounts()
        rows = data.get('clarifCuentas', data.get('clarifcuentas'))
        if not isinstance(rows, list):
            raise BankError('Formato de lista de cuentas inesperado.')
        headers = ['Cuenta', 'Titular', 'Tipo', 'Moneda', 'CBU', 'Saldo actual']
        values = [[row.get('nroCuenta'), row.get('denominacionCuenta'), row.get('tipoCuenta'),
                   row.get('moneda'), row.get('CBU') or row.get('cbu'), row.get('saldo')] for row in rows]
        return workbook_response('saldos-cuentas.xlsx', {'cuentas': (headers, values)})

    @app.get('/export/movimientos.xlsx', dependencies=auth)
    async def export_movements(nro_cuenta: str, fecha_desde: date, fecha_hasta: date,
                               b: CredicoopClient = Depends(bank)):
        if not nro_cuenta.isdigit() or len(nro_cuenta) > 22:
            raise HTTPException(422, 'Número de cuenta inválido; usar nroCuenta, no CBU.')
        try:
            result = await b.movements(nro_cuenta, fecha_desde, fecha_hasta)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        rows = [[item.get('fecha'), item.get('descripcion'), item.get('nroComprobante'), item.get('idTransaccion'),
                 item.get('monto') if item.get('indDBCR') == 'DB' else None,
                 item.get('monto') if item.get('indDBCR') == 'CR' else None,
                 item.get('monto'), item.get('saldo'), nro_cuenta] for item in result['movimientos']]
        headers = ['Fecha', 'Descripción', 'Comprobante', 'Referencia', 'Débito', 'Crédito', 'Importe', 'Saldo', 'Cuenta']
        return workbook_response(f'movimientos-{nro_cuenta}.xlsx', {'movimientos': (headers, rows)})

    @app.get('/cuentas/{nro_cuenta}/saldo', dependencies=auth)
    async def balance(nro_cuenta: str, b: CredicoopClient = Depends(bank)):
        data = await b.accounts()
        accounts = data.get('clarifCuentas', data.get('clarifcuentas'))
        if not isinstance(accounts, list):
            raise BankError('Formato de lista de cuentas inesperado.')
        for account in accounts:
            if str(account.get('nroCuenta')) == nro_cuenta:
                return account
        raise HTTPException(404, 'Cuenta no encontrada entre las habilitadas por el banco.')

    @app.get('/cuentas/{nro_cuenta}/movimientos', dependencies=auth)
    async def movements(nro_cuenta: str, fecha_desde: date, fecha_hasta: date | None = None,
                        cod_operativo: str | None = None, b: CredicoopClient = Depends(bank)):
        if not nro_cuenta.isdigit() or len(nro_cuenta) > 22:
            raise HTTPException(422, 'Número de cuenta inválido; usar nroCuenta, no CBU.')
        end = fecha_hasta or argentina_today()
        # Log request parameters to console for debugging movimientos queries
        logging.getLogger('app.client').info(
            'REQUEST movimientos [GET /api/cuentas/v2/%s/movimientos] fecha_desde=%s fecha_hasta=%s cod_operativo=%s',
            nro_cuenta, fecha_desde.isoformat(), end.isoformat(), cod_operativo
        )
        try:
            result = await b.movements(nro_cuenta, fecha_desde, end, cod_operativo)
        except ValueError as exc:
            logging.getLogger('app.client').info('RESPONSE movimientos [%s] error: %s', nro_cuenta, str(exc))
            raise HTTPException(422, str(exc)) from None
        # Log a truncated JSON summary of the response to avoid very large console output
        try:
            summary = json.dumps(result, ensure_ascii=False, default=str)
            if len(summary) > 4000:
                summary = summary[:4000] + '...'
        except Exception:
            summary = repr(result)
        logging.getLogger('app.client').info(
            'RESPONSE movimientos [GET /api/cuentas/v2/%s/movimientos] status=ok: %s',
            nro_cuenta, summary
        )
        if cfg.fecha_operativa and end > cfg.fecha_operativa:
            result['aviso_homologacion'] = ('El rango llega más allá de la fecha operativa fija del banco. '
                'Para pruebas hasta el 28/08/2026, indicar fecha_hasta explícitamente; revisar si el banco cambió la fecha.')
        return result

    def prepare(instruction):
        try:
            return instruction_payload(instruction, cfg.adherente, cfg.operational_today())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    def get_ready_order(source_id: str, request: Request) -> dict:
        if demo:
            raise HTTPException(404, 'La importación real de Drive no está habilitada en modo demostración.')
        order = request.app.state.journal.get_order(source_id)
        if order is None:
            raise HTTPException(404, 'La orden no se encuentra importada; sincronizá la carpeta de Drive.')
        if order['status'] != 'READY':
            raise HTTPException(409, 'La orden requiere revisión y no se puede preparar para envío.')
        return order

    def order_instruction(order: dict, debit_cbu: str):
        try:
            payload = build_order_instruction(order, debit_cbu, cfg.operational_today())
            if order['method'] == 'TRB':
                return TransferRequest(**payload)
            return EcheqRequest(**payload)
        except (ValueError, OrderParseError) as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get('/ordenes-pago', dependencies=auth)
    async def payment_orders(request: Request):
        if demo:
            raise HTTPException(404, 'La importación real de Drive no está habilitada en modo demostración.')
        return {'ordenes': request.app.state.journal.list_orders()}

    @app.post('/ordenes-pago/sincronizar', dependencies=auth)
    async def sync_payment_orders(request: Request):
        if demo:
            raise HTTPException(404, 'La importación real de Drive no está habilitada en modo demostración.')
        return await request.app.state.drive_orders.sync(request.app.state.journal)


    @app.post('/ordenes-pago/{source_id}/previsualizar', dependencies=auth)
    async def preview_payment_order(source_id: str, account: OrderDebitAccount, request: Request):
        order = get_ready_order(source_id, request)
        instruction = order_instruction(order, account.cbuCuentaDebito)
        return {
            'enviada': False,
            'orden': {
                'archivo': order['source_name'],
                'proveedor': order['supplier']['name'],
                'importe': order['amount'],
                'medio': 'Transferencia' if order['method'] == 'TRB' else 'eCheq',
            },
            'payload_banco': prepare(instruction),
        }

    @app.post('/ordenes-pago/{source_id}/enviar', dependencies=auth)
    async def send_payment_order(source_id: str, account: OrderDebitAccount, request: Request,
                                 b: CredicoopClient = Depends(bank)):
        order = get_ready_order(source_id, request)
        instruction = order_instruction(order, account.cbuCuentaDebito)
        kind = 'transferencia' if order['method'] == 'TRB' else 'echeq'
        prior_operation = request.app.state.journal.get(kind, order['id_origen'])
        if prior_operation:
            request.app.state.journal.update_order_status(
                source_id, prior_operation['estado'], 'Ya existe un intento registrado; consultar su estado y no reenviar.'
            )
            raise HTTPException(409, 'Ya existe un intento para esta orden. Consultá el estado antes de repetir.')
        try:
            result = await submit(kind, instruction, request, b)
        except (BankError, DuplicateInstruction):
            operation = request.app.state.journal.get(kind, order['id_origen'])
            if operation:
                request.app.state.journal.update_order_status(source_id, operation['estado'], 'Consultar el estado local antes de repetir.')
            raise
        except BaseException:
            operation = request.app.state.journal.get(kind, order['id_origen'])
            if operation:
                request.app.state.journal.update_order_status(source_id, operation['estado'], 'Envío interrumpido; consultar el estado antes de repetir.')
            raise
        request.app.state.journal.update_order_status(source_id, 'ENVIADA_A_FIRMA')
        return result

    @app.post('/transferencias/previsualizar', dependencies=auth)
    async def preview_transfer(instruction: TransferRequest):
        return {'enviada': False, 'payload_banco': prepare(instruction)}

    @app.post('/echeqs/previsualizar', dependencies=echeq_auth)
    async def preview_echeq(instruction: EcheqRequest):
        return {'enviada': False, 'payload_banco': prepare(instruction)}

    async def submit(kind, instruction, request, b, *, path=None, payload=None, requires_operation_id=True):
        payload = payload or prepare(instruction)
        journal = request.app.state.journal
        # La reserva se confirma en disco ANTES de invocar el banco.
        actor = getattr(request.state, 'user', {}).get('username', 'API')
        journal.reserve(kind, payload, actor=actor)
        path = path or ('/api/transferencias/v1/ConFirma/transferencia'
                        if kind == 'transferencia' else '/api/echeq/v1/ConFirma/emision')
        try:
            response = await b.request('POST', path, body=payload)
        except BankError as exc:
            journal.finish(kind, instruction.idOrigen, 'RESULTADO_INCIERTO' if exc.ambiguous else 'ERROR',
                           {'error': str(exc), 'detalle_banco': exc.details})
            raise
        except BaseException:
            # También frente a una cancelación: pudo llegar al banco.
            journal.finish(kind, instruction.idOrigen, 'RESULTADO_INCIERTO', {'error': 'Envío interrumpido; consultar al banco.'})
            raise
        data = response.get('data')
        valid_response = isinstance(data, dict) and (
            data.get('idOperacion') if requires_operation_id else data.get('estadoOperacion')
        )
        if not valid_response:
            journal.finish(kind, instruction.idOrigen, 'RESULTADO_INCIERTO', response)
            expected = 'idOperacion' if requires_operation_id else 'estadoOperacion'
            raise BankError(f'Respuesta sin {expected}. Consultar BIE antes de repetir.', 502, response, ambiguous=True)
        journal.finish(kind, instruction.idOrigen, 'RESPUESTA_RECIBIDA', response)
        # El estado real del banco se conserva; no se fuerza a "pendiente" ni "pagado".
        return {'idOrigen': instruction.idOrigen, 'modalidad': 'ConFirma', 'respuesta_banco': response,
                'siguiente_paso': 'Consultar el estado y completar firma y activación en Banca Internet Empresa.'}

    @app.post('/transferencias', dependencies=auth)
    async def transfer(instruction: TransferRequest, request: Request, b: CredicoopClient = Depends(bank)):
        return await submit('transferencia', instruction, request, b)

    @app.post('/echeqs', dependencies=echeq_auth)
    async def echeq(instruction: EcheqRequest, request: Request, b: CredicoopClient = Depends(bank)):
        return await submit('echeq', instruction, request, b)

    @app.post('/echeqs/listar', dependencies=echeq_auth)
    async def list_echeqs(instruction: EcheqListRequest, b: CredicoopClient = Depends(bank)):
        payload = echeq_list_payload(instruction, cfg.adherente)
        return await b.request('POST', '/api/echeq/v1/lista-cheques', body=payload)

    @app.post('/echeqs/gestionar/previsualizar', dependencies=echeq_auth)
    async def preview_echeq_management(instruction: EcheqManagementRequest):
        return {'enviada': False, 'payload_banco': echeq_management_payload(instruction, cfg.adherente)}

    @app.post('/echeqs/gestionar', dependencies=echeq_auth)
    async def manage_echeq(instruction: EcheqManagementRequest, request: Request,
                           b: CredicoopClient = Depends(bank)):
        payload = echeq_management_payload(instruction, cfg.adherente)
        return await submit('echeq_gestion', instruction, request, b,
                            path='/api/echeq/v1/ConFirma/gestion', payload=payload,
                            requires_operation_id=False)

    async def submit_fci(kind, instruction, request, b):
        path = ('/api/fci/v1/ConFirma/suscripcion' if kind == 'fci_suscripcion'
                else '/api/fci/v1/ConFirma/rescate')
        return await submit(kind, instruction, request, b, path=path,
                            payload=fci_instruction_payload(instruction, cfg.adherente))

    @app.get('/fci/cuentas-comitentes', dependencies=fci_auth)
    async def fci_accounts(b: CredicoopClient = Depends(bank)):
        return await b.fci_accounts()

    @app.get('/fci/fondos', dependencies=fci_auth)
    async def fci_funds(b: CredicoopClient = Depends(bank)):
        return await b.fci_funds()

    @app.post('/fci/suscripciones/previsualizar', dependencies=fci_auth)
    async def fci_subscription_preview(instruction: FciSubscriptionRequest):
        return {'enviada': False, 'payload_banco': fci_instruction_payload(instruction, cfg.adherente)}

    @app.post('/fci/suscripciones', dependencies=fci_auth)
    async def fci_subscription(instruction: FciSubscriptionRequest, request: Request,
                               b: CredicoopClient = Depends(bank)):
        return await submit_fci('fci_suscripcion', instruction, request, b)

    @app.get('/fci/suscripciones/estado', dependencies=fci_auth)
    async def fci_subscription_status(id_operacion: str | None = None, id_origen: str | None = None,
                                      b: CredicoopClient = Depends(bank)):
        if not id_operacion and not id_origen:
            raise HTTPException(422, 'Indicar id_operacion o id_origen.')
        return await b.fci_operation('suscripcion', id_operacion, id_origen)

    @app.post('/fci/rescates/previsualizar', dependencies=fci_auth)
    async def fci_redemption_preview(instruction: FciRedemptionRequest):
        return {'enviada': False, 'payload_banco': fci_instruction_payload(instruction, cfg.adherente)}

    @app.post('/fci/rescates', dependencies=fci_auth)
    async def fci_redemption(instruction: FciRedemptionRequest, request: Request,
                             b: CredicoopClient = Depends(bank)):
        return await submit_fci('fci_rescate', instruction, request, b)

    @app.get('/fci/rescates/estado', dependencies=fci_auth)
    async def fci_redemption_status(id_operacion: str | None = None, id_origen: str | None = None,
                                    b: CredicoopClient = Depends(bank)):
        if not id_operacion and not id_origen:
            raise HTTPException(422, 'Indicar id_operacion o id_origen.')
        return await b.fci_operation('rescate', id_operacion, id_origen)

    @app.post('/fci/saldos', dependencies=fci_auth)
    async def fci_balances(instruction: FciPositionRequest, b: CredicoopClient = Depends(bank)):
        payload = instruction.model_dump(mode='json')
        payload.update(numeroAdherente=cfg.adherente, idOrigen=str(uuid4()))
        return await b.request('POST', '/api/fci/v1/cuenta-comitente-saldos', body=payload)

    @app.post('/fci/saldos/export.xlsx', dependencies=fci_auth)
    async def export_fci_balances(instruction: FciPositionRequest, b: CredicoopClient = Depends(bank)):
        payload = instruction.model_dump(mode='json')
        payload.update(numeroAdherente=cfg.adherente, idOrigen=str(uuid4()))
        result = await b.request('POST', '/api/fci/v1/cuenta-comitente-saldos', body=payload)
        data = result.get('data', {}) if isinstance(result, dict) else {}
        rows = data.get('saldoDetalle', []) if isinstance(data, dict) else []
        if not isinstance(rows, list):
            raise BankError('Formato de saldos FCI inesperado.')
        headers = list(dict.fromkeys(key for row in rows if isinstance(row, dict) for key in row)) or ['Resultado']
        values = [[row.get(key) for key in headers] for row in rows if isinstance(row, dict)]
        return workbook_response('saldo-fci.xlsx', {'saldos': (headers, values)})

    @app.post('/fci/movimientos', dependencies=fci_auth)
    async def fci_movements(instruction: FciMovementsRequest, b: CredicoopClient = Depends(bank)):
        payload = instruction.model_dump(mode='json')
        payload.update(numeroAdherente=cfg.adherente, idOrigen=str(uuid4()))
        payload['fechaDesde'] = instruction.fechaDesde.strftime('%Y%m%d')
        payload['fechaHasta'] = instruction.fechaHasta.strftime('%Y%m%d')
        return await b.request('POST', '/api/fci/v1/cuenta-comitente-movimientos', body=payload)

    @app.get('/fci/movimientos/detalle', dependencies=fci_auth)
    async def fci_movement_detail(
        tipo: Annotated[str, Query(min_length=1, max_length=10)],
        numero: Annotated[str, Query(min_length=1, max_length=20)],
        sucursal: Annotated[str, Query(min_length=1, max_length=10)],
        formula: Annotated[str, Query(min_length=1, max_length=20)],
        id_origen: Annotated[str | None, Query(max_length=36)] = None,
        b: CredicoopClient = Depends(bank),
    ):
        return await b.request('GET', '/api/fci/v1/cuenta-comitente-movimiento-detalle', params={
            'numeroAdherente': cfg.adherente, 'idOrigen': id_origen or str(uuid4()),
            'tipo': tipo, 'numero': numero, 'sucursal': sucursal, 'formula': formula,
        })

    @app.get('/transferencias/estado', dependencies=auth)
    async def transfer_status(request: Request, id_operacion: str | None = None, id_origen: str | None = None,
                              b: CredicoopClient = Depends(bank)):
        if not id_operacion and not id_origen:
            raise HTTPException(422, 'Indicar id_operacion o id_origen.')
        result = await b.operation('transferencia', id_operacion, id_origen)
        if id_origen:
            request.app.state.journal.save_bank_status('transferencia', id_origen, result)
        return result

    @app.get('/echeqs/estado', dependencies=auth)
    async def echeq_status(id_operacion: str, b: CredicoopClient = Depends(bank)):
        # Sólo el identificador documentado públicamente, sin depender de idOrigen para eCheq.
        return await b.operation('echeq', id_operacion)

    @app.get('/operaciones/{tipo}/{id_origen}', dependencies=auth)
    async def local_status(
        tipo: Literal['transferencia', 'echeq', 'echeq_gestion', 'fci_suscripcion', 'fci_rescate'],
        id_origen: str,
        request: Request,
    ):
        row = request.app.state.journal.get(tipo, id_origen)
        if row is None:
            raise HTTPException(404, 'No hay registro local para ese idOrigen.')
        return row

    @app.get('/beneficiarios/transferencias', dependencies=auth)
    async def transfer_beneficiary(cbu_cvu: Annotated[str, Query(pattern=r'^\d{22}$')], b: CredicoopClient = Depends(bank)):
        return await b.request('GET', f'/api/transferencias/v1/beneficiario/{cfg.adherente}', params={'cbuCvu': cbu_cvu})

    @app.get('/beneficiarios/echeqs', dependencies=auth)
    async def echeq_beneficiary(documento: Annotated[str, Query(pattern=r'^\d{11}$')],
                                documento_tipo: Literal['CUIT', 'CUIL', 'CDI'] = 'CUIT', b: CredicoopClient = Depends(bank)):
        return await b.request('GET', f'/api/echeq/v1/beneficiario/{cfg.adherente}', params={'documento': documento, 'documentoTipo': documento_tipo})

    @app.get('/destinatarios/consulta', dependencies=auth)
    async def destination(cbu_cvu: Annotated[str | None, Query(pattern=r'^\d{22}$')] = None,
                          alias: str | None = None, moneda: Literal['ARS', 'USD'] = 'ARS', b: CredicoopClient = Depends(bank)):
        if bool(cbu_cvu) == bool(alias):
            raise HTTPException(422, 'Indicar un CBU/CVU o un alias, uno solo.')
        params = {'moneda': moneda, 'idOrigen': secrets.token_hex(16)}
        params['cbuCvu' if cbu_cvu else 'alias'] = cbu_cvu or alias
        return await b.request('GET', f'/api/conscbucvualias/v1/consulta/{cfg.adherente}', params=params)

    return app
