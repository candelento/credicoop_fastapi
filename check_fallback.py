path = 'app/orders.py'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line with 'order_number': None
for i, line in enumerate(lines):
    if 'order_number' in line:
        start = max(0, i - 5)
        end = min(len(lines), i + 5)
        print(f'--- Lines {start+1}-{end} ---')
        for j in range(start, end):
            print(f'{j+1}: {lines[j]!r}')
        break
