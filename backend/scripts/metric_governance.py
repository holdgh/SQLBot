# ========= 【改造标记 METRIC-CENTER】↓ Phase 1 元数据治理一次性辅助脚本 =========
"""指标中心 Phase 1 元数据治理辅助脚本（一次性工具，不参与产品运行链路）。

三个子命令（在 backend/ 目录下执行）：
  gen            读取数据源已勾选表（结构/注释/样本数据），调用 LLM 生成候选草稿：
                   metrics.jsonl      指标候选（含别名/维度名/依赖）
                   dimensions.jsonl   维度候选
                   comments.jsonl     表/字段业务描述候选（core_*.custom_comment）
                   schema_docs.jsonl  Phase 2 schema 语义文档草稿（TABLE/COLUMN 双粒度）
  apply          人工确认后，把 metrics.jsonl + dimensions.jsonl 导入指标中心
                 （走 apps.metric.curd：查重、重建检索文档、补 embedding）
  apply-comments 人工确认后，把 comments.jsonl 写入 core_table/core_field.custom_comment
                 （默认只补空白，--overwrite 才覆盖已有；这是人工治理动作，
                   写入后会进入既有问数链路的 DDL 描述，与 METRIC_CENTER_ENABLED 无关）

典型流程：
  python scripts/metric_governance.py gen --ds 1
  # 人工编辑 governance_out/ds1/*.jsonl（可整行删除、可修正字段）
  python scripts/metric_governance.py apply --ds 1
  python scripts/metric_governance.py apply-comments --ds 1   # 可选

约束：
  - schema_docs.jsonl 只落文件不建表（Phase 2 才建，规则 G5 预留≠实现）。
  - 指标是否参与问数仍由 METRIC_CENTER_ENABLED 开关控制，本脚本不改产品代码行为。
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 以 backend/ 为导入根

import orjson  # noqa: E402
import sqlbot_xpack  # noqa: E402,F401  必须先于 apps.* 导入（与 main.py 顺序一致，避免循环导入）

from apps.metric.curd.metric import (  # noqa: E402
    create_dimension,
    create_metric,
    list_dimension,
)
from apps.metric.models.metric_model import (  # noqa: E402
    DimensionInfo,
    MetricDependencyInfo,
    MetricInfo,
)

# ---------- 常量 ----------

METRIC_FIELDS = [
    'metric_name', 'description', 'business_domain', 'source_table', 'source_column',
    'aggregation', 'filter_rule', 'time_field', 'metric_type', 'unit', 'normal_range',
    'additivity', 'aliases', 'dimension_names', 'dependencies',
]
AGGREGATIONS = ('sum', 'avg', 'count', 'min', 'max')
METRIC_TYPES = ('atomic', 'derived', 'composite')
ADDITIVITIES = ('additive', 'semi', 'non')

# ---------- LLM 提示词（一次性脚本自带，不进产品提示词体系） ----------

METRICS_SYSTEM_PROMPT = """\
你是数据仓库指标治理助手。根据给出的表结构、字段注释与样本数据，产出可供人工确认的「指标候选」与「维度候选」。
硬性要求：
1. metrics 每项字段：metric_name（简洁中文业务名，不带表名前缀，不与常见指标重名）、
   description（业务口径：算什么、怎么算、含什么过滤条件）、business_domain（业务域，简短）、
   source_table（必须是本表名）、source_column（本表中被聚合的数值字段；count 类可为 null）、
   aggregation（只能是 sum/avg/count/min/max 之一）、filter_rule（口径过滤条件，无则 null）、
   time_field（本表日期/时间字段，无则 null）、metric_type（atomic/derived/composite，
   derived 必须给 dependencies）、unit（如 元/人/次/%，未知 null）、
   normal_range（{"min":..,"max":..} 或 null，未知给 null）、additivity（additive/semi/non）、
   aliases（中文常见同义叫法数组，可为空）、dimension_names（分析维度名数组，只能用下方
   dimensions 候选中的名字）、dependencies（derived 才有：
   [{"depends_on_metric_name":"..","expression_hint":".."}]，依赖的必须是本次产出的指标名）。
