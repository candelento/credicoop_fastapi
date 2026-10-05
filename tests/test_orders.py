import hashlib
import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.config import Settings
from app.journal import Journal
from app.main import create_app
from app.orders import (
    DriveOrderService,
    Supplier,
    build_order_instruction,
    load_supplier_master,
    normalize_text,
    order_origin,
    parse_order,
)


SUPPLIER = Supplier('PROVEEDOR UNO SA', '30677886370', '0290023010000000555675')
SUPPLIERS = {normalize_text(SUPPLIER.name): [SUPPLIER]}
DEBIT_CBU = '1910000000000000000000'


def parsed(text, monkeypatch, *, filename='op-ejemplo.pdf', file_id='drive-id-uno', today=date(2026, 8, 28)):
    page = SimpleNamespace(extract_text=lambda: text)
    reader = SimpleNamespace(is_encrypted=False, pages=[page])
    monkeypatch.setattr('app.orders.PdfReader', lambda _: reader)
    return parse_order(filename, file_id, b'%PDF-1.7 synthetic', SUPPLIERS, today)


def test_parse_transfer_amount_from_same_trb_line_and_build_instruction(monkeypatch):
    order = parsed('PROVEEDOR UNO SA\nPago TRB referencia 1.234,56', monkeypatch)
    assert order['status'] == 'READY'
    assert order['method'] == 'TRB'
    assert order['amount'] == '1234.56'
    assert order['supplier']['document'] == '30677886370'
    assert order['id_origen'] == order_origin('drive-id-uno')
    payload = build_order_instruction(order, DEBIT_CBU, date(2026, 8, 28))
    assert payload['beneficiarios'][0]['monto'] == '1234.56'
    assert payload['beneficiarios'][0]['cbuCvu'] == SUPPLIER.cbu


def test_parse_cheque_requires_date_and_always_builds_a_la_orden(monkeypatch):
    order = parsed('PROVEEDOR UNO SA\n28/08/2026 CHE 5.000,00', monkeypatch, file_id='drive-id-che')
    assert order['status'] == 'READY'
    assert order['cheque_type'] == 'ECHC'
    payload = build_order_instruction(order, DEBIT_CBU, date(2026, 8, 28))
    assert payload['echeqs'][0]['tipoCheque'] == 'ECHC'
    assert payload['echeqs'][0]['caracter'] == '1'
    assert payload['echeqs'][0]['fechaPago'] == '2026-08-28'

    deferred = parsed('PROVEEDOR UNO SA\n04/09/2026 CHE 5.000,00', monkeypatch, file_id='drive-che-diferido')
    assert deferred['status'] == 'READY'
    assert deferred['cheque_type'] == 'ECHD'

    missing_date = parsed('PROVEEDOR UNO SA\nCHE 5.000,00', monkeypatch, file_id='drive-che-sin-fecha')
    assert missing_date['status'] == 'NEEDS_REVIEW'
    assert 'fecha de pago' in missing_date['reason']


def test_ambiguous_supplier_or_amount_stays_for_review(monkeypatch):
    ambiguous_suppliers = {
        normalize_text(SUPPLIER.name): [SUPPLIER],
        'PROVEEDOR DOS SA': [Supplier('PROVEEDOR DOS SA', '30546125501', '1910000000000000000000')],
    }
    page = SimpleNamespace(extract_text=lambda: 'PROVEEDOR UNO SA\nPROVEEDOR DOS SA\nTRB 10,00')
    monkeypatch.setattr('app.orders.PdfReader', lambda _: SimpleNamespace(is_encrypted=False, pages=[page]))
    supplier_result = parse_order('op-uno.pdf', 'id-1', b'%PDF-x', ambiguous_suppliers, date(2026, 8, 28))
    assert supplier_result['status'] == 'NEEDS_REVIEW'
    assert 'más de un beneficiario' in supplier_result['reason']

    amount_result = parsed('PROVEEDOR UNO SA\nTRB 10,00 20,00', monkeypatch, file_id='id-2')
    assert amount_result['status'] == 'NEEDS_REVIEW'
    assert 'único importe' in amount_result['reason']


def test_supplier_master_reads_required_columns(tmp_path):
    path = tmp_path / 'beneficiarios.xlsx'
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Beneficiarios Transferencias'
    sheet.append(['CBU', 'NOMBRE', 'CUIT-CUIL-CDI', 'TIPO CTA'])
    sheet.append([SUPPLIER.cbu, SUPPLIER.name, SUPPLIER.document, 'CC'])
    workbook.save(path)

    assert load_supplier_master(path) == {normalize_text(SUPPLIER.name): [SUPPLIER]}


