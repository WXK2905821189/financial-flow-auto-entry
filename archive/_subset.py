import json

with open(r'c:\Users\王小棵\Documents\财务流水自动化\_manifest.json', 'r', encoding='utf-8') as f:
    manifest = json.load(f)

# Only files NOT yet pushed: web, root docs, 产品经理, 数据工程, 财务业务顾问
already_there = {
    '.gitignore', 'README.md', 'backend/.env.example', 'backend/requirements.txt',
    'backend/smoke_test.py',
}
missing = [it for it in manifest if it['path'] not in already_there and not it['path'].startswith('backend/app')]

# split: small text first (web + md/csv/txt), then big html/sql last
def kind(p):
    if p.startswith('backend/web'):
        return 0
    if p.endswith(('.html')):
        return 2
    if p.endswith(('.sql')):
        return 2
    return 1

missing.sort(key=lambda it: (kind(it['path']), it['path']))

with open(r'c:\Users\王小棵\Documents\财务流水自动化\_subset.json', 'w', encoding='utf-8') as f:
    json.dump(missing, f, ensure_ascii=False)
print("SUBSET", len(missing))
for it in missing:
    print(kind(it['path']), len(it['content']), it['path'])