#!/usr/bin/env python
"""
Append more helper functions to orders.py after parse_order.
"""
path = 'app/orders.py'
with open(path, 'rb') as f:
    content = f.read()

# Find the position of '_find_supplier'
idx = content.find(b'def _find_supplier')

# Read helpers from file and encode as latin-1
with open('helpers2.txt', 'r', encoding='utf-8') as f:
    helpers_text = f.read()
helpers_bytes = helpers_text.encode('latin-1')

# Build new content
new_content = content[:idx] + helpers_bytes + content[idx:]

with open(path, 'wb') as f:
    f.write(new_content)

print('Appended more helper functions successfully')
