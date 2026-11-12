# Phase 0 评测报告 · 2026-11-12 13:55:07

- 题数：11（跑批次数 11）
- 总通过率：**9/11 = 81.8%**
- 口径：SQL 正确率=assert∈(plan_sql,sql) 且 passed；结果正确率=assert=exec 且 passed（弱断言：不报错）；澄清/回退按各自断言

## 分类

| 分类 | 通过/总数 | 通过率 |
| --- | --- | --- |
| B同比环比 | 8/10 | 80% |
| G复杂回退 | 1/1 | 100% |

## 断言类型

| assert | 通过/总数 |
| --- | --- |
| exec | 1/1 |
| plan_sql | 8/10 |

## 实际轨道分布

| track | 次数 |
| --- | --- |
| no_dsl | 11 |

## 明细

| id | 结果 | ds | assert | 期望轨 | 实际轨 | conf | record | 耗时 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T013 | ✅ | 1 | plan_sql | dsl | no_dsl | 0.7632195 | 239 | 30.8s |  |
| T014 | ❌ | 1 | plan_sql | dsl | no_dsl | 0.7632195 | 240 | 14.4s | query_type=aggregate want=compare |
| T015 | ✅ | 1 | plan_sql | dsl | no_dsl | 0.7512195 | 241 | 22.3s |  |
| T016 | ❌ | 1 | plan_sql | dsl | no_dsl | 0.7812195 | 242 | 12.0s | query_type=aggregate want=compare |
| T018 | ✅ | 1 | plan_sql | dsl | no_dsl | 0.7272195 | 243 | 17.0s |  |
| T019 | ✅ | 1 | plan_sql | dsl | no_dsl | 0.6965432500000001 | 244 | 14.3s |  |
| T020 | ✅ | 1 | plan_sql | dsl | no_dsl | 0.6192195 | 245 | 11.5s |  |
| T021 | ✅ | 1 | plan_sql | dsl | no_dsl | 0.7392195 | 246 | 11.1s |  |
| T023 | ✅ | 1 | plan_sql | dsl | no_dsl | 0.7512195 | 247 | 10.5s |  |
| T024 | ✅ | 1 | exec | dsl | no_dsl | 0.7512195 | 248 | 15.4s | query_type=compare want=aggregate |
| T051 | ✅ | 1 | plan_sql | dsl | no_dsl | 0.8191550000000001 | 249 | 21.5s |  |

## 失败清单（含 SQL 头）

- **T014** [plan_sql] query_type=aggregate want=compare
  - SQL: `SELECT SUM(CASE WHEN `t`.`统计日期` LIKE '2024%' THEN `t`.`游客数量` ELSE 0 END) AS `visitors_2024`, SUM(CASE WHEN `t`.`统计日期` LIKE '2023%' THEN `t`.`游客数量` ELSE 0 END) A`
- **T016** [plan_sql] query_type=aggregate want=compare
  - SQL: `SELECT SUM(CASE WHEN `t`.`统计日期` LIKE '2023%' THEN `t`.`游客数量` ELSE 0 END) AS `visitors_2023`, SUM(CASE WHEN `t`.`统计日期` LIKE '2022%' THEN `t`.`游客数量` ELSE 0 END) A`
