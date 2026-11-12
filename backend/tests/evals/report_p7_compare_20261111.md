# Phase 7 双轨互补对比报告（动作②）

- 生成：2026-11-12 | 数据源：Phase 0 rejudge 基线 + P7 三批（A=force llm / C=calc 纯 llm / B=缺口 force dsl）
- 覆盖：32 题（30 补纯 LLM 轨 + 2 缺口补编译轨；T043/T044 数据源配错按拍板忽略）
- force-track 实现：run_evals 进程内改 settings（llm=关 DSL_COMPILE+CALC_ENGINE；dsl=开 DSL_COMPILE）

| 题 | 期望轨 | LLM轨 P7 | DSL轨 | P0对照(实测/结果) | 一致性 |
| --- | --- | --- | --- | --- | --- |
| T001 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T002 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T003 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T004 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T005 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T006 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T007 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T009 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T013 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T014 | dsl | ❌ (no_dsl) | ✅ (P0) | dsl/✅ | 分歧:DSL过 |
| T015 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T016 | dsl | ❌ (no_dsl) | ✅ (P0) | dsl/✅ | 分歧:DSL过 |
| T018 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T019 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T020 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T021 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T023 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T024 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T033 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T034 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T037 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T038 | dsl | ✅ (llm,P0) | 缺失(回退复现(P7实测llm)) | llm/✅ | - |
| T039 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T040 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T042 | dsl | ❌ (no_dsl) | ✅ (P0) | dsl/✅ | 分歧:DSL过（假通过，双轨皆错→问题26） |
| T048 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T051 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T055 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T056 | dsl | ✅ (llm,P0) | ✅ (dsl) | llm/✅ | 同✅ |
| T057 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T059 | dsl | ✅ (no_dsl) | ✅ (P0) | dsl/✅ | 同✅ |
| T060 | dsl | ✅ (no_dsl) | ❌ (P0) | dsl/❌ | 分歧:LLM过 |

## 统计

- LLM 轨（P7 纯 LLM）：**29/32 = 90.6%**
- DSL 轨（P0 基线 + P7 缺口重跑）：**30/31 = 96.8%**
- 双轨齐全：31 题 | 一致 27（一致率 87.1%）| 分歧 4（DSL过 LLM败 3 / LLM过 DSL败 1）
- DSL 轨缺失：1 题 T038

## 结论要点

1. T038 缺口复现：force-dsl 下编译仍回退 LLM（根因已定位=plan query_type/calculation 自相矛盾，归并问题 25）；T056 已走 DSL 轨。
2. 分歧题解读（2026-11-12 用户查证修正）：T014/T016 = 归一化兜住矛盾 plan 的真过，保留为放量正向证据（plan 缺陷另立问题 25）；T042 撤下——双轨皆错（DSL 假通过+LLM 拒答，根因术语缺东南亚国家释义+弱断言，问题 26）；反向分歧 T060 其 DSL 数据为问题 24 修复前，待 2026-11-13 复测。
3. 期望 llm 22 题按拍板不跑（结构性无 DSL 轨）；T043/T044 数据源配错忽略。
