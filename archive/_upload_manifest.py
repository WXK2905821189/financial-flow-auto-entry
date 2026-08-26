# -*- coding: utf-8 -*-
import os, json, sys

root = r'c:\Users\王小棵\Documents\财务流水自动化\财务流水自动入账项目'
excl_dirs = {'__pycache__', '.git', '.venv', 'venv', 'node_modules', '.pytest_cache'}
excl_ext = {'.pyc', '.pyo', '.log', '.db', '.sqlite', '.sqlite3', '.tmp', '.bak'}
excl_files = {'.env', '.env.local'}

out = []
for dirpath, dirs, files in os.walk(root):
    dirs[:] = [d for d in dirs if d not in excl_dirs]
    for f in sorted(files):
        if f in excl_files or (f.startswith('.env.') and f.endswith('.local')):
            continue
        ext = os.path.splitext(f)[1].lower()
        if ext in excl_ext:
            continue
        full = os.path.join(dirpath, f)
        rel = os.path.relpath(full, root).replace(os.sep, '/')
        data = open(full, encoding='utf-8').read()
        out.append({'path': rel, 'chars': len(data), 'bytes': os.path.getsize(full)})

print(json.dumps({'count': len(out), 'total_chars': sum(x['chars'] for x in out), 'files': out}, ensure_ascii=False, indent=1))