2. dimensions 每项字段：dimension_name（中文）、aliases（数组，可空）、
   column_name（必须是本表已有字段名）、description（业务含义）。
3. 只产出该表能直接支撑的指标与维度；不确定就少给，禁止杜撰不存在的表/字段/维度。
4. 只输出一个 JSON 对象，格式：
{"metrics":[{"metric_name":"","description":"","business_domain":"","source_table":"","source_column":null,"aggregation":"sum","filter_rule":null,"time_field":null,"metric_type":"atomic","unit":null,"normal_range":null,"additivity":"additive","aliases":[],"dimension_names":[],"dependencies":[]}],"dimensions":[{"dimension_name":"","aliases":[],"column_name":"","description":""}]}
不要输出任何其他内容。"""

DOCS_SYSTEM_PROMPT = """\
你是数据治理助手。根据给出的表结构、字段注释与样本数据，产出三类候选供人工确认：
1. table_comment：该表的业务用途（中文 1~2 句，只讲业务不讲技术实现）。
2. column_comments：字段业务含义，key 必须是本表字段名；只给出能从数据/注释判断的字段。
3. schema_docs：语义文档草稿（供后续检索用的业务语义文本）：
   - TABLE 级一条，object_key 为表名，document_text = 表用途 + 常见分析场景；
   - COLUMN 级按能判断的字段给出，object_key 为 "表名.字段名"，
     document_text = 业务含义 + 取值形态 + 支持的分析。
