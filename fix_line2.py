with open('web/template.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()
# Simple escape function that only handles & < >
lines[222] = 'const esc = s => String(s == null ? "" : s).replace(/[&<>]/g, c => ({"&":"&","<":"<",">":">"}[c]));\n'
with open('web/template.html', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('fixed by line')