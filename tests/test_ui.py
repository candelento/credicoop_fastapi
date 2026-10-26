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
        assert 'data-view="proveedores"' not in home.text
        assert 'Órdenes GECOM PDF' not in home.text
        assert 'Órdenes GECOM ·' in home.text
        assert 'Buscar importe' in home.text
        assert 'class="nav-icon"' in home.text
        assert 'aria-controls="primary-navigation"' in home.text
        assert 'class="sidebar-logout"' in home.text
        assert '<dialog id="reauth-dialog"' in home.text
        assert 'cada 30 minutos' in home.text
        assert 'Todo listo para revisar' in home.text
        assert 'class="review-progress"' in home.text
        assert 'Tu actividad, en un vistazo' in home.text
        assert 'TU CENTRO DE OPERACIONES' not in home.text
        assert 'Saldos, pagos y próximos pasos.' not in home.text
        assert 'Seguí cada movimiento' in home.text
        assert 'id="movement-kpis"' in home.text
        assert 'id="movement-clear-filters"' in home.text
        assert 'id="echeq-list-location"' not in home.text
        assert 'id="echeq-manage-form"' not in home.text
        assert 'Estados de eCheqs' not in home.text
        assert 'Preparar una gestión' not in home.text
        assert 'id="echeq-manage-id"' not in home.text
        assert 'id="echeq-manage-cmc7"' not in home.text
        assert 'class="connection"' not in home.text
        assert 'id="session-profile"' in home.text
        assert home.text.index('id="view-usuarios"') < home.text.index('id="change-password"')
        assert 'Disponibilidad por cuenta' in home.text
        assert 'dashboard-pending-total' in home.text
        assert home.text.count('id="environment"') == 1
        assert 'environment-detail' not in home.text
        assert home.text.count('data-dashboard-view=') == 4
        assert 'class="period-switch"' in home.text
        assert home.text.count('aria-pressed="false"') == 3
        assert 'type="file"' not in home.text
        assert 'Importar PDF' not in home.text
        assert 'Buscar en Drive' in home.text
        assert '<dialog id="drive-order-preview"' in home.text
        assert '<dialog id="drive-batch-preview"' in home.text
        assert 'Confirmar y enviar a firma' in home.text
        assert '<details open><summary>Datos que recibirá el banco' not in home.text
        assert 'Consultar estado bancario' in home.text
        assert 'Descargar JSON' not in home.text
        assert 'Fondos comunes de inversión 1810' in home.text
        assert 'Sistema Bancario | RONANFER' in home.text
        assert 'Iniciar sesión' in home.text
        assert 'frame-ancestors' in home.headers['content-security-policy']
        assert DEMO_KEY not in home.text
        script = api.get('/static/app.js')
        assert script.status_code == 200
        assert '/echeqs/listar' not in script.text and '/echeqs/gestionar' not in script.text
        assert '/ordenes-pago/subir' not in script.text
        assert "openOrderReview('drive-order-preview')" in script.text
        assert api.get('/static/style.css').status_code == 200
        assert api.get('/static/workspace.css').status_code == 200
        assert api.get('/static/auth.css').status_code == 200
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


def test_demo_user_session_dashboard_and_echeq_tools():
    with TestClient(create_demo_app()) as api:
        login = api.post('/login', json={'username': 'demo', 'password': DEMO_KEY})
        assert login.status_code == 200 and 'httponly' in login.headers['set-cookie'].lower()
        assert api.get('/auth/me').json()['usuario'] == 'demo'
        dashboard = api.get('/dashboard')
        assert dashboard.status_code == 200 and dashboard.json()['cantidad_cuentas'] == 2
        listed = api.post('/echeqs/listar', json={'idOrigen': 'demo-list-001', 'filtro': {'estado': 'ACTIVO'}})
        assert listed.status_code == 200 and listed.json()['data']['totalCheques'] == 1
        body = {'idOrigen': 'demo-management-001', 'cbuCuenta': '1910000000000000000000',
                'accion': 'ACEPTAR', 'echeqs': [{'idCheque': 'DEMOECHEQ001'}]}
        managed = api.post('/echeqs/gestionar', json=body)
        assert managed.status_code == 200 and managed.json()['respuesta_banco']['data']['simulacion']
        local = api.get('/operaciones/echeq_gestion/demo-management-001')
        assert local.status_code == 200 and local.json()['actor'] == 'demo'


def test_demo_fci_is_simulated_and_uses_fixed_signer():
    with TestClient(create_demo_app()) as api:
        h = {'X-API-Key': DEMO_KEY}
        config = api.get('/configuracion', headers=h).json()
        assert config['fci_scope_habilitado']
        assert config['fci_firmante_dni'] == '44379155'
        assert api.get('/fci/cuentas-comitentes', headers=h).json()['data']['cuentasComitentes']
        assert api.get('/fci/fondos', headers=h).json()['data']['detalleFondo'][0]['codigo'] == 'FCAD'
        account = {'tipoCuenta': 'ORDI', 'sucursalCuenta': '119', 'numeroCuenta': '011123/9'}
        assert api.post('/fci/saldos', headers=h, json={'cuentaComitente': account}).json()['simulacion']
        movement_body = {'cuentaComitente': account, 'fechaDesde': '2026-08-01', 'fechaHasta': '2026-08-28'}
        assert api.post('/fci/movimientos', headers=h, json=movement_body).json()['simulacion']
        detail = api.get('/fci/movimientos/detalle?tipo=RESC&numero=500&sucursal=0123&formula=7018151', headers=h)
        assert detail.status_code == 200 and detail.json()['simulacion']
        body = {'idOrigen': 'demo-fci-sub-001', 'cbuCuentaDebito': '1910000000000000000000',
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
