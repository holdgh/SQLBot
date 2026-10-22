# Phase 4 Query Plan 语义解析层 方案分析

> 创建时间：2026-10-20｜定位：实施前方案（用户批准起草，**先审后动**）。
> 配套：权威规格《v201改造方案_v1.2.md》第四节 Phase 4 章节；全局规则 G1~G5（同文档第三节）。
> 状态：**待审阅**（审阅通过 = 动手许可）。

---

## 1. 一句话定位

在 SQL 生成之前插一步"理解快照"：让 LLM 先把问题解析成结构化 **Query Plan**（查什么指标/什么维度/怎么算/有多确定），**本期只解析、只校验、只展示，不参与 SQL 生成**——最终 SQL 与结果与基线完全一致。

## 2. 为什么需要

- **LLM 任务过重、错了无法归因**：现状一步完成"理解 + 写 SQL"，答错了分不清是"理解错"还是"SQL 写错"。plan 把"理解"显式化——先可验证理解，Phase 5（编译）/Phase 6（计算）才有输入。
- **计算意图没地方放**：同比/环比/占比/排名的算法意图目前只能揉进 SQL 提示词赌 LLM 写对；plan 的 `calculation` 字段给它正式落点（**结构先行、执行后置**）。
- **可观测**（G4）：执行详情页直接看到"系统怎么理解这个问题"，理解错误当场可见。

## 3. 链路位置（本期为纯旁路）

```
[指标/术语召回] ──→ [4 QUERY PLAN]（开关开：解析+校验+展示，旁路） ──→ generate_sql → check_sql → 执行 → …
                                                  └─ SQL 路径零改动（plan 失败同样零影响）
```

- **插桩点唯一**：`llm.py` 中 `generate_sql` 调用处（`run_task` 内）**之前**——该调用点全仓仅 1 处；
- **开关**：`QUERY_PLAN_ENABLED` 默认 False = 不调用、不建日志、提示词无变化（零额外 LLM 开销）。

## 4. Plan JSON Schema 详细设计（v1.2 预设的详设项）

落地：`backend/apps/chat/schemas/query_plan.py`（pydantic v2，strict）。

### 4.1 字段枚举表

| 字段 | 类型 | 必选 | 取值/校验 | 说明 |
|---|---| :-: |---|---|
| `query_type` | enum | ✓ | `aggregate` / `detail` / `trend` / `rank` / `compare` | 枚举值待拍板（决策点③） |
| `metrics` | list[{`metric_name` 必填, `aggregation` 可选}] | ✓ ≥1 | `metric_name` 非空字符串 | 可来自召回候选，也可 LLM 依据问题补充 |
| `dimensions` | list[str] | | 维度名 | 与 `metric_dimension_relation` 的合法性校验属 Phase 5，本期不校验 |
| `filters` | list[{`field`,`operator`,`value`,`logic`}] | | 业务级描述 | DSL 形态约束：业务级，**不落 SQL 片段**（v1.2） |
| `time_range` | {`current`:{start,end}, `previous`:{start,end}} | 可空（**2026-10-22 案2 拍板修正**，原标 ✓ current） | ISO 日期 | `previous` 由同比/环比类 calculation 决定有无；时间无法从问题确定（5.2 歧义触发条件）时 LLM 可省略 → `None`，前端条件渲染 |
| `calculation` | {`type`, `expr`} | ✓ | `type` ∈ `none/yoy/qoq/share/growth/rank`；`expr` 可选（如 share 分母表达式） | 决定子查询拓扑（Phase 6 消费） |
| `sub_queries` | list[同构 Plan 节点] | | 每节点含 `datasource_id: Optional[int]` | `datasource_id` **仅 schema 预留**（G5）：本期不读取、不校验 |
| `confidence` | {`metric_confidence`: 0~1, `signals`:{`llm_self`,`recall_gap`,`hit_factor`}} | ✓ | 越界 clamp 到 [0,1] | signals 明细落日志，供 Phase 0 调参 |
| `ambiguity` | {`need_clarification`: bool, `reason`: str} | ✓ | `true` 时 `reason` 必填非空 | 本期仅标记 |

