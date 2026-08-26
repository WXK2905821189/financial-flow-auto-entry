import json, os

ROOT = r'c:\Users\王小棵\Documents\财务流水自动化\财务流水自动入账项目'
excl_dirs = {'__pycache__', '.git', '.venv', 'venv', 'node_modules', '.pytest_cache'}
excl_ext = {'.pyc', '.pyo', '.log', '.db', '.sqlite', '.sqlite3', '.tmp'}
excl_files = {'.env', '.env.local'}

out = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in excl_dirs]
    for fn in sorted(filenames):
        full = os.path.join(dirpath, fn)
        rel = os.path.relpath(full, ROOT).replace('\\', '/')
        ext = os.path.splitext(fn)[1].lower()
        if fn in excl_files or ext in excl_ext:
            continue
        with open(full, 'r', encoding='utf-8') as f:
            content = f.read()
        out.append({"path": rel, "content": content})

with open(r'c:\Users\王小棵\Documents\财务流水自动化\_manifest.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False)

print("TOTAL", len(out))
for item in out:
    print(item["path"])