def test_drive_listing_strictly_filters_name_and_mime_type():
    requested = []

    def handler(request):
        requested.append(request)
        return httpx.Response(200, json={'files': [
            {'id': 'pdf-op', 'name': 'op-001.pdf', 'mimeType': 'application/pdf'},
            {'id': 'not-prefix', 'name': 'orden-001.pdf', 'mimeType': 'application/pdf'},
            {'id': 'not-pdf', 'name': 'op-002.pdf', 'mimeType': 'text/plain'},
            {'id': 'not-extension', 'name': 'op-003.doc', 'mimeType': 'application/pdf'},
        ]})

    settings = Settings(_env_file=None, api_key='a' * 40)
    service = DriveOrderService(settings, Path.cwd())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await service._list_files(client, 'test-token')

    assert [item['id'] for item in asyncio.run(run())] == ['pdf-op']
    assert "'1xa_14O0TERbR_kPaQhledLGEl0p77m24' in parents" in requested[0].url.params['q']


def test_journal_deduplicates_content_and_blocks_modified_source(tmp_path):
    journal = Journal(tmp_path / 'orders.sqlite3')
    base = {
        'source_id': 'drive-1',
        'source_name': 'op-1.pdf',
        'sha256': hashlib.sha256(b'first').hexdigest(),
        'id_origen': order_origin('drive-1'),
        'status': 'READY',
    }
    journal.store_order(base)
    duplicate = dict(base, source_id='drive-2', source_name='op-2.pdf')
    duplicate_result = journal.store_order(duplicate)
    assert duplicate_result['status'] == 'DUPLICATE'
    assert duplicate_result['duplicate_of'] == 'drive-1'

    changed = dict(base, sha256=hashlib.sha256(b'changed').hexdigest())
    updated = journal.store_order(changed)
    assert updated['status'] == 'NEEDS_REVIEW'
    assert updated['content_changed_after_import']

    unresolved = dict(base, source_id='drive-needs-review', status='NEEDS_REVIEW',
                      sha256=hashlib.sha256(b'needs review').hexdigest())
    journal.store_order(unresolved)
    resolved = dict(unresolved, status='READY')
    assert journal.store_order(resolved)['status'] == 'READY'


class RecordingBank:
    def __init__(self):
        self.calls = []

    async def request(self, method, path, *, body=None):
        self.calls.append((method, path, body))
        return {'data': {'idOperacion': 123, 'estadoOperacion': {'descripcion': 'Pendiente de firma'}}}

    async def close(self):
        return None


def test_order_preview_is_read_only_and_send_is_explicit_and_once(tmp_path):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_path = tmp_path / 'private.pem'
    key_path.write_bytes(private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ))
    cfg = Settings(_env_file=None, api_key='a' * 40, private_key_path=key_path,
                   journal_path=tmp_path / 'operations.sqlite3')
    bank = RecordingBank()
    with TestClient(create_app(cfg, bank)) as api:
        api.app.state.journal.store_order({
            'source_id': 'drive-preview',
            'source_name': 'op-preview.pdf',
            'id_origen': order_origin('drive-preview'),
            'sha256': hashlib.sha256(b'preview').hexdigest(),
            'status': 'READY',
            'reason': None,
            'method': 'TRB',
            'supplier': {'name': SUPPLIER.name, 'document': SUPPLIER.document, 'cbu': SUPPLIER.cbu},
            'amount': '1234.56',
            'cheque_date': None,
            'cheque_type': None,
        })
        headers = {'X-API-Key': 'a' * 40}
        preview = api.post('/ordenes-pago/drive-preview/previsualizar',
                           headers=headers, json={'cbuCuentaDebito': DEBIT_CBU})
        assert preview.status_code == 200
        assert preview.json()['enviada'] is False
        assert bank.calls == []

        sent = api.post('/ordenes-pago/drive-preview/enviar',
                        headers=headers, json={'cbuCuentaDebito': DEBIT_CBU})
        assert sent.status_code == 200
        assert len(bank.calls) == 1
        repeated = api.post('/ordenes-pago/drive-preview/enviar',
                            headers=headers, json={'cbuCuentaDebito': DEBIT_CBU})
        assert repeated.status_code == 409
        assert len(bank.calls) == 1
