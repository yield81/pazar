import re
with open('web/template.html', 'r', encoding='utf-8') as f:
    t = f.read()
# Fix the esc function - remove the single quote handling
old = "const esc = s => String(s == null ? '' : s).replace(/[&<>\"]/g, c => ({'&':'&','<':'<','>':'>','\"':\"\"\"',\"'\":\"'''}[c]));"
new = 'const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&","<":"<",">":">","\"":\""\"}[c]));'
t = t.replace(old, new)
with open('web/template.html', 'w', encoding='utf-8') as f:
    f.write(t)
print('fixed')