已有 custom_comment 的字段仍可给出更精炼版本（导入时默认只补空白）。
只输出一个 JSON 对象，格式：
{"table_comment":"","column_comments":{},"schema_docs":[{"object_type":"TABLE","object_key":"","document_text":""}]}
不要输出任何其他内容。"""


# ---------- 基础工具 ----------

def _table_context(ds, table, fields, include_sample: bool = True) -> str:
    """拼单表上下文：表注释/字段清单（含注释）/3 行样本数据。"""
    lines = [f'数据源类型: {ds.type}', f'表名: {table.table_name}']
    table_comment = (table.custom_comment or '').strip() or (table.table_comment or '').strip()
    if table_comment:
        lines.append(f'表注释: {table_comment}')
    lines.append('字段:')
    for f in fields:
        comment = (f.custom_comment or '').strip() or (f.field_comment or '').strip()
        line = f'- {f.field_name} {f.field_type}'
        if comment:
            line += f'  注释: {comment}'
        lines.append(line)
    if include_sample:
        from apps.datasource.crud.datasource import get_table_sample_data
        sample = get_table_sample_data(ds, table.table_name, fields)
        if sample:
            lines.append('样本数据(最多3行):')
            lines.append(sample)
    return '\n'.join(lines)


def _parse_llm_json(text: str) -> dict:
    from common.utils.utils import extract_nested_json
    json_str = extract_nested_json(text or '')
    if not json_str:
        raise ValueError(f'LLM 输出中未找到合法 JSON: {(text or "")[:200]}')
    data = orjson.loads(json_str)
    if not isinstance(data, dict):
        raise ValueError('LLM 输出的 JSON 不是对象')
    return data


def _get_llm(args):
    """构造同步可调用的 langchain 聊天模型；优先命令行显式指定，否则用系统默认模型。"""
    from apps.ai_model.model_factory import LLMConfig, LLMFactory, get_default_config

    if args.api_base_url:
        config = LLMConfig(
            model_type=args.model_type,
            model_name=args.model_name or 'default',
            api_key=args.api_key,
            api_base_url=args.api_base_url,
            additional_params={'temperature': 0},
        )
    else:
        config = asyncio.run(get_default_config(args.model_id))
        config = config.model_copy(update={'additional_params': {**config.additional_params,
                                                                 'temperature': 0}})
    return LLMFactory.create_llm(config).llm


def _ask(llm, system: str, user: str, retries: int = 2) -> dict:
    last_err = None
    for _ in range(retries + 1):
        try:
            message = llm.invoke([('system', system), ('human', user)])
            return _parse_llm_json(getattr(message, 'content', str(message)))
        except Exception as e:  # noqa: BLE001 单表失败重试，最终失败交由上层记录
            last_err = e
    raise RuntimeError(f'LLM 调用/解析失败: {last_err}')


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(orjson.loads(line))
        except Exception as e:  # noqa: BLE001
            raise ValueError(f'{path} 第 {line_no} 行不是合法 JSON: {e}') from e
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = '\n'.join(orjson.dumps(r).decode('utf-8') for r in rows)
    path.write_text(body + ('\n' if body else ''), encoding='utf-8')


def _load_table_objs(session, ds, tables_filter):
    from types import SimpleNamespace

    from apps.datasource.crud.datasource import get_table_obj_by_ds
    # id=1 视为管理员，绕过列权限过滤（治理脚本面向全量已勾选表）
    admin = SimpleNamespace(id=1)
    objs = get_table_obj_by_ds(session, admin, ds)
    if tables_filter:
        wanted = {t.strip() for t in tables_filter if t.strip()}
        objs = [o for o in objs if o.table.table_name in wanted]
    return objs


# ---------- gen ----------

def cmd_gen(args) -> int:
    from sqlmodel import Session

    from apps.datasource.crud.datasource import get_ds
    from common.core.db import engine

    out_dir = Path(args.out) / f'ds{args.ds}'
    want_metrics = args.part in ('all', 'metrics')
    want_docs = args.part in ('all', 'docs')

    # 已有草稿的分段默认跳过（防止覆盖人工确认过的编辑），--force 才重跑
    if want_metrics and (out_dir / 'metrics.jsonl').exists() and not args.force:
        print(f'[跳过] {out_dir / "metrics.jsonl"} 已存在（指标/维度分段），覆盖请加 --force')
        want_metrics = False
    if want_docs and (out_dir / 'comments.jsonl').exists() and not args.force:
        print(f'[跳过] {out_dir / "comments.jsonl"} 已存在（描述/文档分段），覆盖请加 --force')
        want_docs = False
    if not want_metrics and not want_docs:
        return 0

    session = Session(engine)
    llm = None
    try:
        ds = get_ds(session, args.ds)
        if ds is None:
            print(f'[错误] 数据源 id={args.ds} 不存在')
            return 1
        objs = _load_table_objs(session, ds, args.tables.split(',') if args.tables else None)
        if not objs:
            print('[错误] 该数据源没有已勾选的表（core_table.checked=true）')
            return 1

        metric_rows: list[dict] = []
        dim_rows: list[dict] = []
        comment_rows: list[dict] = []
        doc_rows: list[dict] = []
        seen_metrics: set[str] = set()
        seen_dims: set[str] = set()
        errors: list[str] = []
        written: list[str] = []

        def _emit(path: Path, rows: list[dict]) -> None:
            if rows or args.force:
                _write_jsonl(path, rows)

        def _flush_drafts() -> None:
            """每张表处理完即落盘：LLM 慢，进程中断不丢已完成结果。"""
            if want_metrics:
                _emit(out_dir / 'metrics.jsonl', metric_rows)
                _emit(out_dir / 'dimensions.jsonl', dim_rows)
            if want_docs:
                _emit(out_dir / 'comments.jsonl', comment_rows)
                _emit(out_dir / 'schema_docs.jsonl', doc_rows)

        for idx, obj in enumerate(objs, 1):
            table = obj.table
            fields = obj.fields or []
            if not fields:
                print(f'[{idx}/{len(objs)}] {table.table_name}: 无勾选字段，跳过')
                continue
            context = _table_context(ds, table, fields)

            if want_metrics:
                if llm is None:
                    llm = _get_llm(args)
                print(f'[{idx}/{len(objs)}] {table.table_name}: 生成指标候选 ...')
                try:
                    data = _ask(llm, METRICS_SYSTEM_PROMPT, context)
                except Exception as e:  # noqa: BLE001
                    errors.append(f'{table.table_name} metrics: {e}')
                    print(f'  [失败] {e}')
                else:
                    for m in data.get('metrics') or []:
                        name = (m.get('metric_name') or '').strip()
                        if not name or name in seen_metrics:
                            continue
                        seen_metrics.add(name)
                        m['source_table'] = m.get('source_table') or table.table_name
                        # ========= 【改造标记 METRIC-CENTER】↓ 问题2方案A：草稿显式带表所属数据源（人工可改） =========
                        m.setdefault('source_ds_id', ds.id)
                        # ========= 【改造标记 METRIC-CENTER】↑ 落稿开始 =========
                        m['_meta'] = {'ds_id': ds.id, 'table': table.table_name}
                        metric_rows.append(m)
                    for d in data.get('dimensions') or []:
                        name = (d.get('dimension_name') or '').strip()
                        if not name or name in seen_dims:
                            continue
                        seen_dims.add(name)
                        # ========= 【改造标记 METRIC-CENTER】↓ 问题4：维度草稿行内写落点三元组（与前后端 dimension 字段一致） =========
                        d.setdefault('source_ds_id', ds.id)
                        d.setdefault('source_table', table.table_name)
                        # ========= 【改造标记 METRIC-CENTER】↑ 问题4 落稿结束（原仅 _meta 记录，不入库） =========
                        d['_meta'] = {'ds_id': ds.id, 'table': table.table_name}
                        dim_rows.append(d)
                    print(f'  指标 {len(data.get("metrics") or [])} 个，'
                          f'维度 {len(data.get("dimensions") or [])} 个')

            if want_docs:
                if llm is None:
                    llm = _get_llm(args)
                print(f'[{idx}/{len(objs)}] {table.table_name}: 生成描述/语义文档候选 ...')
                try:
                    data = _ask(llm, DOCS_SYSTEM_PROMPT, context)
                except Exception as e:  # noqa: BLE001
                    errors.append(f'{table.table_name} docs: {e}')
                    print(f'  [失败] {e}')
                else:
                    tc = (data.get('table_comment') or '').strip()
                    if tc:
                        comment_rows.append({'object_type': 'TABLE', 'table': table.table_name,
                                             'column': None, 'custom_comment': tc,
                                             '_meta': {'ds_id': ds.id}})
                    for col, comment in (data.get('column_comments') or {}).items():
                        if not (comment or '').strip():
                            continue
                        comment_rows.append({'object_type': 'COLUMN', 'table': table.table_name,
                                             'column': col, 'custom_comment': comment.strip(),
                                             '_meta': {'ds_id': ds.id}})
                    for doc in data.get('schema_docs') or []:
                        if doc.get('object_type') not in ('TABLE', 'COLUMN'):
                            continue
                        if not (doc.get('document_text') or '').strip():
                            continue
                        doc_rows.append({'object_type': doc['object_type'],
                                         'object_key': doc.get('object_key') or table.table_name,
                                         'document_text': doc['document_text'].strip(),
                                         '_meta': {'ds_id': ds.id}})
                    print(f'  表描述 {1 if tc else 0}，字段描述 '
                          f'{len(data.get("column_comments") or {})}，语义文档 '
                          f'{len(data.get("schema_docs") or [])} 条')
            _flush_drafts()

        if want_metrics:
            written.append(f'metrics.jsonl ({len(metric_rows)} 行)')
            written.append(f'dimensions.jsonl ({len(dim_rows)} 行)')
        if want_docs:
            written.append(f'comments.jsonl ({len(comment_rows)} 行)')
            written.append(f'schema_docs.jsonl ({len(doc_rows)} 行)')

        print(f'\n[完成] 输出目录: {out_dir}')
        for f in written:
            print(f'  - {f}')
        if errors:
            print(f'[警告] {len(errors)} 个失败项:')
            for e in errors:
                print(f'  - {e}')
        print('\n下一步：人工编辑上述 jsonl（删除/修正），然后执行 apply 导入。')
        return 0
    finally:
        session.close()


# ---------- apply ----------

def cmd_apply(args) -> int:
    from sqlmodel import Session

    from common.core.db import engine
    from common.core.deps import i18n
    from common.utils.embedding_threads import executor

    in_dir = Path(args.in_) / f'ds{args.ds}'
    metric_rows = _read_jsonl(in_dir / 'metrics.jsonl')
    dim_rows = _read_jsonl(in_dir / 'dimensions.jsonl')
    if not metric_rows and not dim_rows:
        print(f'[错误] {in_dir} 下没有可导入的 metrics.jsonl / dimensions.jsonl')
        return 1

    session = Session(engine)
    trans = i18n(None, 'zh-cn')
    oid = args.oid
    # 解析维度时的可选集 = 库内已有 ∪ 本次草稿（dry-run 不写库也能正确判定）
    draft_dim_names = {(r.get('dimension_name') or '').strip() for r in dim_rows}
    created_dims: dict[str, int] = {}
    dim_skipped = dim_failed = 0
    metric_ok = metric_skipped = metric_failed = 0
    try:
        # 1) 维度先入库（按名字幂等）
        existing = {d.dimension_name: d.id for d in list_dimension(session, oid)}
        for row in dim_rows:
            name = (row.get('dimension_name') or '').strip()
            if not name:
                dim_failed += 1
                print('  [维度跳过] dimension_name 为空')
                continue
            if name in existing:
                dim_skipped += 1
                continue
            if args.dry_run:
                print(f'  [dry-run] 将新建维度: {name}')
                continue
            try:
                dim_id = create_dimension(session, DimensionInfo(
                    dimension_name=name,
                    aliases=[a for a in (row.get('aliases') or []) if a],
                    # ========= 【改造标记 METRIC-CENTER】↓ 问题4：落点三元组入库（兼容旧草稿键 default_column/_meta） =========
                    source_ds_id=row.get('source_ds_id') or (row.get('_meta') or {}).get('ds_id') or args.ds,
                    source_table=row.get('source_table') or (row.get('_meta') or {}).get('table'),
                    column_name=row.get('column_name') or row.get('default_column'),
                    # ========= 【改造标记 METRIC-CENTER】↑ 问题4 入库结束（原 default_column） =========
                    description=row.get('description'),
                ), oid, trans)
            except Exception as e:  # noqa: BLE001
                dim_failed += 1
                print(f'  [维度失败] {name}: {e}')
            else:
                existing[name] = dim_id
                created_dims[name] = dim_id
        print(f'[维度] 新建 {len(created_dims)}，已存在跳过 {dim_skipped}，失败 {dim_failed}')

        # 2) 指标入库（specific_ds=True + datasource_ids=[--ds]，同数据源作用域查重）
        for row in metric_rows:
            name = (row.get('metric_name') or '').strip()
            if not name:
                metric_failed += 1
                print('  [指标跳过] metric_name 为空')
                continue

            dimension_ids = []
            for dim_name in row.get('dimension_names') or []:
                dim_name = (dim_name or '').strip()
                if dim_name in existing:
                    dimension_ids.append(existing[dim_name])
                elif args.dry_run and dim_name in draft_dim_names:
                    dimension_ids.append(-1)  # dry-run 占位，仅用于打印计数
                else:
                    print(f'  [警告] 指标 {name} 引用的维度不可用（不存在/创建失败/未在 dimensions.jsonl）: {dim_name}')

            dependencies = []
            for dep in row.get('dependencies') or []:
                dep_name = (dep.get('depends_on_metric_name') or '').strip()
                if dep_name:
                    dependencies.append(MetricDependencyInfo(
                        depends_on_metric_name=dep_name,
                        expression_hint=dep.get('expression_hint'),
                    ))

            aggregation = (row.get('aggregation') or '').strip().lower() or None
            if aggregation and aggregation not in AGGREGATIONS:
                print(f'  [警告] 指标 {name} aggregation={aggregation} 不在 {AGGREGATIONS}，原样保存')
            metric_type = (row.get('metric_type') or 'atomic').strip().lower()
            additivity = (row.get('additivity') or 'additive').strip().lower()

            info = MetricInfo(
                metric_name=name,
                description=row.get('description'),
                business_domain=row.get('business_domain'),
                specific_ds=True,
                datasource_ids=[args.ds],
                # ========= 【改造标记 METRIC-CENTER】↓ 问题2方案A：表所属数据源（行内可覆盖，默认本次 --ds） =========
                source_ds_id=row.get('source_ds_id') or args.ds,
                # ========= 【改造标记 METRIC-CENTER】↑ 落库开始 =========
                source_table=row.get('source_table'),
                source_column=row.get('source_column'),
                aggregation=aggregation,
                filter_rule=row.get('filter_rule'),
                time_field=row.get('time_field'),
                metric_type=metric_type,
                unit=row.get('unit'),
                normal_range=row.get('normal_range') or None,
                additivity=additivity,
                aliases=[a for a in (row.get('aliases') or []) if a],
                dimension_ids=dimension_ids,
                dependencies=dependencies,
            )
            if args.dry_run:
                print(f'  [dry-run] 将导入指标: {name}（维度 {len(dimension_ids)} 个，'
                      f'依赖 {len(dependencies)} 个）')
                metric_ok += 1
                continue
            try:
                create_metric(session, info, oid, trans, skip_embedding=args.no_embedding)
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if 'exists_in_db' in msg or '已存在' in msg or 'already exist' in msg:
                    metric_skipped += 1
                    print(f'  [指标已存在] {name}，跳过')
                else:
                    metric_failed += 1
                    print(f'  [指标失败] {name}: {msg}')
            else:
                metric_ok += 1

        print(f'[指标] 导入 {metric_ok}，已存在跳过 {metric_skipped}，失败 {metric_failed}')

        if args.dry_run:
            print('[dry-run] 未写入数据库')
            return 0

        # 3) 依赖关系二次同步：保证导入顺序不影响 derived→原子 的关联（幂等，只补缺失）
        dep_linked = _sync_dependencies(session, metric_rows, oid)
        if dep_linked:
            print(f'[依赖] 补充依赖关系 {dep_linked} 条')

        if not args.no_embedding:
            executor.shutdown(wait=True)
            print('[embedding] 已等待补 embedding 线程结束（EMBEDDING_ENABLED=False 时自动跳过）')
        return 0
    finally:
        session.close()


def _sync_dependencies(session, metric_rows: list[dict], oid: int) -> int:
    """按指标名解析依赖并补 metric_dependency（缺什么补什么，已存在不动）。"""
    from sqlalchemy import select

    from apps.metric.models.metric_model import MetricDefinition, MetricDependency

    def _id_by_name(name: str):
        return session.execute(
            select(MetricDefinition.id).where(
                MetricDefinition.metric_name == name.strip(),
                MetricDefinition.oid == oid,
            )
        ).scalar()

    linked = 0
    for row in metric_rows:
        deps = row.get('dependencies') or []
        if not deps:
            continue
        name = (row.get('metric_name') or '').strip()
        if not name:
            continue
        derived_id = _id_by_name(name)
        if not derived_id:
            continue
        for dep in deps:
            dep_name = (dep.get('depends_on_metric_name') or '').strip()
            if not dep_name:
                continue
            dep_id = _id_by_name(dep_name)
            if not dep_id:
                print(f'  [警告] 依赖指标不存在: {name} -> {dep_name}')
                continue
            exists = session.query(MetricDependency).filter(
                MetricDependency.derived_metric_id == derived_id,
                MetricDependency.depends_on_metric_id == dep_id,
            ).count()
            if exists:
                continue
            session.add(MetricDependency(
                derived_metric_id=derived_id,
                depends_on_metric_id=dep_id,
                expression_hint=dep.get('expression_hint'),
            ))
            linked += 1
    session.commit()
    return linked


# ---------- apply-comments ----------

def cmd_apply_comments(args) -> int:
    from sqlmodel import Session

    from apps.datasource.models.datasource import CoreField, CoreTable
    from common.core.db import engine

    in_dir = Path(args.in_) / f'ds{args.ds}'
    rows = _read_jsonl(in_dir / 'comments.jsonl')
    if not rows:
        print(f'[错误] {in_dir} 下没有 comments.jsonl')
        return 1

    session = Session(engine)
    filled = skipped = missing = 0
    try:
        for row in rows:
            table_name = row.get('table')
            comment = (row.get('custom_comment') or '').strip()
            if not table_name or not comment:
                skipped += 1
                continue
            table = session.query(CoreTable).filter(
                CoreTable.ds_id == args.ds, CoreTable.table_name == table_name).first()
            if table is None:
                missing += 1
                print(f'  [缺失] 表不存在于 core_table: {table_name}')
                continue
            if row.get('column'):
                field = session.query(CoreField).filter(
                    CoreField.table_id == table.id,
                    CoreField.field_name == row['column']).first()
                if field is None:
                    missing += 1
                    print(f'  [缺失] 字段不存在: {table_name}.{row["column"]}')
                    continue
                target, kind = field, f'{table_name}.{row["column"]}'
            else:
                target, kind = table, table_name

            if target.custom_comment and not args.overwrite:
                skipped += 1
                continue
            target.custom_comment = comment
            filled += 1
            print(f'  [写入] {kind}')
        session.commit()
        print(f'[完成] 写入 {filled}，已有跳过 {skipped}，缺失 {missing}')
        if filled:
            print('[提示] custom_comment 会进入既有问数链路的 DDL 描述（人工治理动作，'
                  '与 METRIC_CENTER_ENABLED 开关无关）；如需重建表向量可触发表 embedding 任务')
        return 0
    finally:
        session.close()


# ---------- main ----------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='metric_governance',
        description='指标中心 Phase 1 元数据治理辅助脚本（LLM 生成候选 + 人工确认导入）',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    def add_common(p):
        p.add_argument('--ds', type=int, required=True, help='数据源 id')
        p.add_argument('--in', dest='in_', default='governance_out',
                       help='草稿目录（默认 governance_out）')
        p.add_argument('--oid', type=int, default=1, help='工作空间 id（默认 1）')

    gen = sub.add_parser('gen', help='LLM 生成候选草稿')
    add_common(gen)
    gen.add_argument('--tables', default='', help='仅处理这些表（逗号分隔，默认全部已勾选表）')
    gen.add_argument('--part', choices=['all', 'metrics', 'docs'], default='all',
                     help='all=全部候选；metrics=只生成指标/维度；docs=只生成描述/语义文档')
    gen.add_argument('--out', default='governance_out', help='输出目录（默认 governance_out）')
    gen.add_argument('--force', action='store_true', help='覆盖已存在的草稿文件')
    gen.add_argument('--model-id', type=int, default=None, help='指定 ai_model.id（默认用系统默认模型）')
    gen.add_argument('--api-base-url', default=None, help='显式指定 LLM 地址（绕过系统默认模型）')
    gen.add_argument('--api-key', default=None)
    gen.add_argument('--model-name', default=None)
    gen.add_argument('--model-type', default='openai', choices=['openai', 'vllm', 'azure', 'tongyi'])
    gen.set_defaults(func=cmd_gen)

    apply = sub.add_parser('apply', help='导入指标/维度候选（需先人工确认）')
    add_common(apply)
    apply.add_argument('--dry-run', action='store_true', help='只校验与打印，不写库')
    apply.add_argument('--no-embedding', action='store_true', help='导入后不补 embedding')
    apply.set_defaults(func=cmd_apply)

    comments = sub.add_parser('apply-comments', help='导入表/字段业务描述候选（需先人工确认）')
    add_common(comments)
    comments.add_argument('--overwrite', action='store_true', help='覆盖已有 custom_comment')
    comments.set_defaults(func=cmd_apply_comments)

    return parser


def main() -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)  # LLM 调用慢，进度即时可见
    args = _build_parser().parse_args()
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
# ========= 【改造标记 METRIC-CENTER】↑ 治理脚本结束 =========