### 4.2 校验与失败口径

- **pydantic strict**：`extra='forbid'`、枚举外值/类型不符即校验失败；
- **失败 = 回退照常**：记一条 plan 失败日志（原因 + LLM 原文截断），`generate_sql` 照走——plan 永不阻断问数（兼容性总则）；
- LLM 输出抽取复用现成先例：`extract_nested_json` + `orjson.loads` + 失败抛错捕获（`select_datasource` 同款模式）。

### 4.3 示例（同比 + 低置信）

```json
{"query_type":"aggregate","metrics":[{"metric_name":"游客量","aggregation":"sum"}],
 "dimensions":["景区所属行政区域"],"filters":[],
 "time_range":{"current":{"start":"2026-01-01","end":"2026-01-31"},
               "previous":{"start":"2025-01-01","end":"2025-01-31"}},
 "calculation":{"type":"yoy"},"sub_queries":[],
 "confidence":{"metric_confidence":0.58,"signals":{"llm_self":0.7,"recall_gap":0.3,"hit_factor":1.0}},
 "ambiguity":{"need_clarification":false,"reason":""}}
```

## 5. 置信度与歧义

### 5.1 混合信号（v1.2 修订 #4 落地式）

```
metric_confidence = clamp01( 0.60×llm_self + 0.25×recall_gap + 0.15×hit_factor )
```

- `llm_self`：LLM 自报分（提示词要求输出 0~1）；
- `recall_gap`：指标召回 top1 与 top2 相关度之差（同量纲归一；仅 1 个候选或并列 → 0）；
- `hit_factor`：召回锚是否存在——命中 ≥1 = 1.0，零命中 = 0.6（无召回锚 = 纯 LLM 推断，打折）；
- 权重与阈值均为**初值**，Phase 0 评测调参（v1.2 已定）；简单加权和，不搞乘积/归一化数学体操（复杂度匹配）。

**⚠ 决策点①（recall_gap 的数据缺口）**：现状召回链路**分数不透出**——`select_metric_by_question` 两路（BM25/pgvector）合并时只保留序位、分数即被丢弃。两案：

| 案 | 做法 | 代价 |
|---|---|---|
| **A（推荐）** | 两路分数各自归一后**附着**到候选（**排序合并逻辑一字不动**，零行为风险），plan 侧取 top1/top2 差 | 动 Phase 1 召回函数少量代码（只加字段不改序；实施时核实 `bm25_retrieve`/pgvector SQL 是否已带分，无则补列） |
| **B** | 砍掉 `recall_gap` 项，公式改 `0.70×llm_self + 0.30×hit_factor` | 零改 Phase 1 代码，但"不单信 LLM 自报"少一路真信号 |

### 5.2 歧义标记（本期=单步状态机）

- 状态仅两枚：`none` → `flagged`（`reason` 必填）；无后续状态——**澄清交互单独立项不在本期**（v1.2 明示）；
- 触发（提示词规则）：多义词（同词可指不同业务对象）、时间范围无法默认（"最近"无默认策略）、指标多候选且语义分歧；
- 本期行为：**仅标记 + 展示**，不触发追问、不改回答、不做触发条件配置化（G5 简单先行）。

### 5.3 低置信提示（本期唯一"结果侧"输出）

- 触发：`metric_confidence < QUERY_PLAN_LOW_CONFIDENCE_THRESHOLD`（默认 0.6，可配）；
- 文案："存在多个可能理解：已按 <当前理解> 处理，如需 <备选> 请追问"（有备选信息则具体化，否则泛化）。

**⚠ 决策点②（载体）**：

| 案 | 做法 | 代价 |
|---|---|---|
| a | 执行详情页 [PLAN] 步骤内展示 | 零契约变化，但结果页看不到（弱于规格"结果附注"） |
| **b（倾向）** | 结果区独立提示条（SSE 追加提示消息） | 最贴规格；需确认/扩展 SSE 消息类型与前端渲染 |
| c | 追加进最终回答文本 | 最省，但污染正文 |

## 6. 实施设计

