from fastapi.testclient import TestClient
import httpx
from app.client import CredicoopClient
from app.demo import DEMO_KEY, create_demo_app
from app.main import create_app
from app.config import Settings


def test_home_assets_and_test_data_require_key():
    with TestClient(create_demo_app()) as api:
        home = api.get('/')
        assert home.status_code == 200 and 'text/html' in home.headers['content-type']
        assert 'Preparación de pagos' in home.text
        assert 'Órdenes de pago en PDF' in home.text
        assert 'Fondos comunes de inversión 1810' in home.text
        assert 'frame-ancestors' in home.headers['content-security-policy']
        assert DEMO_KEY not in home.text
        app_js = api.get('/static/app.js')
        styles = api.get('/static/style.css')
        assert app_js.status_code == 200 and 'method-badge' in app_js.text
        assert styles.status_code == 200 and '.exchange-card-request' in styles.text
        assert 'Request / response a la API del banco' in home.text
        assert '/api/fci/v1/fondos' in home.text
        assert 'Órdenes PDF' not in home.text
        assert 'Datos del beneficiario devueltos por el banco' in home.text
        assert 'beneficiary-response-fields' in home.text
        assert 'beneficiary-response-json' in home.text
        assert 'Consultar último envío' in home.text
        assert api.get('/homologacion/beneficiarios').status_code == 401
        h = {'X-API-Key': DEMO_KEY}
        assert api.get('/ordenes-pago', headers=h).status_code == 404
        assert api.post('/ordenes-pago/sincronizar', headers=h).status_code == 404
        config = api.get('/configuracion', headers=h).json()
        assert config['simulacion'] and config['homologacion']
        data = api.get('/homologacion/beneficiarios', headers=h).json()
        assert all(b['uso'] == 'emision' for b in data['beneficiarios'])
        assert {b['tipo'] for b in data['beneficiarios']} == {'transferencia', 'echeq'}
        orders = api.get('/homologacion/ordenes', headers=h).json()
        assert orders['importe_prueba_predeterminado'] == '15.79'
        assert len(orders['ordenes']) == 3
        assert orders['ordenes'][0]['importeOriginal'] == '181943.75'


def test_homologation_samples_blocked_in_production(tmp_path):
    cfg = Settings(_env_file=None, api_key='a'*40, base_url='https://api.example.com',
                   realm_url='https://api.example.com/auth/realms/produccion', fecha_operativa=None,
                   journal_path=tmp_path/'ops.sqlite3')
    bank = CredicoopClient(cfg, httpx.MockTransport(lambda req: httpx.Response(500, json={})), interval=0)
    with TestClient(create_app(cfg, bank)) as api:
        h = {'X-API-Key':'a'*40}
        assert api.get('/homologacion/beneficiarios', headers=h).status_code == 404
        assert api.get('/homologacion/ordenes', headers=h).status_code == 404


def test_demo_never_requires_bank_credentials():
    with TestClient(create_demo_app()) as api:
        h = {'X-API-Key':DEMO_KEY}
        a = api.get('/cuentas', headers=h).json()['clarifCuentas'][0]
        assert 'DEMO' in a['denominacionCuenta']
        request = {'idOrigen':'demo-test-001','cbuCuentaDebito':a['CBU'],
                   'beneficiarios':[{'cbuCvu':'0290023010000000555675','monto':'15.79',
                                    'cui':'30677886370','nombre':'KRAFT ELVA ROSA'}]}
        r = api.post('/transferencias', json=request, headers=h)
        assert r.status_code == 200 and r.json()['respuesta_banco']['data']['simulacion']
        assert api.post('/transferencias', json=request, headers=h).status_code == 409


def test_demo_fci_is_simulated_and_uses_fixed_signer():
    with TestClient(create_demo_app()) as api:
        h = {'X-API-Key': DEMO_KEY}
        config = api.get('/configuracion', headers=h).json()
        assert config['fci_scope_habilitado']
        assert config['fci_firmante_dni'] == '44379155'
        accounts = api.get('/fci/cuentas-comitentes', headers=h).json()
        assert accounts['data']['cuentasComitentes']
        assert accounts['data']['cuentasVinculadas'][0]['cbu'] == '1910054455005400309496'
        assert 'avisoCbuVinculado' in accounts['data']
        assert api.get('/fci/fondos', headers=h).json()['data']['detalleFondo'][0]['codigo'] == 'FCAD'
        account = {'tipoCuenta': 'ORDI', 'sucursalCuenta': '119', 'numeroCuenta': '011123/9'}
        assert api.post('/fci/saldos', headers=h, json={'cuentaComitente': account}).json()['simulacion']
        movement_body = {'cuentaComitente': account, 'fechaDesde': '2026-08-01', 'fechaHasta': '2026-08-28'}
        assert api.post('/fci/movimientos', headers=h, json=movement_body).json()['simulacion']
        detail = api.get('/fci/movimientos/detalle?tipo=RESC&numero=500&sucursal=0123&formula=7018151', headers=h)
        assert detail.status_code == 200 and detail.json()['simulacion']
        body = {'idOrigen': 'demo-fci-sub-001', 'cbuCuentaDebito': '1910054455005400309496',
                'cuentaComitente': account, 'solicitudSuscripcion': {
                    'codigoFondo': 'FCAD', 'moneda': 'ARS', 'monto': '100.00',
                    'avanzarTestVencido': False, 'aceptarRiesgoExcedido': False}}
        preview = api.post('/fci/suscripciones/previsualizar', headers=h, json=body)
        assert preview.status_code == 200
        assert preview.json()['payload_banco']['operadoresFirmantes'] == [
            {'documento': '44379155', 'documentoTipo': 'DNI'}
        ]
        sent = api.post('/fci/suscripciones', headers=h, json=body)
        assert sent.status_code == 200 and sent.json()['respuesta_banco']['data']['simulacion']
        assert api.get('/fci/suscripciones/estado?id_origen=demo-fci-sub-001', headers=h).status_code == 200
