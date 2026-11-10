# Phase 0 评测跑批：直调 LLMService，三层断言（plan/SQL/执行），输出 markdown 报告
# 运行：backend/.venv/Scripts/python.exe backend/tests/evals/run_evals.py [--id T001 ...] [--repeat N] [--dry] [--out FILE]
# 判定口径：assert=plan_sql|sql|exec|clarify|fallback|no_plan；sql_keys 支持 "A|B" 任一匹配。
import argparse
import asyncio
import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text as sa_text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlmodel import (  # noqa: E402  LLMService 依赖 SQLModel Session（session.exec API）
    Session,
)

import main  # noqa: F401,E402  按生产顺序初始化
from apps.chat.models.chat_model import (  # noqa: E402
    ChatFinishStep,
    ChatQuestion,
    OperationEnum,
)
from apps.chat.task.llm import LLMService  # noqa: E402
from apps.system.schemas.system_schema import UserInfoDTO  # noqa: E402
from common.core.db import engine  # noqa: E402

SessionLocal = sessionmaker(bind=engine, class_=Session)
CASES_FILE = Path(__file__).with_name('cases.jsonl')


def load_cases(only_ids=None):
    cases = []
    with open(CASES_FILE, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            if only_ids and c['id'] not in only_ids:
                continue
            cases.append(c)
    return cases


def load_user(session) -> UserInfoDTO:
    row = session.execute(sa_text(
        "select id, name, email, account, oid from sys_user order by id limit 1")).mappings().first()
    if not row:
        raise RuntimeError('sys_user 为空，无法构造评测用户')
    data = dict(row)
    data.setdefault('language', 'zh-CN')
    return UserInfoDTO.model_validate(data)


def get_or_create_eval_chat(session, oid=1, datasource_id=1) -> int:
    row = session.execute(sa_text(
        "select id from chat where brief = 'phase0-eval' and chat_type='chat' order by id limit 1")).scalar()
    if row:
        return int(row)
    session.execute(sa_text(
        "insert into chat (oid, brief, chat_type, datasource, engine_type, origin) "
        "values (:oid, 'phase0-eval', 'chat', :ds, 'mysql', 0)"),
        {'oid': oid, 'ds': datasource_id})
    session.commit()
    return int(session.execute(sa_text("select max(id) from chat")).scalar())


async def run_one(session, user, chat_id, question, datasource_id, finish_step):
    """跑一题：返回 (record_id, error_str, duration)。"""
    q = ChatQuestion(chat_id=chat_id, question=question, datasource_id=datasource_id)
    svc = await LLMService.create(session, user, q, None, embedding=False)
    svc.init_record(session=session)
    rec_id = svc.get_record().id
    t0 = time.time()
    err = None
    try:
        for _ in svc.run_task(in_chat=False, stream=False, finish_step=finish_step):
            pass
    except Exception as e:  # noqa: BLE001
        err = f'{type(e).__name__}: {e}'
    return rec_id, err, time.time() - t0


def fetch_evidence(record_id):
    """从 DB 取 record 结果 + op16 plan + op17 route + op19 摘要（独立 session 避免事务快照）。"""
    s = SessionLocal()
    try:
        rec = s.execute(sa_text(
            "select question, sql, error, finish, "
            "left(coalesce(sql_exec_result,''),400) as sql_exec_result "
            "from chat_record where id = :i"), {'i': record_id}).mappings().first()
        plan, plan_status = None, 'absent'
        route, route_reason = None, None
        calc_snip = None
        rows = s.execute(sa_text(
            "select operate, messages from chat_log where pid = :i order by id"),
            {'i': record_id}).fetchall()
        for op, fm in rows:
            if op == OperationEnum.QUERY_PLAN.value and fm:
                for part in fm if isinstance(fm, list) else [fm]:
                    if isinstance(part, dict) and part.get('type') == 'ai':
                        try:
                            payload = json.loads(part.get('content') or '{}')
                        except Exception:  # noqa: BLE001
                            continue
                        plan_status = payload.get('status', 'unknown')
                        plan = payload.get('plan')
            elif op == OperationEnum.DSL_COMPILE.value and fm:
                for part in fm if isinstance(fm, list) else [fm]:
                    if isinstance(part, dict) and part.get('type') == 'ai':
                        try:
                            meta = json.loads(part.get('content') or '{}')
                        except Exception:  # noqa: BLE001
                            continue
                        if isinstance(meta, dict):
                            route = meta.get('route', route)
                            route_reason = meta.get('reason', route_reason)
            elif op == OperationEnum.CALC_ENGINE.value and fm:
                calc_snip = json.dumps(fm, ensure_ascii=False)[:400]
        return {
            'sql': (rec['sql'] or '') if rec else '',
            'error': (rec['error'] or '') if rec else '',
            'exec_res': (rec['sql_exec_result'] or '') if rec else '',
            'plan': plan,
            'plan_status': plan_status,
            'route': route,
            'route_reason': route_reason,
            'calc': calc_snip,
        }
    finally:
        s.close()


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def judge(case, ev, runtime_err):
    """返回 (passed, layers dict, notes list)。layers 值: True/False/None(不适用)。"""
    exp = case.get('expect') or {}
    assert_kind = case['assert']
    plan, sql = ev['plan'], ev['sql']
    layers = {'plan': None, 'sql': None, 'exec': None, 'clarify': None, 'fallback': None}
    notes = []

    _hard_kw = ('Traceback', 'Error code', 'insufficient balance', 'Internal Server')
    hard_err = bool(ev['error']) and any(k in ev['error'] for k in _hard_kw)
    exec_ok = (not runtime_err) and (not hard_err)
    layers['exec'] = exec_ok
    if runtime_err:
        notes.append(f'runtime:{runtime_err[:160]}')
    if ev['error']:
        notes.append(f'record.error:{ev["error"][:160]}')

    if plan:
        if exp.get('query_type') and plan.get('query_type') != exp['query_type']:
            layers['plan'] = False
            notes.append(f"query_type={plan.get('query_type')} want={exp['query_type']}")
        elif exp.get('calculation') and exp['calculation'] != 'none':
            got = (plan.get('calculation') or {}).get('type')
            if got != exp['calculation']:
                layers['plan'] = False
                notes.append(f'calculation={got} want={exp["calculation"]}')
            else:
                layers['plan'] = True
        else:
            layers['plan'] = True
        if layers['plan'] is not False and exp.get('time_contains'):
            hay = _dump(plan) + ' ' + sql
            missing = [t for t in exp['time_contains'] if t not in hay]
            if missing:
                layers['plan'] = False
                notes.append(f'time missing={missing}')
    elif assert_kind in ('plan_sql',):
        layers['plan'] = False
        notes.append('plan absent')

    if case.get('sql_keys'):
        hay = sql.lower()
        miss = []
        for key in case['sql_keys']:
            alts = [a.strip().lower() for a in key.split('|') if a.strip()]
            if not any(a in hay for a in alts):
                miss.append(key)
        layers['sql'] = not miss and bool(sql)
        if miss:
            notes.append(f'sql_keys miss={miss}')
        if not sql:
            notes.append('sql empty')
    elif assert_kind == 'sql':
        layers['sql'] = bool(sql)

    if assert_kind == 'clarify':
        nc = ((plan or {}).get('ambiguity') or {}).get('need_clarification')
        layers['clarify'] = bool(nc)
        conf = ((plan or {}).get('confidence') or {}).get('metric_confidence')
        notes.append(f'need_clarification={nc} conf={conf}')
    elif assert_kind == 'fallback':
        ok = ev['route'] not in ('dsl', 'dsl_compiled')
        layers['fallback'] = ok
        notes.append(f'route={ev["route"]} reason={ev["route_reason"]}')
    elif assert_kind == 'no_plan':
        layers['plan'] = plan is None or plan_status_is_failed(ev)
        notes.append(f'plan={"absent" if not plan else "present"}')

    if assert_kind == 'plan_sql':
        passed = layers['plan'] and layers['sql'] and exec_ok
    elif assert_kind == 'sql':
        passed = layers['sql'] and exec_ok
    elif assert_kind == 'exec':
        passed = exec_ok
    elif assert_kind == 'clarify':
        passed = layers['clarify']
    elif assert_kind == 'fallback':
        passed = layers['fallback'] and exec_ok
    elif assert_kind == 'no_plan':
        passed = layers['plan'] and (not sql) and exec_ok
    else:
        passed = False
        notes.append(f'unknown assert={assert_kind}')
    return bool(passed), layers, notes


def plan_status_is_failed(ev):
    return ev['plan_status'] == 'failed'


def track_of(ev):
    if ev['route'] in ('dsl', 'dsl_compiled'):
        return 'dsl'
    if ev['route'] == 'llm_fallback':
        return 'llm'
    return 'no_dsl'


async def run_all(cases, repeat, datasource_id):
    user_session = SessionLocal()
    try:
        user = load_user(user_session)
        chat_id = get_or_create_eval_chat(user_session, oid=user.oid, datasource_id=datasource_id)
    finally:
        user_session.close()

    results = []
    for case in cases:
        for attempt in range(1, repeat + 1):
            s = SessionLocal()
            t0 = time.time()
            try:
                rec_id, rerr, dur = await run_one(
                    s, user, chat_id, case['q'], datasource_id, ChatFinishStep.QUERY_DATA)
            except Exception as e:  # noqa: BLE001
                rec_id, rerr, dur = None, f'create:{type(e).__name__}: {e}', time.time() - t0
            finally:
                s.close()
            ev = fetch_evidence(rec_id) if rec_id else {
                'sql': '', 'error': rerr or '', 'exec_res': '', 'plan': None,
                'plan_status': 'absent', 'route': None, 'route_reason': None, 'calc': None}
            passed, layers, notes = judge(case, ev, rerr)
            results.append({
                'id': case['id'], 'cat': case['cat'], 'assert': case['assert'],
                'want_track': case.get('track'), 'attempt': attempt,
                'record_id': rec_id, 'passed': passed, 'layers': layers,
                'track': track_of(ev), 'plan_status': ev['plan_status'],
                'route_reason': ev['route_reason'], 'conf': _conf_of(ev),
                'notes': notes, 'duration': round(dur, 1),
                'sql_head': (ev['sql'] or '')[:160].replace('\n', ' '),
            })
            mark = 'PASS' if passed else 'FAIL'
            print(f'{mark} {case["id"]} [{case["assert"]}] {case["q"][:40]} '
                  f'({dur:.1f}s track={results[-1]["track"]})'
                  + (f' | {"; ".join(notes)}' if not passed and notes else ''))
    return results


def _conf_of(ev):
    plan = ev.get('plan') or {}
    return ((plan.get('confidence') or {}).get('metric_confidence'))


def write_report(results, cases, out_path):
    total = len(results)
    passed = sum(1 for r in results if r['passed'])
    by_cat, by_assert, by_track = {}, {}, {}
    for r in results:
        by_cat.setdefault(r['cat'], []).append(r)
        by_assert.setdefault(r['assert'], []).append(r)
        by_track.setdefault(r['track'], []).append(r)

    lines = [f'# Phase 0 评测报告 · {datetime.now():%Y-%m-%d %H:%M:%S}', '',
             f'- 题数：{len(cases)}（跑批次数 {total}）',
             f'- 总通过率：**{passed}/{total} = {passed / total * 100:.1f}%**',
             '- 口径：SQL 正确率=assert∈(plan_sql,sql) 且 passed；结果正确率=assert=exec 且 passed（弱断言：不报错）；'
             '澄清/回退按各自断言', '',
             '## 分类', '', '| 分类 | 通过/总数 | 通过率 |', '| --- | --- | --- |']
    for cat in sorted(by_cat):
        rs = by_cat[cat]
        p = sum(1 for x in rs if x['passed'])
        lines.append(f'| {cat} | {p}/{len(rs)} | {p / len(rs) * 100:.0f}% |')
    lines += ['', '## 断言类型', '', '| assert | 通过/总数 |', '| --- | --- |']
    for k in sorted(by_assert):
        rs = by_assert[k]
        p = sum(1 for x in rs if x['passed'])
        lines.append(f'| {k} | {p}/{len(rs)} |')
    lines += ['', '## 实际轨道分布', '', '| track | 次数 |', '| --- | --- |']
    for k in sorted(by_track):
        lines.append(f'| {k} | {len(by_track[k])} |')
    lines += ['', '## 明细', '',
              '| id | 结果 | assert | 期望轨 | 实际轨 | conf | record | 耗时 | 备注 |',
              '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in results:
        lines.append(
            f"| {r['id']} | {'✅' if r['passed'] else '❌'} | {r['assert']} | "
            f"{r['want_track']} | {r['track']} | {r['conf']} | {r['record_id']} | "
            f"{r['duration']}s | {'; '.join(r['notes'])[:180]} |")
    fails = [r for r in results if not r['passed']]
    if fails:
        lines += ['', '## 失败清单（含 SQL 头）', '']
        for r in fails:
            lines.append(f"- **{r['id']}** [{r['assert']}] {'; '.join(r['notes'])[:300]}")
            if r['sql_head']:
                lines.append(f"  - SQL: `{r['sql_head']}`")
    out_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return passed, total


def main_cli():
    ap = argparse.ArgumentParser(description='Phase 0 评测跑批')
    ap.add_argument('--id', nargs='*', help='只跑指定题号')
    ap.add_argument('--repeat', type=int, default=1, help='每题重复次数（默认 1）')
    ap.add_argument('--datasource', type=int, default=1, help='评测数据源 id（默认 1）')
    ap.add_argument('--dry', action='store_true', help='只列题不执行')
    ap.add_argument('--out', default=None, help='报告输出路径（默认 tests/evals/report_<ts>.md）')
    args = ap.parse_args()

    cases = load_cases(args.id)
    if not cases:
        print('无匹配题目')
        return 1
    print(f'loaded {len(cases)} cases (repeat={args.repeat})')
    if args.dry:
        for c in cases:
            print(f"{c['id']} [{c['assert']}] {c['q']}")
        return 0

    results = asyncio.run(run_all(cases, args.repeat, args.datasource))
    out = Path(args.out) if args.out else Path(__file__).with_name(
        f'report_{datetime.now():%Y%m%d_%H%M}.md')
    passed, total = write_report(results, cases, out)
    print(f'\nTOTAL {passed}/{total} = {passed / total * 100:.1f}%  report -> {out}')
    return 0 if passed == total else 2


if __name__ == '__main__':
    sys.exit(main_cli())
