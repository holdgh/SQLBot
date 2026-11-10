# Phase 6 计算引擎（Post-Query Calculation Engine）方案分析

> 创建：2026-10-28（启动日，Phase 5 验收闭环后启动）｜状态：**✅ 拍板通过（2026-10-28，①~⑤ 全按建议）→ Step 1~6 实施完成（2026-10-29）→ 问题 17 方案 C（拍板 10-29/实施 10-30）、问题 18 方案 D（拍板并实施 11-02）、问题 19 Table.ts 空值守卫（11-02）、问题 20 方案 A scope 守卫（拍板并实施 11-03，行为矩阵固化 v1.2 第六节）→ ✅ F1 重测通过（2026-11-02，问题 17/18 关闭；多样性损失挂起=问题 18 演进项）→ F2 ✅ 关闭（11-02 两轮实测：空结果 2018vs2017 确定性 null 不报错 ✓、单边 2021vs2020 当期 273506 正常 ✓；字面 `null` 显示=问题 19 Table.ts 守卫修复，页面复测显示 `-` 正常）** → **F3 ✅ 通过（11-03：calc 关重问同比题 → op17 卡「LLM 生成轨（回退）/scope 原因」、结果正常=Phase 5 基线，经问题 20 方案 A 修复后复测）** → **F5 ✅ 通过（11-03：四语言执行详情显示正常）** → **F4 ✅ 通过（11-03：rank/share reason=`unsupported_calc`、行权限 reason=`row_permission` 三实测过且结果正常；no_previous 子项拍板降级冒烟 U8/C6d 收口；问题 21 方案 A=reason 优先级类型门最前+契约门末位，冒烟 51/51）—— F1~F5 全过，Phase 6 验收闭环（2026-11-03）**（验收编号沿字母序，E1~E5 已被 Phase 5 占用）
> 实施中追加拍板：**列结构 A**（2026-10-29，拍板④歧义澄清）——`<指标名>` 列列头即指标名、值=当期值，另设 同期值/变化值/变化率 三列，无冗余「指标」名字串列。
> 权威规格：`v201改造方案_v1.2.md` 第四节 Phase 6 章节（L217-228）与第九节步骤 18（L380）。
> 配套文档：进展文档第九节（Phase 6）、detail/phase4-query-plan方案分析.md（plan 结构来源）、detail/phase5-sql-builder方案分析.md（解析组件来源）。

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
| **LLM 实际恒输出 `sub_queries: []`**，执行布局明确留 Phase 6 再设计 | phase4 方案文档 L43（schema 预留表） |
| calculation≠none 在 Phase 5 恒回退 LLM 轨（scope reason），Phase 5 不接手 | `sql_builder.py` `COMPILED_QUERY_TYPES` 与 scope 判定 |
| 执行链：check_sql → 白名单 → 3-A → 行权限 filter → check_save_sql → SSE `sql` → **`execute_sql`（EXECUTE_SQL 卡）→ 3-B → DataFormat 规整 → `save_sql_data` → SSE `sql-data` → 图表链（generate_chart LLM 选图）** | `llm.py:1745-1886` |
| 行权限：normal user 且有权限规则时 `generate_filter`（LLM 调用）改写 SQL；normal user 无规则/普通用户直通 | `llm.py:1806-1813` |
| 环话题实测（E3 对照）：plan 正常产出 calculation=qoq + time_range.current/previous，主 SQL 由 LLM 生成当期数据 | phase5 方案文档第 11 节（E3 LLM 轨对照）/ 进展文档 8.4 |

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

> ⚠️ **修正（问题 17，方案 C：拍板 2026-10-29、实施 2026-10-30，替代上述取舍的两项前提）**：F1 首测证明「主 SQL 照旧」下 LLM 轨对计算题生成的是**答案型 SQL**（单条 CASE WHEN 两期聚合+同比率），「主 SQL=当期数据（列=指标名）」契约不成立——引擎取当期 null 且整体替换破坏 LLM 已算好的结果（详见《v201的改造问题发现与分析处理.md》问题 17）。修正为：**计算题（yoy/qoq/growth × aggregate/compare）由编译轨供给当期窗 SQL**（复用 Phase 5 `_compile`，合成 answer 注入既有链路，LLM 不生成主 SQL；`compile_plan_to_answer` gate = `DSL_COMPILE_ENABLED` ∨（`CALC_ENGINE_ENABLED` ∧ 计算题）），calc_engine 只负责补前期窗+公式合并；**LLM 轨回退直答场景由契约检测兜底**（主 data 无指标列 → `contract_mismatch` 跳过不接管，LLM 答案原样返回）。Phase 5 原 scope 中 calculation=none 的全部行为、提示词、开关独立性零改动（`CALC_ENGINE_ENABLED=False` → LLM 原生直答同比，全链现状）。
>
> ⚠️ **再修正（问题 18，方案 D：拍板并实施 2026-11-02）**：F1 重测计算侧通过，但**结果页仍显示当期总量**——`generate_chart`（LLM）按当期单值 SQL 生成列引用，合并 4 列白给（同族契约分叉，发生在图表配置生成环节，详见问题 18）。修正为：**`_calc_computed` 置位（计算引擎接管成功）→ 跳过 LLM 图表生成，`build_rule_chart` 规则构造确定性 table 配置**（列=合并数据首行 keys，复用 `check_save_chart` 落库与 lower 契约，合成 GENERATE_CHART 卡），前端零改动；回退场景与开关关走原 LLM 图表环节。**取舍：calc 题失去图表多样性（固定 table），用户知悉拍板暂行、记为挂起演进项（问题 18「取舍记录」）。**