| 项 | 方案 |
|---|---|
| schema | `apps/chat/schemas/query_plan.py`（pydantic v2 strict） |
| 生成模块 | `apps/chat/task/query_plan.py`（G1 独立模块：提示词、解析、校验、置信度计算、日志封装；与 Phase 5 的 `sql_builder.py` 同目录同模式） |
| 薄插桩 | `llm.py` `generate_sql` 调用处之前：**开关判断 + try/except + 一行调用**（照 3-A 插桩先例；llm.py 新增行仅为调用与开关） |
| 输入 | 问题、`self._metric_candidates`（Phase 1 召回结果）、当前 ds 上下文——**全部已有，不新增召回**；提示词注入当前日期（供 LLM 算时间窗） |
| LLM 调用 | 复用现有链路 LLM 客户端与 `select_datasource` 的 JSON 抽取/失败回退先例 |
| 后端日志 | `OperationEnum.QUERY_PLAN = '16'`——operate 列**非原生 Enum 无 CHECK 约束，无需 DDL 迁移**（`FILTER_METRICS='15'` 注释明示先例）；`start_log/end_log` 模式照 `filter_metric_template`；plan JSON + signals 落步骤日志 |
| 前端 | `ExecutionDetails.vue` 增 `operate_key === 'QUERY_PLAN'` 分支 → 新组件 `LogPlan.vue`（关键字段表格化展示，结构照 `LogMetric` 先例）；步骤标题四语言 i18n |
| 开关 | `config.py` TRUST-VALIDATE 同块新增 `QUERY_PLAN_ENABLED=False`、`QUERY_PLAN_LOW_CONFIDENCE_THRESHOLD=0.6` |

## 7. 边界（本期明确不做）

1. **不改 SQL 生成路径**：plan 纯旁路，开关开/关下 SQL 与结果完全一致（v1.2 硬验收）；
2. **不接 compile**：`DSL_COMPILE_ENABLED` 与 `sql_builder` 属 Phase 5（全仓零命中已核实），编译分流不在本期；
3. **多轮澄清交互不做**（单独立项）；
4. **`datasource_id` 仅预留**：不读取，跨源执行不做（G5）；
5. **`sub_queries` 执行不做**（Phase 6 计算引擎）；
6. plan 任何异常吞掉记日志，主流程照走（失败回退不阻断）。

## 8. 验收标准

**技术验证**：
1. ruff + import 冒烟；
2. **开关关**：不建 plan 日志、提示词无变化、SQL/结果与开关前逐字一致（A3 式对照）；
3. **开关开**：正常问数出现 [PLAN] 步骤（JSON 完整、校验通过）；注入非法 LLM 输出 → 仅 plan 失败日志、主流程不受影响；
4. 默认值代码核实 `QUERY_PLAN_ENABLED=False`。

**用户走查（D1~D4）**：
- **D1 解析正确率**：同比/环比/排名/趋势各若干题 → 详情页 plan 字段正确（v1.2 验收线 ≥85%）；
- **D2 歧义用例**：多义词题 → `ambiguity` 标记出现且 `reason` 可读；
- **D3 低置信提示**：阈值内触发、文案正确（载体按决策点②）；
- **D4 零差异**：同题开关 A/B 对照 → 最终 SQL/结果/图表完全一致。

## 9. 工作量

规格估 **1~1.5 周**（schema + 提示词 + 校验 + 混合信号 + 详情页步骤 + 走查）。

## 10. 待拍板与下一步

1. **决策点①**：`recall_gap` 数据缺口——**A 分数透出（推荐）** / B 砍分差项； ✅ 拍板 **A**（2026-10-21）
2. **决策点②**：低置信提示载体——a / **b（倾向）** / c； ✅ 拍板 **b**（2026-10-21）
3. **决策点③**：`query_type` 枚举值（`aggregate/detail/trend/rank/compare`）确认； ✅ 拍板**暂用所列枚举**（2026-10-21）
4. 全部拍板 + 文档审阅通过 → 出文件级实施清单 → 动手。
5. **time_range 必填性**（2026-10-22 实施中发现规格内生矛盾：4.1 current 必填 vs 5.2 歧义触发「时间无法从问题确定」）→ ✅ 拍板**案2：schema 放宽 `time_range: TimeRange | None = None`**（歧义题合法省略，提示词禁空对象；4.1 表已同步改标）。

