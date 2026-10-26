#!/usr/bin/env python
"""Replace the old parse_order function with the new one."""
import re

path = 'app/orders.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# The new parse_order function
new_parse_order = '''def parse_order(filename: str, file_id: str, content: bytes,
                suppliers: dict[str, list[Supplier]], operational_today: date) -> dict:
    """
    Parsea un PDF de orden de pago y devuelve el diccionario listo para persistir.

    - TRB (transferencia): una sola orden con los datos de la transferencia.
    - CHE (eCheq): puede contener varias instrucciones de pago; se devuelven
      múltiples órdenes, una por cada echeq, usando `Fecha Pago` de cada echeq.
    """
    lines = content.decode('utf-8', errors='ignore').splitlines()
    parsed = _parse_lines(lines)
    method = _detect_method(lines)

    if method == 'TRB' or method is None:
        return _trb_order(parsed, suppliers, operational_today)

    # method == 'CHE'
    return _che_order(parsed, suppliers, operational_today)
'''

# Find the old parse_order function and replace it
lines = content.split('\\n')
start_idx = None
end_idx = None
for i, line in enumerate(lines):
    if 'def parse_order' in line:
        start_idx = i
    if start_idx is not None and i > start_idx and 'return order' in line.strip():
        if i + 1 >= len(lines) or lines[i+1].strip() == '' or lines[i+1].strip().startswith('def '):
            end_idx = i
            break

if start_idx is not None and end_idx is not None:
    new_content = '\\n'.join(lines[:start_idx]) + '\\n' + new_parse_order + '\\n' + '\\n'.join(lines[end_idx+1:])
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Replaced parse_order function successfully')
    print(f'Found at lines {start_idx+1}-{end_idx+1}')
else:
    print('Could not find parse_order function boundaries')
    print('start_idx:', start_idx, 'end_idx:', end_idx)
