"""Servidor demostrativo sin red bancaria. No requiere la llave del banco ni .env."""
import json
import tempfile
from pathlib import Path
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from .client import CredicoopClient
from .config import Settings
from .main import create_app

DEMO_KEY = 'demo-local-credicoop-12345678901234567890'
_temporary = None


def create_demo_app():
    global _temporary
    _temporary = tempfile.TemporaryDirectory(prefix='credicoop_demo_')
    root = Path(_temporary.name)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = root / 'demo.pem'
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cfg = Settings(_env_file=None, base_url='https://homoapibccl.bancocredicoop.coop',
                   realm_url='https://homoapibccl.bancocredicoop.coop/auth/realms/homologacion',
                   client_id='30662210877', adherente=661395, api_key=DEMO_KEY,
                   fecha_operativa='2026-08-28', private_key_path=path, journal_path=root / 'demo.sqlite3',
                   private_key_password=None, ca_bundle=None,
                   scopes='cuentas transferenciasConFirma echeqConFirma fciConFirma beneficiarioTransferencia beneficiarioEcheq consultaCbuCvuAlias')
    operations = {}
    counter = 900000

    def handler(req):
        nonlocal counter
        route = req.url.path
        if route.endswith('/token'):
            return httpx.Response(200, json={'access_token': 'token-simulado', 'expires_in': 1800})
        if route.endswith('/listaCuentas'):
            return httpx.Response(200, json={'clarifCuentas': [
                {'nroCuenta': '00060065641', 'denominacionCuenta': 'EMPRESA DEMO CTA CTE 2', 'saldo': '261792648.67', 'tipoCuenta': 'CC', 'moneda': 'ARS', 'CBU': '1910000000000000000000'},
                {'nroCuenta': '00060065642', 'denominacionCuenta': 'EMPRESA DEMO CTA CTE 1', 'saldo': '5820510.20', 'tipoCuenta': 'CC', 'moneda': 'ARS', 'CBU': '1910000000000000000001'}]})
        if route.startswith('/api/cuentas/') and route.endswith('/movimientos'):
            return httpx.Response(200, json={'consMovCtas': [
                {'fecha': req.url.params['fechaHasta'], 'descripcion': 'ENCABEZADO', 'monto': 261792648.67, 'saldo': 261792648.67},
                {'fecha': req.url.params['fechaHasta'], 'descripcion': 'Transferencia recibida DEMO', 'indDBCR': 'CR', 'monto': 150000, 'saldo': 261792648.67, 'nroComprobante': 'D001', 'idTransaccion': 'DEMO-001'},
                {'fecha': req.url.params['fechaDesde'], 'descripcion': 'Pago a proveedor DEMO', 'indDBCR': 'DB', 'monto': 25000, 'saldo': 261642648.67, 'nroComprobante': 'D002', 'idTransaccion': 'DEMO-002'}]})
        if route.endswith('/cuentas-comitentes'):
            return httpx.Response(200, json={'data': {'estadoTestInversor': 'Vigente', 'perfilInversor': 'MODERADO',
                'cuentasComitentes': [{'tipoCuenta': 'ORDI', 'sucursalCuenta': '119', 'numeroCuenta': '011123/9'}],
                'cuentasVinculadas': [{'cbu': '1910000000000000000000'}]}, 'simulacion': True})
        if route.endswith('/fondos'):
            return httpx.Response(200, json={'data': {'detalleFondo': [
                {'codigo': 'FCAD', 'nombre': '1810 AHORRO DEMO', 'moneda': 'ARS',
                 'valorCuotaparte': '146.25926100', 'perfil': 'Conservador', 'plazo': 'Inmediato'}]},
                'simulacion': True})
        if route.endswith('/cuenta-comitente-saldos'):
            return httpx.Response(200, json={'data': {'saldoDetalle': [
                {'codigo': 'FCAD', 'nombreFondo': '1810 AHORRO DEMO', 'moneda': 'ARS',
                 'cuotapartes': '100.0000', 'valorCuotaparte': '146.25926100',
                 'saldoDisponibleValorizado': '14625.93'}]}, 'simulacion': True})
        if route.endswith('/cuenta-comitente-movimientos'):
            return httpx.Response(200, json={'data': {'movimientos': [], 'totalMovimientos': 0}, 'simulacion': True})
        if route.endswith('/cuenta-comitente-movimiento-detalle'):
            return httpx.Response(200, json={'data': {'detalle': []}, 'simulacion': True})
        if '/beneficiario/' in route:
            return httpx.Response(200, json={'datos': dict(req.url.params), 'estado': 'Beneficiario habilitado DEMO', 'simulacion': True})
        if req.method == 'POST' and '/ConFirma/' in route:
            body = json.loads(req.content)
            counter += 1
            response = {'data': {'idOperacion': counter, 'idOrigen': body['idOrigen'],
                                 'estadoOperacion': {'descripcion': 'Enviada a la firma'},
                                 'simulacion': True}}
            operations[str(counter)] = response
            operations[body['idOrigen']] = response
            return httpx.Response(200, json=response)
        if req.method == 'GET' and route.endswith(('/transferencia', '/emision', '/suscripcion', '/rescate')):
            op = req.url.params.get('idOperacion') or req.url.params.get('idOrigen')
            if op in operations:
                return httpx.Response(200, json=operations[op])
            return httpx.Response(404, json={'codigo': 'DEMO-NO-EXISTE', 'descripcion': 'Operación no encontrada en esta sesión demo.'})
        return httpx.Response(404, json={'codigo': 'DEMO-RUTA', 'descripcion': 'Ruta no simulada.'})

    bank = CredicoopClient(cfg, httpx.MockTransport(handler), interval=0)
    return create_app(cfg, bank, demo=True)
