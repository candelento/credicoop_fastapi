"""CLI contra el servicio FastAPI local. Ejemplo: python credicoop.py cuentas."""
import argparse
import json
import sys
from pathlib import Path
import httpx
from app.config import Settings


def main():
    parser = argparse.ArgumentParser(description='Credicoop API Empresas — consultas y envíos a firma')
    parser.add_argument('--servidor', default='http://127.0.0.1:8000')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('cuentas')
    balance = sub.add_parser('saldo'); balance.add_argument('cuenta')
    moves = sub.add_parser('movimientos'); moves.add_argument('cuenta'); moves.add_argument('--desde', required=True); moves.add_argument('--hasta'); moves.add_argument('--salida', type=Path)
    for kind in ('transferencia', 'echeq'):
        p = sub.add_parser(kind); p.add_argument('archivo', type=Path)
        p.add_argument('--enviar', action='store_true', help='Enviar al banco a firma. Sin esta opción sólo previsualiza.')
    status = sub.add_parser('estado'); status.add_argument('tipo', choices=['transferencia', 'echeq']); status.add_argument('--id-operacion'); status.add_argument('--id-origen')
    args = parser.parse_args()
    cfg = Settings()
    params, body, method = {}, None, 'GET'
    if args.command == 'cuentas': path = '/cuentas'
    elif args.command == 'saldo': path = f'/cuentas/{args.cuenta}/saldo'
    elif args.command == 'movimientos':
        path = f'/cuentas/{args.cuenta}/movimientos'; params['fecha_desde'] = args.desde
        if args.hasta: params['fecha_hasta'] = args.hasta
    elif args.command in ('transferencia', 'echeq'):
        path = '/transferencias' if args.command == 'transferencia' else '/echeqs'
        if not args.enviar: path += '/previsualizar'
        method = 'POST'
        body = json.loads(args.archivo.read_text(encoding='utf-8-sig'))
    else:
        path = '/transferencias/estado' if args.tipo == 'transferencia' else '/echeqs/estado'
        if args.id_operacion: params['id_operacion'] = args.id_operacion
        if args.id_origen: params['id_origen'] = args.id_origen
    try:
        response = httpx.request(method, args.servidor.rstrip('/') + path, params=params, json=body,
                                headers={'X-API-Key': cfg.api_key.get_secret_value()}, timeout=600)
    except httpx.HTTPError:
        print('No se obtuvo respuesta local. Si era un envío, consultar estado antes de repetir.', file=sys.stderr)
        return 1
    output = json.dumps(response.json(), ensure_ascii=False, indent=2)
    if getattr(args, 'salida', None): args.salida.write_text(output, encoding='utf-8')
    print(output)
    return 0 if response.is_success else 1


if __name__ == '__main__':
    raise SystemExit(main())