---

## 11. 实施执行记录（分步执行，逐条随记）

> 拍板时间 2026-10-21（方案审阅通过 = 动手许可）。

- **Step 1 ✅（2026-10-21）schema 文件**：新建 `apps/chat/schemas/query_plan.py` + `__init__.py`（schemas 目录为新建）。9 类模型按 4.1 表全量落地：`extra='forbid'` strict、`QueryType`/`CalculationType` 字面量枚举（决策③）、confidence/signals 越界 clamp [0,1]（`metric_confidence` 1.7→1.0 实测）、sub_queries 递归同构（`model_rebuild`）。import + `model_validate` 冒烟通过。
- **Step 2 ✅（2026-10-21）召回分数透出（决策①A）**，6 处编辑：
  - `keyword_retrieval.py`：新增 `bm25_retrieve_with_scores`（原 `bm25_retrieve` 改为其薄封装，行为等价，其余调用方零影响）；
  - `metric.py`：`_score_map` 容器（合并逻辑 `_ordered` 一字不动）→ BM25 路收集原始分**路内 min-max 归一**附着 → pgvector 路取 SQL 已返回的 `similarity`（clamp [0,1]，两路同 id 取 max）→ 候选 dict 加 `recall_score` → `get_metric_template` 的提示词 XML **剥离 `recall_score`（提示词零变化）**；
  - 已核实：`llm_filter_context`/schema 短路/validator 对候选均**逐字段取值**，加字段不泄漏进其他提示词；日志 `full_message` 会多显示该键（展示性，非破坏，走查时看 LogMetric 渲染）；
  - 验证：ruff 新文件+keyword_retrieval **All checks passed**（metric.py 全量 34 错均为存量风格问题，本次改动行 0 新增）；冒烟实测 **count=7、recall_score 归一递减（1.0/0.755/0.505/0.341）** ✓（注意：库内 8 指标全部 `specific_ds=True`，须带 `datasource` 调用才有召回——首轮冒烟 count=0 系测试传参所致，非代码问题）。
