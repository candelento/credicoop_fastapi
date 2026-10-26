#!/usr/bin/env python
path = 'app/orders.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the two pattern lines
lines = content.split('\n')
new_lines = []
for line in lines:
    if 'ORDER_NUMBER_PATTERN' in line or 'ISSUE_DATE_PATTERN' in line:
        continue
    new_lines.append(line)

content = '\n'.join(new_lines)

# Fix the sync fallback (remove order_number and issue_date from error dict)
old = """        'order_number': None,
        'issue_date': None,
"""
if old in content:
    content = content.replace(old, "")
    print('Fixed sync fallback')
else:
    print('Fallback block not found')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

# Verify
with open(path, 'r', encoding='utf-8') as f:
    check = f.read()
print('ORDER_NUMBER_PATTERN present:', 'ORDER_NUMBER_PATTERN' in check)
print('ISSUE_DATE_PATTERN present:', 'ISSUE_DATE_PATTERN' in check)
print("'order_number': None present:", "'order_number': None" in check)
print("'issue_date': None present:", "'issue_date': None" in check)
