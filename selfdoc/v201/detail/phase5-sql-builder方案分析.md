# Phase 5 SQL Builder（DSL → SQL 确定性编译）+ 阻断级校验 方案分析

> 权威规格：`v201改造方案_v1.2.md` 第四节 Phase 5 章节与第九节（终态逐步骤）。
> 拍板记录：2026-10-26 用户对 5 个拍板点全部按建议拍板（见第 10 节）。

## 1. 一句话定位

把「让 LLM 猜 SQL」的一部分变成「**系统编译 SQL**」：单表聚合主干的 Query Plan 由 sqlglot 确定性编译成 SQL，复杂查询永久回退 LLM 轨道（双轨，G2）。

## 2. 为什么需要

- LLM 直出 SQL 的正确率天花板受生成随机性限制（D1 走查实测：同题两跑 SQL 文本存在方差）；
- 指标口径、维度落点、时间过滤这类**确定性知识**不应由 LLM 每次重新猜——指标中心（Phase 1）已把这些知识结构化，编译器直接消费；
- 阻断级校验（enforce）必须绑在确定性轨道上才可靠（LLM 轨道恒告警，G4/G2）。

## 3. 链路位置（核心事实，2026-10-26 代码探查）

```text
build_query_plan（Phase 4，op16）
        ↓ plan
【Phase 5 新增】分流判定 + 编译（sql_builder.py，op17 日志）
   ├─ 成功 → 构造「合成 answer JSON」→ 替换 full_sql_text → 跳过 generate_sql
   └─ 任一条件不满足/编译异常 → 记 op17（route=llm_fallback + reason）→ 原 generate_sql（LLM 永久轨）
        ↓
既有 check_sql / 表名白名单 / 3-A / 行权限 / 执行 / 3-B / 图表（整链零改动复用）
```

**三个决定实现形态的关键事实**（代码实测）：

1. `check_sql`（`llm.py:1367`）、`get_chart_type_from_sql_answer`（`llm.py:1400`）、`get_brief_from_sql_answer`（`llm.py:1420`）全部解析 **LLM answer JSON**（`{'success','sql','tables','chart-type','brief'}`）→ DSL 编译产物**构造成合成 answer** 注入即整链零改动；
2. `check_metric_rule_violations`（`common/utils/metric_validator.py:181`）**已返回 `violations` 清单** → 阻断级只需在调用点消费；
3. `operate` 列无 CHECK 约束（op14/15/16 先例）→ 新 op `'17'` 无需 DDL 迁移。

## 4. DSL 形态（不另造语法）

**DSL = QueryPlan 既有业务级结构的子集** `{metrics, dimensions, filters, time_range, calculation}`（Phase 4 schema 已一次到位）。sqlglot AST 只存在于 Compiler 内部，不对上暴露。

## 5. 分流判定（✅ 全部满足才编译，否则回退 + reason 码）

| # | 条件 | reason 码 |
| -- | ---- | ---- |
| 1 | `QUERY_PLAN_ENABLED` ∧ `DSL_COMPILE_ENABLED`（开关关 = 零开销早退、不记 op17） | （早退） |
| 2 | plan 非 None | `no_plan` |
| 3 | `query_type ∈ {aggregate, detail, trend}` 且 `calculation.type='none'`（compare/rank/yoy/qoq/share 属 Phase 6 或无结构字段） | `scope` |
| 4 | 全部 metrics 命中 `metric_definition`（当前 ds 作用域、status 非 disabled）且 `metric_type ∈ {NULL, 'atomic'}`（derived/composite 回退）且 **同一 `source_table` 非空** 且 `source_column/aggregation` 可用 | `metric_resolve` / `not_atomic` / `multi_table` |
| 5 | 全部 dimensions 解析：`dimension_name/aliases` → `column_name`，`source_table` 同表或空；每个 (metric, dimension) 过 `metric_dimension_relation(enabled=True)`；**trend 特例**：`plan.dimensions` 为空或纯时间词（月份/月度/年月/统计日期/date/month/year 等）→ 按 `metric.time_field` 月分组；trend 携带非时间维度 → 回退 | `dimension_resolve` / `relation` / `scope` |
| 6 | `query_type=detail` 必须 ≥1 维度（SELECT 裸列）；`query_type=trend` 必须 `time_field` 非空 | `scope` / `no_time_field` |
| 7 | 全部 filters：`field` 经「真实列名（core_field 表）∪ 维度名/别名」解析到列；`operator` 归一入白名单（`= != in not in > < >= <= like between` 含中文别名）；`logic` 非纯 and（出现 or）→ 回退；值序列化为参数安全的字面量（标量带引号，列表展开） | `filter_resolve` / `operator` / `scope` |
| 8 | `time_range` 非空（案2 省略时间的题不编译，防全表扫） | `no_time_range` |
| 9 | `ds.type` ∈ 方言白名单：首期 `mysql` / `postgresql`（月分组：MySQL `SUBSTRING(col,1,7)`；PG `SUBSTRING(CAST(col AS text),1,7)`） | `dialect` |
| 10 | 编译产物自检：sqlglot 解析通过 ∧ `extract_tables_from_sql` 结果 ⊆ `table_name_list` | `self_check` |

- **any 异常 → 整包 try/except 兜底 → `llm_fallback(reason=internal_error)` → 原流程**（G2，编译器自身故障绝不影响问数）；
- **aggregation 仲裁（G3）**：`plan.MetricRef.aggregation` 与 `metric_definition.aggregation` 不一致 → 以固化口径为准编译 + op17 日志记差异（不回退）；
- **术语库边界**：术语库为纯文本词（word/description/embedding），无业务名→列结构映射，首期**不作** filter 解析源（G3「字段别名入口=术语库」的结构化落地列为后续演进）。