- **Step 3 ✅（2026-10-22）生成模块**：新建 `apps/chat/task/query_plan.py`。模块内全包（G1/3-A）：开关判断（关=直接返回 None 零行为）、`start_log`/`end_log` 步骤日志（operate=QUERY_PLAN，finally 统一写 `{'status':'ok'|'failed'}`）、`_collect_stream` **内联实现**（`process_stream`/`get_token_usage` 在 llm.py 内不可 import——避免循环依赖；简收 content/reasoning + `chunk.usage_metadata` 累加）、`extract_nested_json`+orjson 解析、`QueryPlan.model_validate` strict 校验、`_calc_confidence` 混合信号（0.60×llm_self + 0.25×recall_gap + 0.15×hit_factor，clamp；实测 0.78/无命中 0.57）、异常分 `ValidationError`/`Exception` 分类捕获 → 记日志返回 None 永不抛出、`is_low_confidence` 读 `QUERY_PLAN_LOW_CONFIDENCE_THRESHOLD`。候选进提示词前剥 `recall_score`（LLM 不可见）。**过程中修两处写入缺陷**：① `signals.model_copy` 括号错配（`_calc_confidence` 返回 dict 非模型，改 `ConfidenceSignals(**signal_vals)` 构造）；② `ConfidenceSignals` 漏导入、`AIPromptMessage` 未用 → 已修。
- **Step 4 ✅（2026-10-22）config 开关**：`common/core/config.py` TRUST-VALIDATE 块后加 `QUERY_PLAN_ENABLED: bool = False`（**默认关，硬验收前提**）、`QUERY_PLAN_LOW_CONFIDENCE_THRESHOLD: float = 0.6`；`lowercase_bool` field_validator 列表加 `'QUERY_PLAN_ENABLED'`。冒烟断言默认值 False ✓。
- **Step 5 ✅（2026-10-22）操作类型枚举**：`chat_model.py` `OperationEnum.QUERY_PLAN = '16'`（带 QUERY-PLAN 改造标记注释；operate 列非原生 Enum，无 DDL）。冒烟取值 ✓。
- **Step 6 ✅（2026-10-22）llm.py 薄插桩**：顶部 TRUST-VALIDATE 导入块后加 `from apps.chat.task.query_plan import build_query_plan`（query_plan 不反向 import llm，无循环）；run_task 内 `sql_res = self.generate_sql(_session)` 调用行**之前**一行 `self.query_plan = build_query_plan(self, _session)`（异常兜底全在模块内，llm.py 零 try/except，照 3-A 形态）。验证：ruff 两新文件 **All checks passed**；冒烟经 `import main` 生产顺序全链通过（直接 import query_plan 会触发仓库存量 `datasource↔xpack↔permission` 循环链——**存量问题非本次引入**，llm.py 生产中亦经 main 初始化加载，行为一致）：llm 模块含 build_query_plan ✓、schema 拷贝改写 plan.confidence 实测 ✓、默认关断言 ✓。
- **Step 7 ✅（2026-10-22）前端 LogPlan**：
  - 新建 `frontend/src/views/chat/execution-component/LogPlan.vue`（结构照 `LogMetric`：BaseContent 底 + 标题/值行式布局）：读 `item.message` 中 `type==='ai'` 条目的 content（**兼容 JSON 字符串与 dict 双形态**，后端存的是 JSON 字符串），渲染 query_type（枚举 i18n）、metrics（名+聚合）、dimensions、filters（字段/运算符/值/逻辑）、time_range（当期/对比期）、calculation（type≠none 或有 expr 才显示）、confidence（百分比 + signals 三分量）、ambiguity（need_clarification 时橙框高亮 reason）；`status==='failed'` 显示失败文案（不影响主流程）；
  - `ExecutionDetails.vue`：import LogPlan + `ele.operate_key === 'QUERY_PLAN'` 分支（排在 LogWithAi 兜底之前）；步骤标题走既有机制 `t('chat.log.' + operate)`，后端 `get_log_history` 已按枚举名回传 `QUERY_PLAN`，**后端零改动**；
  - 四语言 i18n（`zh-CN/zh-TW/en/ko-KR`）：`chat.log.QUERY_PLAN` 步骤名 + `chat.plan.*` 字段标签与 `type.*`/`calc.*` 枚举文案；4 文件 `ConvertFrom-Json` 合法性全过；
  - 验证：`npx vue-tsc -b` exit 0 ✓。
- **Step 8 ✅（2026-10-22，代码+静态验证；动态实测归 Step 9）SSE 结果区低置信提示条（决策②b）**：
  - **后端**（`llm.py` 插桩块扩展）：`build_query_plan` 调用之后，`is_low_confidence(self.query_plan)` 为真时追加一行 SSE 事件 `{'type': 'query-plan-hint', 'confidence': <0~1>}`（round 4 位；开关关/plan 失败 → plan=None → 判定 False → **零事件**）；阈值不进事件，文案由前端 i18n 持有；llm.py 顶部 import 行扩为 `build_query_plan, is_low_confidence`。
  - **前端**（`ChartAnswer.vue`，问数主答案组件）：新增 `planHint` computed（取 `records[index].query_plan_hint`，与 sendMessage 同源）；sendMessage 取到 currentRecord 后**先清空**旧 hint（重问不残留）；SSE switch 新增 `case 'query-plan-hint'` 写入 record；模板在 BaseAnswer 结果容器内 ChartBlock 之上渲染橙色提示条（`chat.plan.low_confidence` 带 {0} 百分比参数）；
  - **契约**：`api/chat.ts` `ChatRecord` 加可选运行时字段 `query_plan_hint?: { confidence: number }`；
  - **i18n**：四语言加 `chat.plan.low_confidence`（置信度较低+建议核对意图/补充时间范围）；4 文件 JSON 合法性全过 ✓；
  - **验证**：ruff `llm.py` 全量 56 错**均存量**（I001 及 UP* 集中在既有 import/style 行，I001 diff 显示被重排的全是 2026-10-21 前的存量导入，非本次引入；改动行 84/1663-1666 零命中）；`npx vue-tsc -b` exit 0 ✓。
  - **边界（拍板记录）**：提示条为**会话内实时**——ChatRecord 无空闲字段、持久化需 DDL 加列，超出决策②b「SSE 追加提示消息」范围，本期不做；刷新后不保留，但 plan 明细（含 confidence/signals）永久在执行详情 [PLAN] 步骤可查。