**公式与子查询拓扑（确定性）**：

| calculation.type | 子查询拓扑 | Python 公式 |
| ---- | ---- | ---- |
| `yoy` / `qoq` / `growth` | 2 条同构（当期窗=主 SQL 已有；前期窗=程序组装） | `变化值=当期-基期`；`变化率=(当期-基期)/基期` |
| `share` / `rank` | 分母/名次语义依赖 `expr` 自由文本，解析不确定 → **本期回退**（见拍板点②） | — |

## 4. 拍板点（建议已给出，请逐条确认）

### ① 轨道形态：形态 1「真 Post-Query」（建议 ✅）

- **建议**：主 SQL 照旧 LLM 轨执行，calc_engine 只做「补前期查询 + Python 合并」，插桩在 3-B 之后。理由：a) 贴规格字面（Post-Query、挂接 execute_sql 附近、契约完全不变）；b) 主链改动最小（单点插桩）；c) 不动 Phase 5 边界，两 Phase 职责清晰。
- 备选形态 2：calculation 题在分流点整体接管（N 子查询自执行自落库）——侵入 check_save_sql/EXECUTE_SQL/权限/3-B 全链对齐，复杂度高，不建议本期。
- **修正（问题 17，方案 C 拍板 2026-10-29）**：F1 首测证伪「主 SQL 照旧」前提（LLM 答案型 SQL 契约失配，见上文 §3 修正注）；形态 1 与形态 2 的折中落地——**当期数据由编译轨供给（形态 2 的确定性）+ 既有链路零改（形态 1 的最小侵入）**：计算题进 `compile_plan_to_answer`（合成 answer 注入，check_sql/白名单/3-A/权限/执行/图表全走 Phase 5 已验证件），calc_engine 仍仅 3-B 后单点插桩补前期+合并；LLM 轨回退直答由 `contract_mismatch` 契约检测兜底不接管。原建议「一行不改 SQL 生成路径」的字面保留于 **calculation=none 题**（其路径确实零改动），计算题的 LLM 生成路径改为「被分流跳过」而非「被修改」。

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

- **F1**：问「同比增长多少」→ calc 卡含过程、结果与人工核算一致、`change_rate` 小数正确、图表正常；**✅ 已通过（2026-11-02，历经问题 17→方案 C、问题 18→方案 D 两修后重测通过）**
- **F2**：除零（基期 0）与空结果（前期无数据）确定性 null，不报错；（2026-11-02 实测「2018年…同比」：当期 2018 与前期 2017 **均无数据**——库内年份仅 2021~2026，`SUM` 空集返回 1 行 NULL → 合并 1 行全 null、行数 1、**不报错，空结果场景符合验收标准**）。**（11-02 补测收口：① 用户确认页面显示字面 `null` → 定位 `charts/Table.ts` S2 formatter `String(null)` → 记问题 19，两处空值守卫返回 `-` 同日实施 + build 过）；② 「2021年…同比」单边实测通过——当期 273506 正常、对比期/变化/变化率 `-`、不报错、行数 1。F2 计算侧通过）** → **✅ F2 关闭（2026-11-02，问题 19 页面复测显示 `-` 正常）**
- **F3**：开关关 → 与现状逐字零差异（A3 式对照）；无 plan 题永不触发；（**✅ 已通过 2026-11-03**：calc 关问「2021年上海接待美国游客数量同比增长多少」→ dsl 卡「LLM 生成轨（回退）/超出首期编译范围（对比/排名/占比/多表等，走 LLM 轨道）」、无 op19、结果正常；过程中暴露**问题 20**（gate 漏洞：DSL 开独立放行致 calc 关计算题误入编译轨出单期结果）→ **方案 A** `_resolve_scope` 守卫修复 + 行为矩阵固化 v1.2 第六节，冒烟 47/47 + 回归 26/26）
- **F4**：share/rank/行权限/previous 缺失 → 回退 reason 正确、单期结果照常（**✅ 已通过 11-03：rank/share reason=`unsupported_calc`、行权限 reason=`row_permission` 三实测过；行权限实测=受限用户问英国→主 SQL 查无数据→结果页 `-` 符合权限预期；no_previous 子项 11-03 拍板降级冒烟 U8/C6d 收口——自然问数难构造 plan 缺窗**）；
- **F5**：四语言 calc 卡显示正常（**✅ 已通过 2026-11-03**）。

## 8. 待办

1. ~~**用户拍板 ①~⑤**~~ ✅（2026-10-28 全按建议；追加列结构 A 拍板 2026-10-29）；
2. ~~分步实施（Step 1 开关/枚举 → Step 2 sql_builder 抽函数 → Step 3 calc_engine → Step 4 llm.py 插桩 → Step 5 前端四件套 → Step 6 冒烟/文档）~~ ✅（2026-10-29 完成：smoke_p6 **27/27**、smoke_p5 回归 **26/26**、ruff 新改文件全过、前端 build 过、i18n 四语言 JSON 校验过；真实数据 cur=798526/prev=585270 公式与 SQL 真值交叉一致）；
3. 走查 F1~F5 → **✅ 全部通过（2026-11-03，Phase 6 验收闭环）**：F1/F2/F3/F5 页面实测 + F4 三实测（rank/share/行权限）+ no_previous 降级冒烟收口；回填见进展文档第九节。
