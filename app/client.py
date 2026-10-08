import asyncio
import base64
from contextvars import ContextVar
import json
import ssl
import time
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4
import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from .config import Settings
from .evidence import EvidenceRecorder, exchange_snapshot

BANK_EXCHANGES: ContextVar[list[dict] | None] = ContextVar('bank_exchanges', default=None)

CON_FIRMA_POSTS = {
    '/api/transferencias/v1/ConFirma/transferencia',
    '/api/echeq/v1/ConFirma/emision',
    '/api/fci/v1/ConFirma/suscripcion',
    '/api/fci/v1/ConFirma/rescate',
    '/api/echeq/v1/ConFirma/gestion',
}
MUTATION_POSTS = {
    '/api/transferencias/v1/beneficiario',
    '/api/echeq/v1/beneficiario',
}
QUERY_POSTS = {
    '/api/fci/v1/cuenta-comitente-saldos',
    '/api/fci/v1/cuenta-comitente-movimientos',
    '/api/echeq/v1/lista-cheques',
}
ENDPOINT_INFO = {
    '/api/cuentas/v1/listaCuentas': ('Consultar cuentas', 'cuentas'),
    '/api/transferencias/v1/beneficiario': ('Alta de beneficiario de transferencia', 'beneficiarioTransferencia'),
    '/api/echeq/v1/beneficiario': ('Alta de beneficiario de eCheq', 'beneficiarioEcheq'),
    '/api/transferencias/v1/ConFirma/transferencia': ('Transferir con firma', 'transferenciasConFirma'),
    '/api/transferencias/v1/transferencia': ('Consultar transferencia', 'transferenciasConFirma'),
    '/api/echeq/v1/ConFirma/emision': ('Emitir eCheq con firma', 'echeqConFirma'),
    '/api/echeq/v1/emision': ('Consultar emisión de eCheq', 'echeqConFirma'),
    '/api/echeq/v1/lista-cheques': ('Listar eCheqs', 'echeqConFirma'),
    '/api/echeq/v1/ConFirma/gestion': ('Gestionar eCheqs con firma', 'echeqConFirma'),
}


class BankError(Exception):
    def __init__(self, message, status=502, details=None, ambiguous=False):
        super().__init__(message)
        self.status, self.details, self.ambiguous = status, details, ambiguous


