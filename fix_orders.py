#!/usr/bin/env python
import sys

path = 'app/orders.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Remove ORDER_NUMBER_PATTERN and ISSUE_DATE_PATTERN lines
import re as _re
lines = content.split('\n')
new_lines = []
skip_next = False
for line in lines:
    if 'ORDER_NUMBER_PATTERN' in line or 'ISSUE_DATE_PATTERN' in line:
        continue
    new_lines.append(line)
content = '\n'.join(new_lines)

# Update sync error fallback to remove order_number and issue_date fields
old_fallback = """                        order = {
                            'source_id': file_id,
                            'source_name': metadata['name'],
                            'id_origen': order_origin(file_id),
                            'sha256': hashlib.sha256(content).hexdigest(),
                            'status': 'NEEDS_REVIEW',
                            'reason': str(exc),
                            'method': None,
                            'supplier': None,
                            'amount': None,
                            'cheque_date': None,
                            'cheque_type': None,
                            'order_number': None,
                            'issue_date': None,
                            'concept': None,
                            'references': [],
                        }"""
new_fallback = """                        order = {
                            'source_id': file_id,
                            'source_name': metadata['name'],
                            'id_origen': order_origin(file_id),
                            'sha256': hashlib.sha256(content).hexdigest(),
                            'status': 'NEEDS_REVIEW',
                            'reason': str(exc),
                            'method': None,
                            'supplier': None,
                            'amount': None,
                            'cheque_date': None,
                            'cheque_type': None,
                            'concept': None,
                            'references': [],
                        }"""

if old_fallback in content:
    content = content.replace(old_fallback, new_fallback)
    print('Fixed sync fallback')
else:
    print('Fallback block not found exactly as expected')
    # Use regex to find and remove the two fields
    content = content.replace("'order_number': None,\n                            ", "")
    content = content.replace("'issue_date': None,\n                            ", "")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')
