#!/usr/bin/env python
"""
Append helper functions to orders.py after parse_order.
"""
path = 'app/orders.py'
with open(path, 'rb') as f:
    content = f.read()

# Find the position of 'def build_order_instruction'
idx = content.find(b'def build_order_instruction')

# Read helpers from file and encode as latin-1 to preserve non-ASCII
with open('helpers.txt', 'r', encoding='utf-8') as f:
    helpers_text = f.read()
helpers_bytes = helpers_text.encode('latin-1')

# Build new content with \r\n line endings
new_content = content[:idx] + helpers_bytes + content[idx:]

with open(path, 'wb') as f:
    f.write(new_content)

print('Appended helper functions successfully')
