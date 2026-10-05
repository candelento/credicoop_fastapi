import secrets
import json
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyHeader
from .client import BankError, CredicoopClient
from .config import Settings, argentina_today
from .journal import DuplicateInstruction, Journal
from .models import (
    EcheqRequest, FCI_SIGNER_DNI, FciMovementsRequest, FciPositionRequest, FciRedemptionRequest,
    FciSubscriptionRequest, OrderDebitAccount, TransferRequest, fci_instruction_payload, instruction_payload,
)
from .orders import DriveOrderError, DriveOrderService, OrderParseError, SupplierMasterError, build_order_instruction

api_key_header = APIKeyHeader(name='X-API-Key', auto_error=False)


def create_app(settings: Settings | None = None, client: CredicoopClient | None = None, *, demo: bool = False):
    cfg = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.bank = client or CredicoopClient(cfg)
        app.state.journal = Journal(cfg.journal_path)
        app.state.drive_orders = DriveOrderService(cfg, project_root)
        yield
        await app.state.bank.close()

    app = FastAPI(title='Credicoop — operaciones con firma en BIE', version='1.2.0', lifespan=lifespan,
        description='Consultas de cuentas, movimientos y FCI. Transferencias, eCheqs, suscripciones y rescates se envían a la firma; la autorización y activación se realizan en Banca Internet Empresa.')

    async def authorized(key: Annotated[str | None, Security(api_key_header)]):
        if not key or not secrets.compare_digest(key, cfg.api_key.get_secret_value()):
            raise HTTPException(401, 'Clave local X-API-Key inválida o ausente.')

    def fci_scope_enabled():
        if 'fciConFirma' not in cfg.scopes.split():
            raise HTTPException(503, 'Falta el scope fciConFirma en CREDICOOP_SCOPES. Confirmá antes con el banco que el adherente esté habilitado.')

    def bank(request: Request):
        return request.app.state.bank

    auth = [Depends(authorized)]
    fci_auth = auth + [Depends(fci_scope_enabled)]
    project_root = Path(__file__).resolve().parents[1]
    app.mount('/static', StaticFiles(directory=project_root / 'app' / 'static'), name='static')

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

    @app.get('/salud')
    async def health():
        return {'estado': 'ok', 'modalidad': 'firma posterior en BIE'}

    @app.get('/configuracion', dependencies=auth)
    async def configuration():
        return {'adherente': cfg.adherente, 'fecha_actual_argentina': argentina_today().isoformat(),
                'fecha_operativa_banco': cfg.operational_today().isoformat(),
                'homologacion': cfg.is_homologation,
                'simulacion': demo,
                'fci_scope_habilitado': 'fciConFirma' in cfg.scopes.split(),
                'fci_firmante_dni': FCI_SIGNER_DNI,
                'movimientos_hasta_predeterminado': 'fecha actual de Argentina'}

    @app.get('/cuentas', dependencies=auth)
    async def accounts(b: CredicoopClient = Depends(bank)):
        return await b.accounts()

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
        try:
            result = await b.movements(nro_cuenta, fecha_desde, end, cod_operativo)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
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

    @app.post('/echeqs/previsualizar', dependencies=auth)
    async def preview_echeq(instruction: EcheqRequest):
        return {'enviada': False, 'payload_banco': prepare(instruction)}

    async def submit(kind, instruction, request, b, *, path=None, payload=None):
        payload = payload or prepare(instruction)
        journal = request.app.state.journal
        # La reserva se confirma en disco ANTES de invocar el banco.
        journal.reserve(kind, payload)
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
        if not isinstance(data, dict) or not data.get('idOperacion'):
            journal.finish(kind, instruction.idOrigen, 'RESULTADO_INCIERTO', response)
            raise BankError('Respuesta sin idOperacion. Consultar BIE antes de repetir.', 502, response, ambiguous=True)
        journal.finish(kind, instruction.idOrigen, 'RESPUESTA_RECIBIDA', response)
        # El estado real del banco se conserva; no se fuerza a "pendiente" ni "pagado".
        return {'idOrigen': instruction.idOrigen, 'modalidad': 'ConFirma', 'respuesta_banco': response,
                'siguiente_paso': 'Consultar el estado y completar firma y activación en Banca Internet Empresa.'}

    @app.post('/transferencias', dependencies=auth)
    async def transfer(instruction: TransferRequest, request: Request, b: CredicoopClient = Depends(bank)):
        return await submit('transferencia', instruction, request, b)

    @app.post('/echeqs', dependencies=auth)
    async def echeq(instruction: EcheqRequest, request: Request, b: CredicoopClient = Depends(bank)):
        return await submit('echeq', instruction, request, b)

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
    async def transfer_status(id_operacion: str | None = None, id_origen: str | None = None,
                              b: CredicoopClient = Depends(bank)):
        if not id_operacion and not id_origen:
            raise HTTPException(422, 'Indicar id_operacion o id_origen.')
        return await b.operation('transferencia', id_operacion, id_origen)

    @app.get('/echeqs/estado', dependencies=auth)
    async def echeq_status(id_operacion: str, b: CredicoopClient = Depends(bank)):
        # Sólo el identificador documentado públicamente, sin depender de idOrigen para eCheq.
        return await b.operation('echeq', id_operacion)

    @app.get('/operaciones/{tipo}/{id_origen}', dependencies=auth)
    async def local_status(
        tipo: Literal['transferencia', 'echeq', 'fci_suscripcion', 'fci_rescate'],
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
