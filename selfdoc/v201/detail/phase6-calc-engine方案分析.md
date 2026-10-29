# Phase 6 计算引擎（Post-Query Calculation Engine）方案分析

> 创建：2026-10-28（启动日，Phase 5 验收闭环后启动）｜状态：**✅ 拍板通过（2026-10-28，①~⑤ 全按建议）→ Step 1~6 实施完成（2026-10-29），待走查 F1~F5（验收编号沿字母序，E1~E5 已被 Phase 5 占用，2026-10-29 与进展文档统一）**
> 实施中追加拍板：**列结构 A**（2026-10-29，拍板④歧义澄清）——`<指标名>` 列列头即指标名、值=当期值，另设 同期值/变化值/变化率 三列，无冗余「指标」名字串列。
> 权威规格：`v201改造方案_v1.2.md` 第四节 Phase 6 章节（L217-228）与第九节步骤 18（L366）。
> 配套文档：进展文档（新增第六节日）、detail/phase4-query-plan方案分析.md（plan 结构来源）、detail/phase5-sql-builder方案分析.md（解析组件来源）。

## 1. 权威规格解读（v1.2 原文要点）

- **目标**：解决"怎么算"——**业务公式由程序计算，LLM 只做表达**。
- **三类分工**：类型1 数据库计算（sum/count/avg/group by）留 SQL（Phase 5 编译，不进 Python）；**类型2 业务公式（同比/环比/增长率）= 本引擎**：plan 展开 N 个子查询执行后 Python 计算；类型3 统计分析（拟合/预测/异常）不在本期。
- **改动**：`apps/chat/task/calc_engine.py`——输入 `plan.calculation` + 子查询结果，输出**合并为普通行列结构**；`save_sql_data`/图表/SSE 契约**完全不变**；纯 Python 函数库（除零保护、精度约定）。
- **挂接点**：`execute_sql` 附近，calculation 非 none 时启用；**无 plan 永不触发**。
- **开关**：`CALC_ENGINE_ENABLED` 默认 False。
- **验收**："同比增长多少"由代码算出（日志含过程）且与人工核算一致；除零/空结果确定性处理；图表正常。
- **演进注记（G5，本期不做）**：未来 Calculation Planner 按数据源能力选 SQL/Python 双后端，届时补双后端一致性回归入评测集。

## 2. 现状事实（代码探查结论）

| 事实 | 位置 |
| ---- | ---- |
| `QueryPlan.calculation = {type: none/yoy/qoq/share/growth/rank, expr?}`、`time_range.previous` 可空、`sub_queries: list[QueryPlan]`（与自身同构）已预留 | `query_plan.py:57-62,32-36,121` |
| **LLM 实际恒输出 `sub_queries: []`**，执行布局明确留 Phase 6 再设计 | phase4 方案文档 L60/L123 |
| calculation≠none 在 Phase 5 恒回退 LLM 轨（scope reason），Phase 5 不接手 | `sql_builder.py` `COMPILED_QUERY_TYPES` 与 scope 判定 |
| 执行链：check_sql → 白名单 → 3-A → 行权限 filter → check_save_sql → SSE `sql` → **`execute_sql`（EXECUTE_SQL 卡）→ 3-B → DataFormat 规整 → `save_sql_data` → SSE `sql-data` → 图表链（generate_chart LLM 选图）** | `llm.py:1745-1886` |
| 行权限：normal user 且有权限规则时 `generate_filter`（LLM 调用）改写 SQL；normal user 无规则/普通用户直通 | `llm.py:1806-1813` |
| 环话题实测（E3 对照）：plan 正常产出 calculation=qoq + time_range.current/previous，主 SQL 由 LLM 生成当期数据 | 走查记录（问题文档 16 附近） |

## 3. 总体方案（形态 1：真 Post-Query，主链零改 SQL 生成）

**核心设计——"主 SQL 照旧，引擎只补算"**：

