import json

with open(r'c:\Users\王小棵\Documents\财务流水自动化\_subset.json', 'r', encoding='utf-8') as f:
    items = json.load(f)

batchA = [it for it in items if it['path'].startswith('backend/web')]
rest = [it for it in items if not it['path'].startswith('backend/web')]

meta = ['产品经理', '财务业务顾问', '一期Agent提示词与分工（v1）.md', '一期UI设计归档.md',
        '一期分工表（Sheet）.csv', '财务流水自动入账项目 — 执行方案——第一期（v3）.md',
        '财务流水自动入账项目 — 立项与架构设计（v2）.md']
batchB = [it for it in rest if any(m in it['path'] for m in meta)]
rest = [it for it in rest if it not in batchB]

batchC = [it for it in rest if 'mock_bank_flow_data' in it['path'] or 'mock_bank_api' in it['path']]
batchD = [it for it in rest if it not in batchC]

batches = {'A_web': batchA, 'B_docs': batchB, 'C_mockdata': batchC, 'D_sql_html': batchD}

for k, v in batches.items():
    with open(rf'c:\Users\王小棵\Documents\财务流水自动化\_batch_{k}.json', 'w', encoding='utf-8') as f:
        json.dump(v, f, ensure_ascii=False)
    print(k, sum(len(it['content']) for it in v), len(v))
    for it in v:
        print('   ', it['path'])