"""Validate four-subject canonical resources and derive exports. No API calls.

Run: python3 resource/scripts/build_resources.py --write
Check committed outputs without changing files: omit --write.
Requires Pydantic 2, as declared by the backend. All four subjects use JSONL
as canonical inputs. Optional views are generated outside resource/.
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True
import verify_answers

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SUBJECTS = [('DS','数据结构','data-structures'),
            ('CO','计算机组成原理','computer-organization'),
            ('OS','操作系统','operating-systems'),
            ('CN','计算机网络','computer-networks')]
LEVELS = ('remember','understand','apply','analyze')
RELATIONS = {'prerequisite_of','recommended_before','related_to','applied_in'}
LABELS = dict(remember='记忆',understand='理解',apply='应用',analyze='分析')


def read_jsonl(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def json_text(data, jsonl=False):
    if jsonl:
        return ''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in data)
    return json.dumps(data,ensure_ascii=False,indent=2)+'\n'


def actual_models():
    schema = REPO/'code/backend/aristotle_backend/schemas.py'
    policy = REPO/'code/core_engine/aristotle_core/policy.py'
    # Execute the request-model definitions, not an imitation of their constraints.
    # Stop before ReviewInput: Python 3.9 can validate these resource models even
    # though later application models use Python 3.10 union annotations.
    body = []
    for node in ast.parse(schema.read_text(encoding='utf-8')).body:
        if isinstance(node,ast.ClassDef) and node.name=='ReviewInput':
            break
        body.append(node)
    namespace = {}
    exec(compile(ast.Module(body=body,type_ignores=[]),str(schema),'exec'),namespace)
    policy_namespace = {}
    exec(compile(policy.read_text(encoding='utf-8'),str(policy),'exec'),policy_namespace)
    return namespace, policy_namespace['validate_graph'], {str(p.relative_to(REPO)):sha(p) for p in (schema,policy)}


def check_canonical(code, subject, points, questions, edges, syllabus):
    ids = [p['id'] for p in points]
    require(len(ids)==len(set(ids)), f'{code}: duplicate point IDs')
    by_id = {p['id']:p for p in points}
    refs = {x['id']:x for x in syllabus['items']}
    require(len(refs)==len(syllabus['items']),f'{code}: duplicate outline locators')
    require(set(refs)=={r for p in points for r in p['syllabus_refs']},f'{code}: outline coverage mismatch')
    for ref, item in refs.items():
        mapped = {p['id'] for p in points if ref in p['syllabus_refs']}
        require(mapped==set(item['knowledge_point_ids']),f'{code}: wrong outline map {ref}')
    for point in points:
        require(re.fullmatch(r'[A-Za-z0-9_-]{1,64}',point['id']) is not None,point['id'])
        require(point['id'].startswith(code+'-'),point['id'])
        require(point['subject_code']==code and point['subject']==subject,point['id'])
    qids = [q['id'] for q in questions]
    require(len(qids)==len(set(qids)),f'{code}: duplicate question IDs')
    counts = Counter(q['knowledge_point_id'] for q in questions)
    require(set(counts)==set(ids),f'{code}: dangling or empty point')
    require(all(3<=n<=5 for n in counts.values()),f'{code}: question count outside 3..5')
    stems = set()
    for q in questions:
        kid = q['knowledge_point_id']
        point = by_id[kid]
        require(q['subject']==subject and q['subject_code']==code,q['id'])
        require(q['chapter_number']==point['chapter_number'] and q['chapter']==point['chapter'],q['id'])
        require(q['knowledge_point']==point['name'],q['id'])
        require(q['knowledge_path']==[subject,point['chapter'],point['name']],q['id'])
        require(q['syllabus_refs'] and set(q['syllabus_refs'])<=set(point['syllabus_refs']),q['id'])
        require(set(q['secondary_knowledge_point_ids'])<=set(ids),q['id'])
        require(type(q['difficulty']) is int and 1<=q['difficulty']<=5,q['id'])
        require(q['question_type']=='single_choice' and q['format']=='text_only',q['id'])
        require(q['cognitive_level_candidate'] in LEVELS,q['id'])
        require(list(q['options'])==list('ABCD') and q['answer'] in q['options'],q['id'])
        require(len(set(q['options'].values()))==4,q['id'])
        for text in [q['stem'],q['explanation'],q['cognitive_rationale'],*q['options'].values()]:
            require(isinstance(text,str) and text.strip(),q['id'])
            require(not re.search(r'!\[|<img|data:image|如图|见图|下图|图中所示',text,re.I),f'{q["id"]}: requires image')
        normalized = re.sub(r'\W','',q['stem']).casefold()
        require(normalized not in stems,f'{q["id"]}: duplicate stem')
        stems.add(normalized)
    edge_ids = set()
    for edge in edges:
        require(edge['id'] not in edge_ids,f'duplicate edge {edge["id"]}')
        edge_ids.add(edge['id'])
        require(edge['source_id'] in by_id and edge['target_id'] in by_id,edge['id'])
        require(edge['source_id']!=edge['target_id'],edge['id'])
        require(edge['relation_type'] in RELATIONS,edge['id'])
    return counts


def graph_payload(points, edges, version, include_recommended=False):
    kinds = {'prerequisite_of','recommended_before'} if include_recommended else {'prerequisite_of'}
    return dict(version=version,nodes=[dict(id=p['id'],name=p['name'],
        prerequisites=sorted({e['source_id'] for e in edges if e['target_id']==p['id'] and e['relation_type'] in kinds})) for p in points])


def source_text(q):
    if q['source_type']=='ai_generated':
        return 'AI独立编写的纯文字练习；非真题'
    fields=['来源类型：'+q['source_type'],'题源核验：'+q['source_verification']]
    for key,label in [('year','年份'),('original_question_number','原题号'),('source_url','网址'),('revision_note','修订说明')]:
        if q.get(key) is not None:
            fields.append(label+'：'+str(q[key]))
    return '；'.join(fields)


def exports(questions):
    qs, cs = [], []
    for q in questions:
        qs.append(dict(question_id=q['id'],version=q['version'],knowledge_id=q['knowledge_point_id'],
            prompt=q['stem'],options=[q['options'][k] for k in 'ABCD'],answer=q['options'][q['answer']],
            explanation=q['explanation'],source=source_text(q)))
        cs.append(dict(question_id=q['id'],question_version=q['version'],
            primary_level=q['cognitive_level_candidate'],secondary_levels=[],rationale=q['cognitive_rationale'],
            confidence=0.5,ambiguity_note='confidence=0.5为未校准占位值，不是实测概率。'))
    return qs,cs


def derivatives(points, questions, edges, graph, order):
    by_id = {p['id']:p for p in points}
    parents = {n['id']:n['prerequisites'] for n in graph['nodes']}
    ancestors, depths = {}, {}
    for kid in order:
        ancestors[kid] = set(parents[kid])
        for parent in parents[kid]:
            ancestors[kid].update(ancestors[parent])
        depths[kid] = max((depths[parent]+1 for parent in parents[kid]),default=0)
    coverage, dependencies = [], []
    for point in points:
        kid = point['id']
        qset = [q for q in questions if q['knowledge_point_id']==kid]
        counts = {level:sum(q['cognitive_level_candidate']==level for q in qset) for level in LEVELS}
        coverage.append(dict(knowledge_point_id=kid,knowledge_point=point['name'],chapter=point['chapter'],
            syllabus_refs=point['syllabus_refs'],question_ids=[q['id'] for q in qset],question_count=len(qset),
            candidate_level_counts=counts,missing_to_three_per_level={level:max(0,3-n) for level,n in counts.items()},
            coverage_status='question_count_met_not_full_subtopic_or_diagnostic_validation'))
        dependencies.append(dict(knowledge_point_id=kid,prerequisite_logic='all_of',
            direct_required_prerequisite_ids=parents[kid],
            indirect_required_prerequisite_ids=sorted(ancestors[kid]-set(parents[kid])),
            direct_required_successor_ids=sorted(k for k in by_id if kid in parents[k]),
            direct_recommended_prerequisite_ids=sorted(e['source_id'] for e in edges if e['target_id']==kid and e['relation_type']=='recommended_before'),
            required_depth=depths[kid],question_ids=[q['id'] for q in qset]))
    return coverage,dependencies


def review_text(subject, points, questions, coverage, dependencies, syllabus):
    qlines = [f'# {subject}题目', '', '每道题包含四个选项、一个答案和解析；均可直接按文字作答。','']
    for point in points:
        qlines += [f'## {point["id"]} · {point["name"]}', '',f'章节：{point["chapter"]}；考纲定位：{", ".join(point["syllabus_refs"])}。','']
        for q in [q for q in questions if q['knowledge_point_id']==point['id']]:
            qlines += [f'### {q["id"]}', '',f'难度：{q["difficulty"]}/5；认知候选：{LABELS[q["cognitive_level_candidate"]]}。','',q['stem'],'']
            qlines += [f'{k}. {v}' for k,v in q['options'].items()]
            qlines += ['',f'**答案：{q["answer"]}**', '',q['explanation'],'']
    lines = [f'# {subject}知识点与覆盖','',f'{len(points)} 个知识点，{len(questions)} 道纯文字单选题，映射 {len(syllabus["items"])} 个公开考纲末级定位条目。', '',
        '题量表示每个知识节点的练习数量；不等同于每个细分条目或每个认知维度都有三题。认知维度缺口见 coverage.json。','',
        '| 知识点 | 章节 | 考纲定位 | 题数 | 直接前提 |','| --- | --- | --- | ---: | --- |']
    for point, row, dep in zip(points,coverage,dependencies):
        lines.append(f'| {point["id"]} {point["name"]} | {point["chapter"]} | {", ".join(point["syllabus_refs"])} | {row["question_count"]} | {", ".join(dep["direct_required_prerequisite_ids"]) or "无"} |')
    lines += ['', '## 考纲映射','', '| 定位 | 范围简称 | 对应知识点 |','| --- | --- | --- |']
    for item in syllabus['items']:
        lines.append(f'| {item["id"]} | {item["topic_summary"]} | {", ".join(item["knowledge_point_ids"])} |')
    lines += ['', '来源、版本与正文核验范围见 syllabus.json。学习前提由教学设计确定，不将其表述为考试大纲规定的先后顺序。','']
    return '\n'.join(qlines),'\n'.join(lines)


def build(write=False, views_dir=None):
    if views_dir is not None:
        views_dir = Path(views_dir).expanduser().resolve()
        require(views_dir != ROOT and ROOT not in views_dir.parents,
                'Generate optional views outside resource/ to keep the resource package compact')
    models, validate_graph, code_hash = actual_models()
    products = {}
    all_points, all_questions, all_edges, api_qs, api_cs, summaries = [], [], [], [], [], []
    subject_data = []
    for code, subject, folder in SUBJECTS:
        root = ROOT/folder
        points = read_jsonl(root/'knowledge_points.jsonl')
        questions = read_jsonl(root/'questions.jsonl')
        edges = read_jsonl(root/'relations.jsonl')
        syllabus = json.loads((root/'syllabus.json').read_text(encoding='utf-8'))
        counts = check_canonical(code,subject,points,questions,edges,syllabus)
        graph = graph_payload(points,edges,f'kew-{code.lower()}-text-v1')
        models['GraphInput'].model_validate(graph)
        validate_graph(graph['nodes'])
        validate_graph(graph_payload(points,edges,'order',True)['nodes'])
        question_payload, candidates = exports(questions)
        for row in question_payload:
            models['QuestionInput'].model_validate(row)
        for row in candidates:
            models['CandidateInput'].model_validate(row)
        input_hashes = {name:sha(root/name) for name in ('knowledge_points.jsonl','questions.jsonl','relations.jsonl','syllabus.json')}
        summaries.append(dict(subject=subject,subject_code=code,directory=folder,
            knowledge_points=len(points),questions=len(questions),relations=len(edges),syllabus_items=len(syllabus['items']),
            questions_per_point=dict(min=min(counts.values()),max=max(counts.values())),canonical_sha256=input_hashes))
        subject_data.append((subject,folder,points,questions,edges,syllabus))
        all_points.extend(points)
        all_questions.extend(questions)
        all_edges.extend(edges)
        api_qs.extend(question_payload)
        api_cs.extend(candidates)
    cross = read_jsonl(ROOT/'cross_subject_relations.jsonl')
    all_edges.extend(cross)
    point_ids = {p['id'] for p in all_points}
    require(len(point_ids)==len(all_points),'globally duplicated point IDs')
    require(len({q['id'] for q in all_questions})==len(all_questions),'globally duplicated question IDs')
    require(len({re.sub(r'\W','',q['stem']).casefold() for q in all_questions})==len(all_questions),'globally duplicated stems')
    require(len({e['id'] for e in all_edges})==len(all_edges),'globally duplicated edge IDs')
    for e in all_edges:
        require(e['source_id'] in point_ids and e['target_id'] in point_ids,e['id'])
        require(e['source_id']!=e['target_id'],e['id'])
        require(e['relation_type'] in RELATIONS,e['id'])
        require(e['directed']==(e['relation_type']!='related_to'),e['id'])
    for e in cross:
        require(e['source_id'].split('-')[0]!=e['target_id'].split('-')[0],e['id'])
    full_graph = graph_payload(all_points,all_edges,'kew-408-text-v1')
    full_order = validate_graph(full_graph['nodes'])
    recommended_order = validate_graph(graph_payload(all_points,all_edges,'full-order',True)['nodes'])
    maximum = models['GraphInput'].model_json_schema()['properties']['nodes']['maxItems']
    graph_errors = []
    try:
        models['GraphInput'].model_validate(full_graph)
    except Exception as exc:
        if not hasattr(exc,'errors'):
            raise
        graph_errors = [dict(location=list(e['loc']),type=e['type'],message=e['msg']) for e in exc.errors()]
        require(len(full_graph['nodes'])>maximum and all(e['location']==['nodes'] and e['type']=='too_long' for e in graph_errors),str(graph_errors))
    integration_status = 'blocked_graph_node_limit' if graph_errors else 'passed_request_models'
    full_coverage, full_dependencies = derivatives(all_points,all_questions,all_edges,full_graph,full_order)
    answers = verify_answers.run()
    coverage_summary = dict(points_with_3_to_5_questions=len(full_coverage),
        points_with_three_questions_in_every_level=sum(all(n>=3 for n in row['candidate_level_counts'].values()) for row in full_coverage),
        missing_to_three_per_level={level:sum(row['missing_to_three_per_level'][level] for row in full_coverage) for level in LEVELS},
        note='每点总题量与每个认知维度的题量是不同指标；逐点分布可通过--views-dir生成。')
    products[ROOT/'manifest.json'] = json_text(dict(schema_version=1,exam='408计算机学科专业基础',target_year=2027,
        subjects=summaries,total_knowledge_points=len(all_points),total_questions=len(all_questions),
        total_relations=len(all_edges),cross_subject_relations=len(cross),
        canonical_layout='<subject>/questions.jsonl, knowledge_points.jsonl, relations.jsonl, syllabus.json',
        cross_subject_relation_file='cross_subject_relations.jsonl',
        exports=dict(graph='exports/aristotle_graph.full.json',questions='exports/aristotle_questions.jsonl',candidates='exports/aristotle_candidates.jsonl'),
        rebuild='python3 resource/scripts/build_resources.py --write',verify='python3 resource/scripts/build_resources.py',
        optional_views='python3 resource/scripts/build_resources.py --views-dir /tmp/aristotle-review',
        report='validation_report.json',integration_status=integration_status,active_graph_limit=maximum,
        field_mapping={'knowledge_point_id':'QuestionInput.knowledge_id','stem':'QuestionInput.prompt',
            'options':'A/B/C/D顺序转换为文本数组','answer':'正确选项字母转换为对应文本',
            'cognitive_level_candidate':'CandidateInput.primary_level','prerequisite_of':'GraphInput.nodes[].prerequisites'},
        metadata_note='科目、章节、难度、考纲定位和其他关系保留在规范JSONL，接口导出不增加后端未定义字段。'))
    products[ROOT/'exports/aristotle_graph.full.json'] = json_text(full_graph)
    products[ROOT/'exports/aristotle_questions.jsonl'] = json_text(api_qs,True)
    products[ROOT/'exports/aristotle_candidates.jsonl'] = json_text(api_cs,True)
    report = dict(resource_validation='passed',
        structural_checks=['unique_ids','unique_stems','unique_options','answer_membership','text_only','3_to_5_per_point',
            'outline_reference_coverage','edge_references','edge_directions','required_dag','recommended_dag'],
        subjects=summaries,total_knowledge_points=len(all_points),total_questions=len(all_questions),total_relations=len(all_edges),
        coverage_summary=coverage_summary,answer_checks=answers,
        integration_checks=dict(status=integration_status,subject_graph_models='passed',
            question_models=dict(status='passed',count=len(api_qs)),candidate_models=dict(status='passed',count=len(api_cs)),
            merged_dag=dict(status='passed',nodes=len(all_points)),
            merged_graph_model=dict(status='blocked' if graph_errors else 'passed',max_nodes=maximum,errors=graph_errors),
            code_sha256=code_hash,scope='实际请求模型及图校验；未执行HTTP、数据库或发布操作。'),
        cross_subject_relations_sha256=sha(ROOT/'cross_subject_relations.jsonl'),
        builder_sha256=sha(Path(__file__)),export_sha256={p.name:hashlib.sha256(value.encode()).hexdigest() for p,value in products.items() if p.parent==ROOT/'exports'})
    products[ROOT/'validation_report.json'] = json_text(report)
    drift = []
    for path,value in products.items():
        if write:
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(value,encoding='utf-8')
        elif not path.exists() or path.read_text(encoding='utf-8')!=value:
            drift.append(str(path.relative_to(ROOT)))
    require(not drift,'Derived files differ; rebuild with --write: '+', '.join(drift))
    if views_dir is not None:
        views = {}
        for subject,folder,points,questions,edges,syllabus in subject_data:
            graph = graph_payload(points,edges,'view')
            order = validate_graph(graph['nodes'])
            coverage,deps = derivatives(points,questions,edges,graph,order)
            qtext,ktext = review_text(subject,points,questions,coverage,deps,syllabus)
            views[views_dir/folder/'全部题目.md']=qtext
            views[views_dir/folder/'知识点与覆盖.md']=ktext
            views[views_dir/folder/'coverage.json']=json_text(coverage)
            views[views_dir/folder/'syllabus.json']=json_text(syllabus)
        views[views_dir/'knowledge_graph.json']=json_text(dict(nodes=all_points,edges=all_edges))
        views[views_dir/'dependencies.jsonl']=json_text(full_dependencies,True)
        views[views_dir/'coverage.json']=json_text(full_coverage)
        views[views_dir/'learning_order.json']=json_text(dict(required_topological_order=full_order,recommended_topological_order=recommended_order))
        for path,value in views.items():
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(value,encoding='utf-8')
    return dict(resource_validation='passed',integration_status=integration_status,
        total_nodes=len(all_points),total_questions=len(all_questions),total_relations=len(all_edges),
        computed_answers=answers['checked_questions'],derived_files=len(products),optional_views=str(views_dir) if views_dir else None)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write',action='store_true',help='Regenerate manifest, unified exports and one report; never modify canonical inputs')
    parser.add_argument('--views-dir',help='Optional external destination for readable questions, graphs, dependencies and coverage')
    args = parser.parse_args()
    print(json.dumps(build(args.write,args.views_dir),ensure_ascii=False,indent=2))
