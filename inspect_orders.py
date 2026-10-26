#!/usr/bin/env python
import sys

path = 'app/orders.py'
with open(path, 'rb') as f:
    c = f.read()

i = c.find(b'ORDER_NUMBER_PATTERN')
if i == -1:
    print('ORDER_NUMBER_PATTERN not found')
    sys.exit(0)

# print context around it
start = max(0, i - 100)
end = min(len(c), i + 500)
print(repr(c[start:end]))
print()

# Also check DATE_PATTERN context
j = c.find(b'DATE_PATTERN')
if j != -1:
    start = max(0, j - 100)
    end = min(len(c), j + 300)
    print(repr(c[start:end]))