- **Step 9 ✅（2026-10-22）技术验证收口（脚本级 + 静态论证；页面走查 D1~D4 留用户）**：
  - **9-A 离线冒烟过**：① `get_metric_template` **有召回**场景（candidates=5）：候选带 `recall_score`、模板 XML **零泄漏**（补上 Step 2 遗留）；② 开关关：`build_query_plan` 早返回 None（FakeService 零属性触碰）、QUERY_PLAN 日志 0→0、`is_low_confidence(None)=False`。
  - **9-B 开关开冒烟过（真 LLM，仅进程内 env 启用，代码默认值仍 False）**：B1 plan 生成成功（query_type=aggregate、metrics=1、**time_range=None 合法省略**——案2 生效、confidence=0.660 与公式手算一致 0.6×0.8+0.25×0.118+0.15×1.0、5 候选召回锚命中）、[PLAN] 日志 status=ok 落库；B2 阈值翻转：threshold=1.01→hint=True / 0.6→False；B3 回退双路径：非 JSON 输出 → status=failed+`cannot parse plan json`、schema 非法 → status=failed+`plan schema validation failed`，**均返回 None 不抛异常**（主流程不受影响）。
  - **过程中修两缺陷 + 一拍板**：
    1. **提示词 `.format()` KeyError**：`QUERY_PLAN_SYSTEM_PROMPT` 含字面 JSON 示例大括号（`{metric_name:...}` 等），`format(today=...)` 把它们当格式化字段 → `KeyError` 被兜底吞（真 LLM 首跑才暴露）；改 `replace('{today}', ...)`，注释已说明。
    2. **案2 拍板（用户，2026-10-22）**：`time_range` 必填 vs 5.2 歧义规则「时间无法从问题确定」冲突——schema 放宽 `time_range: TimeRange | None = None`，LLM 省略整个字段合法（提示词同步加「禁止输出空对象」）；方案 4.1 表该行标注已改（原 ✓ current → 可空+拍板记录）；前端 LogPlan 本就条件渲染零改动。
    3. **补 Step 1 漏实现**：4.1「`need_clarification=true` 时 `reason` 必填非空」——`Ambiguity` 加 `model_validator`，冒烟 4 态（省略 time_range 合法/空 reason 拒/有 reason 过/false 过）全过。
  - **零差异论证（技术验证第 2 条，静态铁证）**：`git diff` 实测 `llm.py` **9 增 0 删**，新增全部在 QUERY-PLAN 标记块内（import 2 行 + 插桩 5 行）；开关关时插桩块仅 3 行零副作用调用（9-A 证零日志）、`generate_sql`/提示词/消息构造零触碰；提示词侧另有 XML 剥离冒烟证零变化。**改造前后 SQL 生成路径逐字一致由 diff 直接保证**；开关开/关 A/B 与页面效果归用户走查 D4/D1~D3。
  - **ruff**：`query_plan.py`（task+schema 两文件）All checks passed ✓。
  - **技术验证 4 条对照**：① ruff+import 冒烟 ✓；② 开关关不建日志/提示词零变化/SQL 零差异 ✓（上述）；③ 开关开 [PLAN] 步骤+失败回退+低置信判定 ✓（9-B）；④ `QUERY_PLAN_ENABLED=False` 默认值 ✓（9-A 断言）。
- **待办（剩用户走查，非助手动作）**：D1 解析正确率（同比/环比/排名/趋势题若干，v1.2 线 ≥85%）、D2 歧义用例 reason 可读、D3 低置信提示条（阈值内触发、文案）、D4 同题开关 A/B 最终 SQL/结果/图表零差异；走查通过后进展文档 Phase 4 行转 ✅。
