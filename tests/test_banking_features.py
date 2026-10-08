import json
from datetime import date

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.client import CredicoopClient
from app.config import Settings
from app.evidence import EvidenceRecorder
from app.main import create_app
from app.models import (
    EcheqListRequest,
    EcheqManagementRequest,
    echeq_list_payload,
    echeq_management_payload,
)


@pytest.fixture
def settings(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_path = tmp_path / 'key.pem'
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    return Settings(
        _env_file=None,
        api_key='k' * 40,
        private_key_path=key_path,
        journal_path=tmp_path / 'journal.sqlite3',
        fecha_operativa=date(2026, 8, 28),
    )


def token_response(request):
    if request.url.path.endswith('/token'):
        return httpx.Response(200, json={'access_token': 'test', 'expires_in': 1800})
    return None


def test_echeq_listing_defaults_and_date_format():
    request = EcheqListRequest(
        idOrigen='listar-001',
        filtro={
            'gestion': 'RECIBIDOS',
            'estado': 'ACTIVO',
            'fechaPagoDesde': '2026-08-01',
        },
    )
    payload = echeq_list_payload(request, 661395)
    assert payload['numeroAdherente'] == 661395
    assert payload['filtro']['pagina'] == 1
    assert payload['filtro']['limite'] == 20
    assert payload['filtro']['fechaPagoDesde'] == '20260801'


def test_echeq_listing_rejects_bad_state_dates_and_page_limit():
    with pytest.raises(ValidationError):
        EcheqListRequest(idOrigen='bad-state', filtro={'gestion': 'GENERADOS', 'estado': 'INVENTADO'})
    with pytest.raises(ValidationError):
        EcheqListRequest(idOrigen='bad-range', filtro={
            'gestion': 'GENERADOS',
            'fechaEmisionDesde': '2026-08-29',
            'fechaEmisionHasta': '2026-08-28',
        })
    with pytest.raises(ValidationError):
        EcheqListRequest(idOrigen='bad-limit', filtro={'gestion': 'GENERADOS', 'limite': 10})


def test_echeq_management_action_contracts_and_payload():
    accept = EcheqManagementRequest(
        idOrigen='aceptar-001', cbuCuenta='1910000000000000000000',
        accion='ACEPTAR', echeqs=[{'idCheque': 'REAL-ID-1'}],
    )
    assert echeq_management_payload(accept, 661395)['accion'] == 'ACEPTAR'

    endorsement = EcheqManagementRequest(
        idOrigen='endosar-001', cbuCuenta='1910000000000000000000',
        accion='ENDOSAR', tipoEndoso='NOM',
        beneficiario={'documento': '30546125501', 'documentoTipo': 'CUIT'},
        echeqs=[{'cmc7': '19134927202001001234490140027'}],
    )
    assert echeq_management_payload(endorsement, 661395)['beneficiario']['documento'] == '30546125501'

    deposit = EcheqManagementRequest(
        idOrigen='depositar-001', cbuCuenta='1910000000000000000000',
        accion='DEPOSITAR',
        echeqs=[{
            'idCheque': 'REAL-ID-2', 'monto': '1.00',
            'fechaPago': '2026-08-29',
        }],
    )
    payload = echeq_management_payload(deposit, 661395)
    assert payload['echeqs'][0]['fechaPago'] == '20260829'
    assert payload['echeqs'][0]['monto'] == '1.00'

    with pytest.raises(ValidationError):
        EcheqManagementRequest(
            idOrigen='deposito-sin-fecha', cbuCuenta='1910000000000000000000',
            accion='DEPOSITAR', echeqs=[{'idCheque': 'REAL-ID-3', 'monto': '1.00'}],
        )
    with pytest.raises(ValidationError):
        EcheqManagementRequest(
            idOrigen='endoso-sin-beneficiario', cbuCuenta='1910000000000000000000',
            accion='ENDOSAR', echeqs=[{'idCheque': 'REAL-ID-4'}],
        )
    with pytest.raises(ValidationError):
        EcheqManagementRequest(
            idOrigen='sin-identificador', cbuCuenta='1910000000000000000000',
            accion='ACEPTAR', echeqs=[{}],
        )


def test_echeq_list_route_uses_documented_post_and_returns_empty_list(settings):
    seen = []

    def handler(request):
        token = token_response(request)
        if token:
            return token
        seen.append(request)
        assert request.url.path == '/api/echeq/v1/lista-cheques'
        payload = json.loads(request.content)
        assert payload['numeroAdherente'] == 661395
        assert payload['filtro'] == {
            'gestion': 'GENERADOS', 'estado': 'TODOS', 'pagina': 1, 'limite': 20,
        }
        return httpx.Response(200, json={'data': {'echeqs': [], 'totalCheques': 0}})

    client = CredicoopClient(settings, httpx.MockTransport(handler), interval=0)
    with TestClient(create_app(settings, client)) as api:
        response = api.post('/echeqs/lista', headers={'X-API-Key': 'k' * 40}, json={
            'idOrigen': 'lista-001',
            'filtro': {'gestion': 'GENERADOS'},
        })
    assert response.status_code == 200
    assert response.json()['data']['echeqs'] == []
    assert len(seen) == 1


def test_management_response_without_id_operacion_is_accepted_and_not_repeated(settings):
    calls = []

    def handler(request):
        token = token_response(request)
        if token:
            return token
        calls.append(request)
        assert request.url.path == '/api/echeq/v1/ConFirma/gestion'
        return httpx.Response(200, json={
            'data': {
                'idOrigen': 'aceptar-001',
                'estadoOperacion': {'descripcion': 'Aceptada'},
            },
        })

    client = CredicoopClient(settings, httpx.MockTransport(handler), interval=0)
    with TestClient(create_app(settings, client)) as api:
        headers = {'X-API-Key': 'k' * 40}
        payload = {
            'idOrigen': 'aceptar-001',
            'cbuCuenta': '1910000000000000000000',
            'accion': 'ACEPTAR',
            'echeqs': [{'idCheque': 'ID-DEVUELTO-POR-LA-API'}],
        }
        preview = api.post('/echeqs/gestion/previsualizar', headers=headers, json=payload)
        sent = api.post('/echeqs/gestion', headers=headers, json=payload)
        duplicate = api.post('/echeqs/gestion', headers=headers, json=payload)
    assert preview.status_code == 200 and preview.json()['enviada'] is False
    assert sent.status_code == 200
    assert sent.json()['respuesta_banco']['data']['estadoOperacion']['descripcion'] == 'Aceptada'
    assert 'idOperacion' not in sent.json()['respuesta_banco']['data']
    assert duplicate.status_code == 409
    assert len(calls) == 1


def test_bank_beneficiary_registration_can_respond_without_operation_id(settings):
    calls = []

    def handler(request):
        token = token_response(request)
        if token:
            return token
        calls.append(request)
        assert request.url.path == '/api/echeq/v1/beneficiario'
        payload = json.loads(request.content)
        assert payload['numeroAdherente'] == 661395
        return httpx.Response(200, json={'data': {'idOrigen': payload['idOrigen']}})

    client = CredicoopClient(settings, httpx.MockTransport(handler), interval=0)
    with TestClient(create_app(settings, client)) as api:
        headers = {'X-API-Key': 'k' * 40}
        response = api.post('/beneficiarios/echeqs', headers=headers, json={
            'idOrigen': 'alta-ben-001',
            'beneficiarios': [{
                'orden': 0,
                'documento': '30546125501',
                'documentoTipo': 'CUIT',
            }],
        })
        exchange_response = api.get(
            f"/intercambios-banco/{response.headers['X-Bank-Exchange-ID']}",
            headers=headers,
        )
    assert response.status_code == 200
    assert response.json()['respuesta_banco']['data']['idOrigen'] == 'alta-ben-001'
    assert len(calls) == 1
    exchange = exchange_response.json()['intercambios'][-1]
    assert exchange['request']['method'] == 'POST'
    assert exchange['request']['headers']['authorization'] == '[REDACTADO]'
    assert exchange['request']['body']['numeroAdherente'] == 661395
    assert exchange['request']['body']['beneficiarios'][0]['documento'] == '30546125501'
    assert exchange['response']['body'] == {'data': {'idOrigen': 'alta-ben-001'}}


def test_echeq_beneficiary_query_requires_document_and_forwards_valid_cuit(settings):
    calls = []

    def handler(request):
        token = token_response(request)
        if token:
            return token
        calls.append(request)
        assert request.url.path == '/api/echeq/v1/beneficiario/661395'
        assert request.url.params['documento'] == '30546125501'
        assert request.url.params['documentoTipo'] == 'CUIT'
        return httpx.Response(200, json={'data': {'documento': '30546125501'}})

    client = CredicoopClient(settings, httpx.MockTransport(handler), interval=0)
    with TestClient(create_app(settings, client)) as api:
        headers = {'X-API-Key': 'k' * 40}
        empty = api.get('/beneficiarios/echeqs?documento=&documento_tipo=CUIT', headers=headers)
        valid = api.get('/beneficiarios/echeqs?documento=30546125501&documento_tipo=CUIT', headers=headers)
        exchange_id = valid.headers['X-Bank-Exchange-ID']
        exchange_response = api.get(
            f'/intercambios-banco/{exchange_id}',
            headers=headers,
        )

    assert empty.status_code == 422
    assert valid.status_code == 200
    assert valid.json()['data']['documento'] == '30546125501'
    assert len(calls) == 1
    assert exchange_response.status_code == 200
    exchanges = exchange_response.json()['intercambios']
    assert len(exchanges) == 2
    assert exchanges[0]['request']['method'] == 'POST'
    assert exchanges[0]['response']['body']['access_token'] == '[REDACTADO]'
    exchange = exchanges[1]
    assert exchange['request']['method'] == 'GET'
    assert exchange['request']['url'] == str(calls[0].url)
    assert exchange['request']['headers']['authorization'] == '[REDACTADO]'
    assert exchange['request']['body'] is None
    assert exchange['response']['status'] == 200
    assert exchange['response']['body'] == {'data': {'documento': '30546125501'}}


def test_transfer_beneficiary_registration_uses_test_data_fields(settings):
    calls = []

    def handler(request):
        token = token_response(request)
        if token:
            return token
        calls.append(request)
        assert request.url.path == '/api/transferencias/v1/beneficiario'
        payload = json.loads(request.content)
        beneficiary = payload['beneficiarios'][0]
        assert beneficiary['nombre'] == 'PIAZZA, ANA KARINA'
        assert beneficiary['visibleBI'] is True
        return httpx.Response(200, json={'data': {'idOrigen': payload['idOrigen']}})

    client = CredicoopClient(settings, httpx.MockTransport(handler), interval=0)
    with TestClient(create_app(settings, client)) as api:
        response = api.post('/beneficiarios/transferencias', headers={'X-API-Key': 'k' * 40}, json={
            'idOrigen': 'alta-tr-001',
            'beneficiarios': [{
                'orden': 0,
                'cbuCvu': '0200902911000060065458',
                'moneda': 'ARS',
                'cui': '27237632813',
                'nombre': 'PIAZZA, ANA KARINA',
                'visibleBI': True,
            }],
        })
    assert response.status_code == 200
    assert response.json()['respuesta_banco']['data']['idOrigen'] == 'alta-tr-001'
    assert len(calls) == 1


def test_evidence_captures_full_exchange_and_redacts_credentials(tmp_path):
    recorder = EvidenceRecorder(tmp_path / 'evidencias')
    request = httpx.Request(
        'POST',
        'https://homoapibccl.bancocredicoop.coop/auth/token',
        headers={'Authorization': 'Bearer should-not-leak', 'Content-Type': 'application/json'},
        json={'client_assertion': 'assertion-secret', 'scope': 'cuentas'},
    )
    response = httpx.Response(
        200, headers={'Content-Type': 'application/json'},
        json={'access_token': 'access-secret', 'expires_in': 100},
        request=request,
    )
    recorder.record('Autenticación OAuth', 'cuentas', request, response)
    folder = recorder.directory
    assert folder is not None
    transcript = '\n'.join(path.read_text(encoding='utf-8') for path in folder.iterdir() if path.is_file())
    assert 'should-not-leak' not in transcript
    assert 'assertion-secret' not in transcript
    assert 'access-secret' not in transcript
    assert '[REDACTADO]' in transcript
    assert (folder / 'intercambios.jsonl').is_file()
    assert (folder / 'RESUMEN.csv').is_file()
    assert (folder / 'RESUMEN.md').is_file()
