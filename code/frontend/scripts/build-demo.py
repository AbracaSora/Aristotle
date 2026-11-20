"""Build the offline demonstration from the repository's curated resources."""
import json
from pathlib import Path
root = Path(__file__).resolve().parents[3]
resource = root / 'resource'
out = root / 'code/frontend/src/features/map'
manifest = json.loads((resource / 'manifest.json').read_text())
subjects, bank = [], {}
def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
for subject in manifest['subjects']:
    folder = resource / subject['directory']
    nodes = rows(folder / 'knowledge_points.jsonl')
    ids = {n['id'] for n in nodes}
    edges = [[r['source_id'], r['target_id']] for r in rows(folder / 'relations.jsonl') if r['relation_type'] == 'prerequisite_of']
    assert all(a in ids and b in ids for a,b in edges)
    for q in rows(folder / 'questions.jsonl'):
        assert q['knowledge_point_id'] in ids and q['answer'] in q['options']
        bank.setdefault(q['knowledge_point_id'], []).append(q)
    assert all(len(bank.get(n['id'], [])) >= 3 for n in nodes)
    subjects.append({'id':subject['subject_code'], 'title':subject['subject'], 'nodes':[{'id':n['id'],'title':n['name'],'chapter':n['chapter'],'chapterNumber':n['chapter_number']} for n in nodes], 'edges':edges})
(out / 'curriculum.json').write_text(json.dumps({'version':'resource-2027-v1','subjects':subjects},ensure_ascii=False,indent=2))
(out / 'demo-questions.json').write_text(json.dumps(bank,ensure_ascii=False))
print([(s['title'],len(s['nodes'])) for s in subjects], 'questions:',sum(map(len,bank.values())))