```
[现状链路不动] LLM 生成主 SQL（当期窗）→ 校验/权限 → execute（当期数据）→ 3-B
      │
      ▼ 【新插桩点：3-B 之后、DataFormat/save 之前】
if CALC_ENGINE_ENABLED ∧ plan ∧ plan.calculation.type ∈ 支持集:
      ① 复用 Phase 5 解析组件 + plan（仅换 time_range.previous 窗）程序化组装"前期子查询 SQL"
         → 表名自检（∈ table_name_list）；解析失败/范围外 → 回退不计算（记 skip reason）
      ② execute_sql(前期子查询)（白名单同表天然满足；不另开 EXECUTE_SQL 卡，过程记 calc 卡）
      ③ Python 公式计算（yoy/qoq/growth：变化值=当期-基期，变化率=(当期-基期)/基期；除零→null）
      ④ 合并 rows：按 dimensions key 两期 full-join → 普通行列
           [{维度列…, 指标, 当期值, 同期值, 变化值, 变化率}, …]（单值题=无维度单行）
      ⑤ 替换 result['data'] → 既有 DataFormat → save_sql_data → SSE sql-data → 图表
      │
      ▼ 无论算成与否，主流程继续（G2：回退=按当期单期数据照常返回，不阻断）
```

**关键取舍（对应拍板点①）**：主 SQL 的生成路径**本期一行不改**（与 Phase 4 硬边界同款"不改 SQL 生成路径"）；Phase 5 编译范围**不动**（calculation 继续回退 LLM 轨）。Phase 6 是**结果侧增量**，不是第三条 SQL 轨道。

**公式与子查询拓扑（确定性）**：

| calculation.type | 子查询拓扑 | Python 公式 |
| ---- | ---- | ---- |
| `yoy` / `qoq` / `growth` | 2 条同构（当期窗=主 SQL 已有；前期窗=程序组装） | `变化值=当期-基期`；`变化率=(当期-基期)/基期` |
| `share` / `rank` | 分母/名次语义依赖 `expr` 自由文本，解析不确定 → **本期回退**（见拍板点②） | — |

## 4. 拍板点（建议已给出，请逐条确认）

### ① 轨道形态：形态 1「真 Post-Query」（建议 ✅）

- **建议**：主 SQL 照旧 LLM 轨执行，calc_engine 只做「补前期查询 + Python 合并」，插桩在 3-B 之后。理由：a) 贴规格字面（Post-Query、挂接 execute_sql 附近、契约完全不变）；b) 主链改动最小（单点插桩）；c) 不动 Phase 5 边界，两 Phase 职责清晰。
- 备选形态 2：calculation 题在分流点整体接管（N 子查询自执行自落库）——侵入 check_save_sql/EXECUTE_SQL/权限/3-B 全链对齐，复杂度高，不建议本期。

### ② 本期 calculation 范围：yoy/qoq/growth 做，share/rank 回退（建议 ✅）

- **建议**：`yoy/qoq/growth` 三者**同构**（两期窗拓扑，程序可确定性组装）；`share`（分母=expr 自由文本）与 `rank`（与 query_type=rank 重叠、涉排序取值语义）本期回退——保持「方案复杂度与问题复杂度匹配」。
- 回退行为=现状（LLM 主 SQL 内自算），与今天行为零差异。
- share 若你认为业务优先级高，备选：分母=同 filter 去维度合计子查询（程序可算，但 expr 语义边界需再定义）——**不建议本期**。

### ③ 三种场景回退不计算（建议 ✅，安全优先）

1. `time_range.previous` 缺失而 calculation≠none → 回退单期（记 reason=no_previous）；
2. 前期子查询组装/自检失败（解析不出指标/维度/单表范围外）→ 回退单期（reason=compile_fail）；
3. **行权限场景（normal user 且有权限规则）→ 回退单期（reason=row_permission）**——前期查询若不完整施加权限存在**数据泄露风险**；完整复施权限=对前期 SQL 再走一次 `generate_filter`（+1 LLM 调用且改写非确定），首期从简回退，演进待议。

回退一律记 calc 卡 reason，主流程照常（当期数据照常返回），不报错不阻断。

### ④ 合并 rows 形态与精度（建议 ✅）

