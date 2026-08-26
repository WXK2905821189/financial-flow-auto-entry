# -*- coding: utf-8 -*-
import os, json
ROOT = r'c:\Users\王小棵\Documents\财务流水自动化\财务流水自动入账项目'
listf = r'c:\Users\王小棵\Documents\财务流水自动化\_list.txt'
arr = []
for ln in open(listf, encoding='utf-8'):
    p = ln.rstrip('\n').strip()
    if not p:
        continue
    full = os.path.join(ROOT, p)
    with open(full, encoding='utf-8') as f:
        content = f.read()
    arr.append({'path': p.replace('\\', '/'), 'content': content})
print(json.dumps(arr, ensure_ascii=False))