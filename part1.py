#!/usr/bin/env python
"""Part 1: Find the parse_order function and prepare the replacement."""
path = 'app/orders.py'
with open(path, 'rb') as f:
    content = f.read()

# Split into lines, handling both \n and \r\n
raw_lines = content.split(b'\n')
# Handle \r
lines = [line.decode('utf-8').rstrip('\r') for line in raw_lines]

# Find start and end of parse_order function
start_idx = None
end_idx = None
for i, line in enumerate(lines):
    if line.strip().startswith('def parse_order('):
        start_idx = i
    if start_idx is not None and i > start_idx and line.strip() == 'return order':
        # Check if next line is empty or a new def
        if i + 1 >= len(lines) or lines[i+1].strip() == '' or lines[i+1].strip().startswith('def '):
            end_idx = i
            break

print(f'start_idx: {start_idx}, end_idx: {end_idx}')
if start_idx is not None and end_idx is not None:
    print(f'Lines before parse_order: {start_idx}')
    print(f'Lines in parse_order: {end_idx - start_idx + 1}')
else:
    print('Could not find function')