## 6. 编译产物与合成 answer

编译 SQL 形态（单表）：

```sql
SELECT <agg>(<source_column>) [AS <metric_name>], <dim_cols...] | <裸列（detail）>
FROM <source_table>
WHERE <time_field> >= '<start>' AND <time_field> <= '<end>' [AND <filters...>] [AND <metric.filter_rule?>=不编译，仅告警轨道]
[GROUP BY <dim_cols...>]        -- aggregate；trend=GROUP BY 月表达式 ORDER BY 月表达式
[LIMIT <row_limit>]             -- 服务端 enable_sql_row_limit 时取 1000，与 LLM 轨道同源
```

- `metric.filter_rule`（口径强制过滤）**首期不编译进 SQL**（Text 自由格式解析不可靠），交 3-A 告警轨道观测，列为已知边界；
- 合成 answer：`{'success': True, 'sql': <编译SQL>, 'tables': [<source_table>], 'chart-type': <规则映射>}`——**不含 brief**，会话标题走既有 `question[:20]` fallback；
- **chart-type 规则映射**（拍板点 3）：`detail→table`、`trend→line`、`aggregate 有维度→bar`、`aggregate 单值→table`；
- SSE 契约：DSL 分支 yield 一次 `sql-result`（content=合成 answer 文本）+ 一次 `info: sql generated`，与 LLM 轨道消息序列一致，前端零改动。

## 7. 阻断级校验（enforce 消费点）

`llm.py` 3-A 调用点（现 L1723）改为：

```python
violations = check_metric_rule_violations(...)
# DSL 轨道 ∧ METRIC_RULE_ENFORCE=True ∧ 违规非空 → 阻断（plan 强绑定，v1.2 Phase 5 条目）
if violations and settings.METRIC_RULE_ENFORCE and self._dsl_compiled:
    raise SingleMessageError(...)
```

- LLM 轨道不改：违规照旧只写告警日志（G2「对 LLM 轨道恒为告警」）；
- `METRIC_RULE_ENFORCE` 默认 False（仅声明），验收时临时开实测一次阻断后回 False（拍板点 4）。

## 8. 日志与执行详情

- `OperationEnum.DSL_COMPILE = '17'`（无需迁移）；
- **DSL 开关开即记一条** op17（含 `no_plan`，观测完整；开关关零开销无日志）：
  `end_message = {'route': 'dsl'|'llm_fallback', 'reason': <码>, 'metric'/dimensions/table 摘要, 'sql'?（成功时）, 'agg_mismatch'?（G3 仲裁差异）}`；
- 前端执行详情：op `'17'` 分发 + 四语言 i18n 标题 + 展示组件（吸取问题 10 教训，同步交付）。

## 9. 改动清单（G1 薄插桩）与验收

| 文件 | 改动 | 量级 |
| ---- | ---- | ---- |
| `common/core/config.py` | `DSL_COMPILE_ENABLED: bool = False` | ~2 行 |
| `apps/chat/models/chat_model.py` | `OperationEnum.DSL_COMPILE = '17'` | ~3 行 |
| **`apps/chat/task/sql_builder.py`（新建）** | 分流判定 + 解析 + sqlglot 编译 + 合成 answer + op17 日志（实现落独立模块） | ~250 行 |
| `apps/chat/task/llm.py` | 分流插桩（替换 full_sql_text 来源，~20 行）+ 3-A enforce 消费（~3 行） | ~25 行 |
| 前端执行详情 | op17 分发 + i18n ×4 + 组件 + build | 新组件 |
| `metric_validator` / `query_plan` schema / SSE 契约 | **不改** | 0 |

**验收（走查制；「正确率 ≥ LLM 轨道」统计线移交 Phase 0）**：
E1 单表聚合题走 DSL（op17 route=dsl、SQL 正确、图表正常、省一次 LLM）；
E2 复杂题（多表 join/窗口/compare/share）全部正确回退且结果不劣于现状；
E3 `METRIC_RULE_ENFORCE=True` 临时实测「违规 → 阻断」，LLM 轨道同规则仍告警；验后回 False；
E4 全开关关 = 原版零差异；
E5 执行详情 op17 步骤四语言显示正常。

**冒烟（助手执行）**：sql_builder 用例 ≥10（aggregate/detail/trend 编译正确 + compare/calc≠none/多表/derived/无时间/非法 operator/异方言/无 plan 全部正确回退 + 合成 answer 过 check_sql）+ ruff + import 回归。

## 10. 待拍板 → 已拍板（2026-10-26，5 点全按建议）

1. **首期编译范围**：仅 `aggregate/detail/trend + calculation=none + 单表 + atomic`，其余回退 → **✅ 按建议**；
2. **方言白名单**：首期 mysql + postgresql，其他数据源回退 → **✅ 按建议**；
3. **chart-type 规则映射**：detail→table、trend→line、aggregate 有维度→bar、单值→table → **✅ 按建议**；
4. **阻断级验收**：代码完整实现 enforce，走查时临时开实测一次再回 False → **✅ 按建议**；
5. **aggregation 仲裁**：以 `metric_definition` 固化口径为准 + op17 记差异 → **✅ 按建议**。

## 11. 实施执行记录（分步执行，逐条随记）

（待实施时逐 Step 回填）
