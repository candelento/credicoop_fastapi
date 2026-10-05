"""Crea .env local con clave aleatoria, sin sobrescribir configuración existente."""
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / '.env'
if target.exists():
    print('.env ya existe; no se modificó.')
else:
    content = (root / '.env.example').read_text(encoding='utf-8').replace('GENERAR_CON_CONFIGURAR', secrets.token_urlsafe(32))
    target.write_text(content, encoding='utf-8')
    print('Configuración creada. Copiá la llave PEM a secrets y revisá .env antes de iniciar.')
(root / 'secrets').mkdir(exist_ok=True)