def redact(value):
    if isinstance(value, dict):
        return {k: ('[REDACTADO]' if any(s in k.lower() for s in ('token', 'assertion', 'private', 'password', 'authorization', 'x-api-key')) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(x) for x in value]
    return value


def signed_assertion(settings: Settings) -> str:
    try:
        password = settings.private_key_password.get_secret_value().encode() if settings.private_key_password else None
        key = serialization.load_pem_private_key(settings.private_key_path.read_bytes(), password)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ValueError('RSA required')
    except (OSError, ValueError, TypeError):
        raise BankError('No se pudo cargar la llave RSA configurada.', 503) from None
    def enc(obj):
        return base64.urlsafe_b64encode(json.dumps(obj, separators=(',', ':')).encode()).rstrip(b'=')
    now = int(time.time())
    payload = {'iss': settings.client_id, 'sub': settings.client_id, 'aud': settings.realm_url.rstrip('/'), 'iat': now, 'exp': now + 60, 'jti': str(uuid4())}
    unsigned = enc({'alg': 'RS256', 'typ': 'JWT'}) + b'.' + enc(payload)
    signature = key.sign(unsigned, padding.PKCS1v15(), hashes.SHA256())
    return (unsigned + b'.' + base64.urlsafe_b64encode(signature).rstrip(b'=')).decode()


class CredicoopClient:
    def __init__(self, settings: Settings, transport=None, interval=1.25):
        self.settings = settings
        context = ssl.create_default_context(cafile=str(settings.ca_bundle) if settings.ca_bundle else None)
        self.http = httpx.AsyncClient(timeout=settings.timeout, verify=context, transport=transport, follow_redirects=False)
        self.evidence = EvidenceRecorder(Path('evidencias')) if transport is None else None
        self._token = None
        self._expiry = 0
        self._auth_lock = asyncio.Lock()
        self._rate_lock = asyncio.Lock()
        self._last_request = 0
        self._interval = interval

    async def close(self):
        await self.http.aclose()

    async def _send(self, request, function: str, scope: str, *, ambiguous=False):
        try:
            response = await self.http.send(request)
        except BaseException as exc:
            exchanges = BANK_EXCHANGES.get()
            if exchanges is not None:
                exchanges.append(exchange_snapshot(
                    request, error=f'{type(exc).__name__}: {exc}',
                ))
            if self.evidence:
                self.evidence.record(
                    function, scope, request,
                    error=f'{type(exc).__name__}: {exc}',
                    ambiguous=ambiguous,
                )
            raise
        exchanges = BANK_EXCHANGES.get()
        if exchanges is not None:
            exchanges.append(exchange_snapshot(request, response))
        if self.evidence:
            self.evidence.record(function, scope, request, response, ambiguous=ambiguous)
        return response

    async def _pace(self):
        # Máximo global 50/minuto; se ejecuta en un solo proceso/worker.
        async with self._rate_lock:
            delay = self._interval - (time.monotonic() - self._last_request)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request = time.monotonic()

    async def token(self):
        async with self._auth_lock:
            if self._token and time.monotonic() < self._expiry:
                return self._token
            assertion = signed_assertion(self.settings)
            await self._pace()
            try:
                request = self.http.build_request('POST', self.settings.token_url, data={
                    'grant_type': 'client_credentials', 'client_id': self.settings.client_id,
                    'scope': self.settings.scopes,
                    'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
                    'client_assertion': assertion,
                }, headers={'Accept': 'application/json'})
                response = await self._send(request, 'Autenticación OAuth', self.settings.scopes)
            except httpx.HTTPError:
                raise BankError('No se pudo contactar el servicio de autenticación del banco.', 503) from None
            if response.status_code != 200:
                raise BankError('El banco rechazó la autenticación; revisar credenciales, reloj y scopes.', 502,
                                {'http_banco': response.status_code})
            try:
                data = response.json()
                token = data['access_token']
                ttl = float(data['expires_in'])
                if not isinstance(token, str) or not token or ttl <= 0:
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise BankError('Respuesta de autenticación inválida.', 502) from None
            # Usar el vencimiento recibido, sin persistir ni exponer el token.
            self._token = token
            self._expiry = time.monotonic() + max(0, ttl - min(30, ttl / 2))
            return token

    async def request(self, method, path, *, params=None, body=None):
        if not path.startswith('/api/'):
            raise ValueError('Ruta del banco inválida.')
        if method == 'POST' and path not in CON_FIRMA_POSTS | MUTATION_POSTS | QUERY_POSTS:
            raise ValueError('Sólo se permiten consultas y operaciones ConFirma.')
        transaction = method == 'POST' and path in (CON_FIRMA_POSTS | MUTATION_POSTS)
        function, scope = ENDPOINT_INFO.get(path, (path, self.settings.scopes))
        if path.startswith('/api/cuentas/v1/') and path.endswith('/movimientos'):
            function, scope = 'Consultar movimientos', 'cuentas'
        elif path.startswith('/api/transferencias/v1/beneficiario/'):
            function, scope = 'Consultar beneficiario de transferencia', 'beneficiarioTransferencia'
        elif path.startswith('/api/echeq/v1/beneficiario/'):
            function, scope = 'Consultar beneficiario de eCheq', 'beneficiarioEcheq'
        for attempt in range(2):
            token = await self.token()
            await self._pace()
            try:
                request = self.http.build_request(
                    method, self.settings.base_url.rstrip('/') + path,
                    params=params, json=body,
                    headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'},
                )
                response = await self._send(request, function, scope, ambiguous=transaction)
            except httpx.HTTPError:
                raise BankError('No se obtuvo respuesta del banco. Consultar el estado antes de repetir.',
                                504, ambiguous=transaction) from None
            # Reautenticación sólo de lecturas. Nunca reintentar pagos automáticamente.
            if response.status_code == 401:
                async with self._auth_lock:
                    if self._token == token:
                        self._token, self._expiry = None, 0
                if method == 'GET' and attempt == 0:
                    continue
            try:
                data = response.json()
            except ValueError:
                raise BankError('El banco devolvió una respuesta no JSON.', 502,
                                {'http_banco': response.status_code}, ambiguous=transaction) from None
            data = redact(data)
            if response.is_error or response.is_redirect:
                raise BankError('El banco rechazó la solicitud.', 502,
                                {'http_banco': response.status_code, 'respuesta': data},
                                ambiguous=(transaction and response.status_code >= 500))
            if not isinstance(data, dict):
                raise BankError('Formato de respuesta del banco inesperado.', 502, ambiguous=transaction)
            if (data.get('error') or data.get('errores')
                    or ('codigo' in data and str(data['codigo']) not in ('0', '200', 'None', ''))):
                raise BankError('El banco informó errores en la operación.', 502, data)
            return data
        raise BankError('No se pudo autenticar la consulta.')

    async def accounts(self):
        return await self.request('GET', '/api/cuentas/v1/listaCuentas')

    async def fci_accounts(self):
        return await self.request('GET', '/api/fci/v1/cuentas-comitentes', params={
            'numeroAdherente': self.settings.adherente, 'idOrigen': str(uuid4()),
        })

    async def fci_funds(self):
        return await self.request('GET', '/api/fci/v1/fondos', params={
            'numeroAdherente': self.settings.adherente, 'idOrigen': str(uuid4()),
        })

    async def fci_operation(self, kind, operation_id=None, origin_id=None):
        if kind not in ('suscripcion', 'rescate'):
            raise ValueError('Tipo de operación FCI inválido.')
        if not operation_id and not origin_id:
            raise ValueError('Indicar id_operacion o id_origen.')
        params = {'numeroAdherente': self.settings.adherente}
        if operation_id:
            params['idOperacion'] = operation_id
        if origin_id:
            params['idOrigen'] = origin_id
        return await self.request('GET', f'/api/fci/v1/{kind}', params=params)

    async def movements(self, account: str, start: date, end: date, code=None):
        if start > end:
            raise ValueError('fecha_desde debe ser menor o igual a fecha_hasta.')
        if (end - start).days > 366:
            raise ValueError('Consultar rangos de hasta 367 días por solicitud.')
        headers, rows, incomplete = [], [], []

        async def fetch(a, b):
            params = {'fechaDesde': a.strftime('%Y%m%d'), 'fechaHasta': b.strftime('%Y%m%d')}
            if code:
                params['codOperativo'] = code
            data = await self.request('GET', f'/api/cuentas/v1/{account}/movimientos', params=params)
            records = data.get('consMovCtas')
            if not isinstance(records, list) or any(not isinstance(x, dict) for x in records):
                raise BankError('Falta la lista consMovCtas en la respuesta del banco.')
            if data.get('alerta') and a < b:
                middle = a + (b-a)//2
                # Conservar sólo subrangos sin superposición, no los registros parciales del padre.
                await fetch(middle + timedelta(days=1), b)
                await fetch(a, middle)
                return
            for x in records:
                if x.get('descripcion') == 'ENCABEZADO':
                    headers.append({'fecha_desde': a.isoformat(), 'fecha_hasta': b.isoformat(), 'datos': x})
                else:
                    rows.append(x)
            if data.get('alerta'):
                incomplete.append({'fecha': a.isoformat(), 'alerta': data['alerta']})

        await fetch(start, end)
        return {'nroCuenta': account, 'fecha_desde': start.isoformat(), 'fecha_hasta': end.isoformat(),
                'completa': not incomplete, 'rangos_incompletos': incomplete,
                'encabezados': headers, 'movimientos': rows}

    async def operation(self, kind, operation_id=None, origin_id=None):
        if kind not in ('transferencia', 'echeq'):
            raise ValueError('Tipo inválido.')
        if not operation_id and not origin_id:
            raise ValueError('Indicar id_operacion o id_origen.')
        params = {'numeroAdherente': self.settings.adherente}
        if operation_id:
            params['idOperacion'] = operation_id
        if origin_id:
            # La colección permite idOrigen; la página pública de eCheq sólo documenta idOperacion.
            params['idOrigen'] = origin_id
        path = '/api/transferencias/v1/transferencia' if kind == 'transferencia' else '/api/echeq/v1/emision'
        return await self.request('GET', path, params=params)
