# Phase 0 复判报告 · 2026-11-11 10:24:36（首跑证据 + 修正后期望，未调 LLM）

- 复判题数：54｜通过：**51/54 = 94.4%**
- 待真跑：2（T059 (record 184 = 429)；T060 (record 185 = 429)）

## 分类

| 分类 | 通过/总数 | 通过率 |
| --- | --- | --- |
| A取数时间 | 12/12 | 100% |
| B同比环比 | 11/11 | 100% |
| C排名占比 | 6/7 | 86% |
| D趋势多维 | 7/7 | 100% |
| E模糊词 | 4/6 | 67% |
| F歧义闲聊 | 3/3 | 100% |
| G复杂回退 | 4/4 | 100% |
| H异常边界 | 4/4 | 100% |

## 明细

| id | 结果 | assert | track | record | 备注 |
| --- | --- | --- | --- | --- | --- |
| T001 | ✅ | plan_sql | dsl | 129 |  |
| T002 | ✅ | plan_sql | dsl | 130 |  |
| T003 | ✅ | plan_sql | dsl | 131 |  |
| T004 | ✅ | plan_sql | dsl | 132 |  |
| T005 | ✅ | plan_sql | dsl | 133 |  |
| T006 | ✅ | plan_sql | dsl | 134 |  |
| T007 | ✅ | plan_sql | dsl | 135 |  |
| T008 | ✅ | plan_sql | llm | 136 |  |
| T009 | ✅ | plan_sql | dsl | 137 |  |
| T010 | ✅ | plan_sql | llm | 138 |  |
| T011 | ✅ | plan_sql | llm | 139 |  |
| T012 | ✅ | plan_sql | llm | 140 |  |
| T013 | ✅ | plan_sql | dsl | 141 |  |
| T014 | ✅ | plan_sql | dsl | 142 |  |
| T015 | ✅ | plan_sql | dsl | 143 |  |
| T016 | ✅ | plan_sql | dsl | 144 |  |
| T018 | ✅ | plan_sql | dsl | 145 |  |
| T019 | ✅ | plan_sql | dsl | 146 |  |
| T020 | ✅ | plan_sql | dsl | 147 |  |
| T021 | ✅ | plan_sql | dsl | 148 |  |
| T022 | ✅ | plan_sql | llm | 149 |  |
| T023 | ✅ | plan_sql | dsl | 150 |  |
| T024 | ✅ | exec | dsl | 151 | query_type=compare want=aggregate |
| T025 | ❌ | plan_sql | llm | 152 | record.error:{"message":"Execute SQL Failed","traceback":"Traceback (most recent call last):\n  File \"C:\\Users\\gaohu\\aiPyProject\\nl2sqlPros\\SQLBot\\backend\\.venv\\Lib |
| T026 | ✅ | plan_sql | llm | 153 |  |
| T027 | ✅ | sql | llm | 154 |  |
| T028 | ✅ | plan_sql | llm | 155 |  |
| T030 | ✅ | plan_sql | llm | 156 |  |
| T031 | ✅ | plan_sql | llm | 157 |  |
| T032 | ✅ | plan_sql | llm | 158 |  |
| T033 | ✅ | plan_sql | dsl | 159 |  |
| T034 | ✅ | plan_sql | dsl | 160 |  |
| T035 | ✅ | plan_sql | llm | 161 |  |
| T037 | ✅ | plan_sql | dsl | 162 |  |
| T038 | ✅ | plan_sql | llm | 163 |  |
| T039 | ✅ | plan_sql | dsl | 164 |  |
| T040 | ✅ | plan_sql | dsl | 165 |  |
| T041 | ✅ | sql | llm | 166 |  |
| T042 | ✅ | sql | dsl | 167 |  |
| T043 | ❌ | plan_sql | llm | 168 | sql_keys miss=['各处室假日上报数据总表'] |
| T044 | ❌ | plan_sql | dsl | 169 | sql_keys miss=['各处室假日上报数据总表', '国庆'] |
| T045 | ✅ | plan_sql | llm | 170 |  |
| T046 | ✅ | sql | llm | 171 |  |
| T047 | ✅ | clarify | llm | 172 | need_clarification=True conf=0.5412195000000001 |
| T048 | ✅ | exec | dsl | 173 |  |
| T050 | ✅ | clarify | llm | 175 | need_clarification=True conf=0.437628 |
| T051 | ✅ | plan_sql | dsl | 176 |  |
| T052 | ✅ | fallback | llm | 177 | route=llm_fallback reason=scope |
| T053 | ✅ | fallback | llm | 178 | route=llm_fallback reason=dimension_resolve |
| T054 | ✅ | fallback | llm | 179 | route=llm_fallback reason=metric_resolve |
| T055 | ✅ | exec | dsl | 180 |  |
| T056 | ✅ | exec | llm | 181 |  |
| T057 | ✅ | exec | dsl | 182 |  |
| T058 | ✅ | exec | llm | 183 | record.error:无法根据您的问题生成SQL：提问内容“asdfghjkl 12345”不是可识别的查询需求，请提供明确的查询内容，例如要查询的表、指标、维度或时间范围。 |

## 失败清单（3）

- **T025** [plan_sql] record.error:{"message":"Execute SQL Failed","traceback":"Traceback (most recent call last):\n  File \"C:\\Users\\gaohu\\aiPyProject\\nl2sqlPros\\SQLBot\\backend\\.venv\\Lib
- **T043** [plan_sql] sql_keys miss=['各处室假日上报数据总表']
- **T044** [plan_sql] sql_keys miss=['各处室假日上报数据总表', '国庆']

## 轨道缺口：期望轨 ≠ 实际轨（7）

| id | 期望 | 实际 | 结果 |
| --- | --- | --- | --- |
| T011 | dsl | llm | ✅ |
| T012 | dsl | llm | ✅ |
| T030 | dsl | llm | ✅ |
| T031 | dsl | llm | ✅ |
| T038 | dsl | llm | ✅ |
| T056 | dsl | llm | ✅ |
| T058 | any | llm | ✅ |