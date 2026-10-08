import csv
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SENSITIVE_KEYS = (
    'authorization', 'x-api-key', 'token', 'assertion', 'password', 'private_key',
    'client_secret', 'cookie', 'secret',
)
IDENTIFIER_KEYS = ('idOrigen', 'idOperacion', 'idCheque', 'chequeId', 'cmc7', 'cmc7completo')


def _redact_value(value):
    if isinstance(value, dict):
        return {
            key: '[REDACTADO]' if any(part in key.lower() for part in SENSITIVE_KEYS)
            else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _redact_text(body: str, content_type: str) -> str:
    if 'application/json' in content_type.lower():
        try:
            return json.dumps(_redact_value(json.loads(body)), ensure_ascii=False, indent=2)
        except (ValueError, TypeError):
            pass
    if 'application/x-www-form-urlencoded' in content_type.lower():
        fields = parse_qsl(body, keep_blank_values=True)
        return urlencode([
            (key, '[REDACTADO]' if any(part in key.lower() for part in SENSITIVE_KEYS) else value)
            for key, value in fields
        ])
    return re.sub(
        r'(?i)((?:"?(?:access_token|refresh_token|client_assertion|client_secret|x-api-key|password|private_key)"?)\s*[:=]\s*)'
        r'(?:"[^"]*"|[^&,\s}]+)',
        r'\1"[REDACTADO]"',
        body,
    )


def _headers(headers) -> dict:
    return {
        key: '[REDACTADO]' if any(part in key.lower() for part in SENSITIVE_KEYS)
        else value
        for key, value in headers.items()
    }


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode([
        (key, '[REDACTADO]' if any(part in key.lower() for part in SENSITIVE_KEYS) else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def exchange_snapshot(request, response=None, error=None) -> dict:
    request_content_type = request.headers.get('content-type', '')
    raw_request_body = request.content.decode('utf-8', errors='replace') if request.content else ''
    request_body = _redact_text(raw_request_body, request_content_type) if raw_request_body else None
    if request_body and 'application/json' in request_content_type.lower():
        try:
            request_body = json.loads(request_body)
        except ValueError:
            pass

    response_body = None
    response_headers = {}
    if response is not None:
        response_headers = _headers(response.headers)
        raw_response_body = response.content.decode('utf-8', errors='replace')
        content_type = response.headers.get('content-type', '')
        response_body = _redact_text(raw_response_body, content_type) if raw_response_body else ''
        if response_body and 'application/json' in content_type.lower():
            try:
                response_body = json.loads(response_body)
            except ValueError:
                pass

    return {
        'request': {
            'method': request.method,
            'url': _safe_url(str(request.url)),
            'headers': _headers(request.headers),
            'body': request_body,
        },
        'response': {
            'status': response.status_code if response is not None else None,
            'headers': response_headers,
            'body': response_body,
            'error': _redact_text(error, '') if error else None,
        },
    }


def _identifiers(*values) -> dict:
    found = {key: [] for key in IDENTIFIER_KEYS}

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in found and item is not None and not isinstance(item, (dict, list)):
                    text = str(item)
                    if text not in found[key]:
                        found[key].append(text)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for value in values:
        visit(value)
    return {key: items[0] if len(items) == 1 else items for key, items in found.items() if items}


def _bank_error(body) -> bool:
    return isinstance(body, dict) and bool(
        body.get('error') or body.get('errores')
        or ('codigo' in body and str(body['codigo']) not in ('0', '200', 'None', ''))
    )


class EvidenceRecorder:
    def __init__(self, root: Path):
        self.root = root
        self.directory: Path | None = None
        self._lock = threading.Lock()
        self._counter = 0
        self._summary: list[dict] = []

    def record(self, function: str, scope: str, request, response=None, *, error=None,
               ambiguous=False, local_response_body=None) -> dict:
        timestamp = datetime.now().astimezone().isoformat(timespec='microseconds')
        content_type = request.headers.get('content-type', '')
        raw_request_body = request.content.decode('utf-8', errors='replace') if request.content else ''
        request_body = _redact_text(raw_request_body, content_type) if raw_request_body else ''
        request_json = None
        try:
            request_json = _redact_value(json.loads(raw_request_body)) if raw_request_body else None
        except (ValueError, TypeError):
            pass

        response_status = response.status_code if response is not None else None
        response_headers = _headers(response.headers) if response is not None else {}
        raw_response_body = ''
        response_body = None
        if response is not None:
            raw_response_body = response.content.decode('utf-8', errors='replace')
            response_content_type = response.headers.get('content-type', '')
            safe_text = _redact_text(raw_response_body, response_content_type)
            try:
                response_body = json.loads(safe_text)
            except (ValueError, TypeError):
                response_body = safe_text

        if error:
            result = 'RESULTADO_INCIERTO' if ambiguous else 'SIN_RESPONSE'
        elif response_status is not None and (response_status >= 400 or _bank_error(response_body)):
            result = 'ERROR_BANCARIO'
        else:
            result = 'RESPUESTA_EXITOSA'

        with self._lock:
            if self.directory is None:
                folder_time = datetime.now().astimezone().strftime('%Y%m%d_%H%M%S_%f_%z')
                self.directory = self.root / folder_time
                self.directory.mkdir(parents=True, exist_ok=False)
            self._counter += 1
            index = self._counter
            slug = re.sub(r'[^A-Za-z0-9_-]+', '_', function).strip('_')[:50] or 'llamada'
            stem = f'{index:03d}_{slug}'
            request_file = f'{stem}.request.txt'
            response_file = f'{stem}.response.txt'
            json_file = f'{stem}.json'
            request_text = (
                f'Fecha y hora: {timestamp}\nFunción: {function}\nScope: {scope}\n'
                f'Método: {request.method}\nURL: {request.url}\nHeaders:\n'
                + '\n'.join(f'{key}: {value}' for key, value in _headers(request.headers).items())
                + '\n\nBody:\n' + (request_body or 'SIN BODY') + '\n'
            )
            if response is None:
                response_text = f'HTTP: SIN RESPONSE\nError: {error or "No se recibió respuesta"}\n'
            else:
                response_text = (
                    f'Fecha y hora: {timestamp}\nHTTP: {response_status}\nHeaders:\n'
                    + '\n'.join(f'{key}: {value}' for key, value in response_headers.items())
                    + '\n\nBody:\n' + (raw_response_body if raw_response_body else 'BODY VACÍO') + '\n'
                )
                response_text = _redact_text(response_text, response.headers.get('content-type', ''))
            identifiers = _identifiers(request_json, response_body)
            entry = {
                'fecha_hora': timestamp,
                'funcion': function,
                'scope': scope,
                'metodo': request.method,
                'url': str(request.url),
                'request_headers': _headers(request.headers),
                'request_body': request_body,
                'http_status': response_status,
                'response_headers': response_headers,
                'response_body': response_body if response is not None else None,
                'resultado': result,
                'error': error,
                'identificadores': identifiers,
                'archivos': {
                    'request': request_file,
                    'response': response_file,
                    'json': json_file,
                },
            }
            if local_response_body is not None:
                entry['response_body'] = _redact_value(local_response_body)
            (self.directory / request_file).write_text(request_text, encoding='utf-8')
            (self.directory / response_file).write_text(response_text, encoding='utf-8')
            (self.directory / json_file).write_text(
                json.dumps(entry, ensure_ascii=False, indent=2), encoding='utf-8'
            )
            with (self.directory / 'intercambios.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
            self._summary.append(entry)
            self._write_summaries()
        return entry

    def note(self, function: str, result: str, details: str, identifiers: dict | None = None):
        timestamp = datetime.now().astimezone().isoformat(timespec='microseconds')
        with self._lock:
            if self.directory is None:
                folder_time = datetime.now().astimezone().strftime('%Y%m%d_%H%M%S_%f_%z')
                self.directory = self.root / folder_time
                self.directory.mkdir(parents=True, exist_ok=False)
            self._counter += 1
            slug = re.sub(r'[^A-Za-z0-9_-]+', '_', function).strip('_')[:50] or 'nota'
            stem = f'{self._counter:03d}_{slug}'
            files = {
                'request': f'{stem}.request.txt',
                'response': f'{stem}.response.txt',
                'json': f'{stem}.json',
            }
            entry = {
                'fecha_hora': timestamp,
                'funcion': function,
                'scope': 'NO APLICA - SIN LLAMADA',
                'metodo': None,
                'url': None,
                'request_headers': {},
                'request_body': None,
                'http_status': None,
                'response_headers': {},
                'response_body': None,
                'resultado': result,
                'error': details,
                'identificadores': identifiers or {},
                'archivos': files,
            }
            (self.directory / files['request']).write_text(
                f'Fecha y hora: {timestamp}\nFunción: {function}\n'
                f'Estado: NO ENVIADO\nMotivo: {details}\n', encoding='utf-8',
            )
            (self.directory / files['response']).write_text(
                f'HTTP: SIN RESPONSE\nEstado: {result}\nMotivo: {details}\n', encoding='utf-8',
            )
            (self.directory / files['json']).write_text(
                json.dumps(entry, ensure_ascii=False, indent=2), encoding='utf-8',
            )
            with (self.directory / 'intercambios.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
            self._summary.append(entry)
            self._write_summaries()
        return entry

    def _write_summaries(self):
        assert self.directory is not None
        columns = (
            'funcion', 'resultado', 'http_status', 'idOrigen', 'idOperacion',
            'idCheque', 'cmc7', 'request', 'response', 'json',
        )
        with (self.directory / 'RESUMEN.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            for entry in self._summary:
                identifiers = entry['identificadores']
                writer.writerow({
                    'funcion': entry['funcion'],
                    'resultado': entry['resultado'],
                    'http_status': entry['http_status'] or '',
                    **{key: identifiers.get(key, '') for key in ('idOrigen', 'idOperacion', 'idCheque', 'cmc7')},
                    **entry['archivos'],
                })
        lines = [
            '# Evidencias de homologación',
            '',
            '| Función | Resultado | HTTP | idOrigen | idOperacion | idCheque | cmc7 | Archivos |',
            '|---|---|---:|---|---|---|---|---|',
        ]
        for entry in self._summary:
            identifiers = entry['identificadores']
            files = ', '.join(f'`{name}`' for name in entry['archivos'].values())
            lines.append(
                f"| {entry['funcion']} | {entry['resultado']} | {entry['http_status'] or '—'} | "
                f"{identifiers.get('idOrigen', '—')} | {identifiers.get('idOperacion', '—')} | "
                f"{identifiers.get('idCheque', '—')} | {identifiers.get('cmc7', '—')} | {files} |"
            )
        (self.directory / 'RESUMEN.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