- 行结构：`{维度列…, <指标名>, 当期值, 同期值, 变化值, 变化率}`；单值题=无维度单行；有维度=按维度 key full-join（前期缺行→前期列 null，变化列 null）。
- `变化率`为**小数数值**（0.123 形态，非"12.3%"字符串——保证图表/大数字规整链路兼容）；`基期=0` → 变化率 **null**（日志记 div_zero）；任一期无数据 → 对应值与变化列 null。
- 两期数据合并后统一过既有 `DataFormat` 两函数再 `save_sql_data`（与现状规整口径一致）。
- 图表：不做规则映射（那是 DSL 轨的），`generate_chart` 看合并 rows 自选（列宽了自然多为 table/line），验收以"图表正常"为准。

### ⑤ 执行详情 calc 卡（建议 ✅，照 3-A 校验卡同模式）

- 新 `OperationEnum.CALC_ENGINE = '19'`（operate 无 CHECK 约束，无迁移）；每道 calculation 题记一卡：type、两期时间窗、前期子查询 SQL、两期原值、公式、结果/回退 reason——**"日志含过程"验收项的落点**。
- 前端新 `LogCalc.vue`（照 LogTrust/LogDsl 范式）+ `ExecutionDetails` 分发 + i18n 四语言 `chat.calc` 段。

### ⑥ 开关与触发条件（v1.2 既有，无拍板，仅确认）

- `CALC_ENGINE_ENABLED: bool = False`（config，CALC 段）；触发 = `CALC_ENGINE_ENABLED ∧ QUERY_PLAN_ENABLED 有 plan ∧ calculation.type∈{yoy,qoq,growth}`；无 plan/开关关 = 零行为。

## 5. 改动清单（预估，拍板后定稿）

| 文件 | 改动 |
| ---- | ---- |
| `common/core/config.py` | 新增 `CALC_ENGINE_ENABLED=False` |
| `apps/chat/models/chat_model.py` | `OperationEnum.CALC_ENGINE = '19'` |
| `apps/chat/task/sql_builder.py` | 抽出「plan+时间窗 → 单条 SELECT」内部组装函数（Phase 5 主入口与 Phase 6 前期子查询共用，主入口行为不变） |
| `apps/chat/task/calc_engine.py` | **新建**：`compute(service, session, result) -> bool`——组装/执行/公式/合并/回退/calc 卡；纯函数库 `calc_formulas.py` 可并入本文件首期 |
| `apps/chat/task/llm.py` | 3-B 后单点插桩（`CALC-ENGINE` 标记，失败吞掉不影响主流程） |
| 前端 | `LogCalc.vue` 新建 + `ExecutionDetails.vue` 分发 + i18n×4 |

## 6. 边界（本期明确不做）

1. 不改 SQL 生成路径、不动 Phase 5 编译范围与回退 reason；
2. `share`/`rank` calculation、类型3 统计分析、多源 `datasource_id`（G5 恒单源）；
3. 行权限场景的前期查询（回退，见③-3）；
4. Calculation Planner 双后端与一致性回归（G5 演进注记）；
5. 3-B 结果校验对合并后 rows 不重复跑（边界记录：3-B 仍对主 SQL 当期结果）。

## 7. 验收（对应 v1.2 Phase 6 验收行）

- **F1**：问「同比增长多少」→ calc 卡含过程、结果与人工核算一致、`change_rate` 小数正确、图表正常；
- **F2**：除零（基期 0）与空结果（前期无数据）确定性 null，不报错；
- **F3**：开关关 → 与现状逐字零差异（A3 式对照）；无 plan 题永不触发；
- **F4**：share/rank/行权限/previous 缺失 → 回退 reason 正确、单期结果照常；
- **F5**：四语言 calc 卡显示正常。

## 8. 待办

1. ~~**用户拍板 ①~⑤**~~ ✅（2026-10-28 全按建议；追加列结构 A 拍板 2026-10-29）；
2. ~~分步实施（Step 1 开关/枚举 → Step 2 sql_builder 抽函数 → Step 3 calc_engine → Step 4 llm.py 插桩 → Step 5 前端四件套 → Step 6 冒烟/文档）~~ ✅（2026-10-29 完成：smoke_p6 **27/27**、smoke_p5 回归 **26/26**、ruff 新改文件全过、前端 build 过、i18n 四语言 JSON 校验过；真实数据 cur=798526/prev=585270 公式与 SQL 真值交叉一致）；
3. 走查 F1~F5（需临时开 `CALC_ENGINE_ENABLED=True` 问同比题）→ 进展文档第九节回填闭环。
