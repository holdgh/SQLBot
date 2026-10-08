# SQLBot 优化改造过程明细记录

> 记录时间：2026-09-23（下班前保存，次日继续）；2026-09-24 更新（三点改造全部完成并验证）
> 项目路径：`C:\Users\gaohu\aiPyProject\nl2sqlPros\sqlbot_pro`
> 当前状态：**改造点1 ✅ / 改造点2 ✅ / 改造点3 ✅ —— 三点改造全部完成（2026-09-24），ruff 零新增、编译/冒烟/import main 全通过；剩余为上线后观察项（DB 实联调、Excel 列数、analysis/predict 挂接扩展）**

---

## 一、改造任务总体要求

对 sqlbot 源码做三点优化改造。**改造要求：务必注释掉相关旧代码（不删除），新代码务必添加醒目的改造标记注释。** 分多次进行，每次处理一点。

1. **改造点1**：将术语与 SQL 示例数据的关键词检索机制（当前是模糊查询，基本的包含关系 ILIKE）改造成 RAG 中典型的关键词检索机制（BM25 分词打分）。
2. **改造点2**：自定义提示词这块不开源，但源码中已存在相应的表结构，请实现自定义提示词相关功能（自定义提示词的维护 + 问数过程中获取与用户问题相关的自定义提示词）。
3. **改造点3**：单靠 RAG 检索获取相关上下文（术语、SQL 示例、自定义提示词）略显粗糙，增加一层大模型过滤（RAG 找出候选项集合，然后用大模型再过滤一遍，选出更精准的与用户问题相关的上下文）。

---

## 二、源码调研结论（已完成）

### 2.1 术语（terminology）与 SQL 示例（data_training）的关键词检索现状

#### 表结构（ORM + DDL）

- 术语表 ORM：`backend/apps/terminology/models/terminology_model.py:11-23`
  - 字段：id, oid, pid, create_time, word, description, **embedding (VECTOR/pgvector)**, specific_ds, datasource_ids (JSONB), enabled, advanced_application
  - 同义词通过 `pid` 实现父子结构：父记录=主词（pid is None），子记录=同义词
- SQL 示例表 ORM：`backend/apps/data_training/models/data_training_model.py:10-20`
  - 字段：id, oid, datasource, create_time, question（示例问题）, description（示例SQL）, **embedding (VECTOR)**, enabled, advanced_application
- DDL 来源是 `backend/alembic/versions/*.py`（docs/ 和 installer/ 里没有建表 SQL）：
  - `039_create_terminology.py`（建表+pgvector扩展）、`041`（加oid）、`045`（加specific_ds/datasource_ids）
  - `042_data_training.py`（建表）、`051`（加advanced_application）
  - `069_term_custom_prompt.py`（给 custom_prompt、terminology 加 advanced_application）
  - `047_table_embedding.py`（core_table/core_datasource embedding，Text 存 JSON 向量）

#### 模糊查询/LIKE 的具体位置（改造点1 要替换的目标）

| 位置 | 逻辑 |
|---|---|
| `backend/apps/terminology/curd/terminology.py:849-858` | 问数流程术语匹配：`text(":sentence ILIKE '%' \|\| word \|\| '%'"`——**词条必须完整出现在用户问题中** |
| `backend/apps/data_training/curd/data_training.py:529-539` | 问数流程SQL示例匹配：**双向 contains**（问题包含示例问题 or 示例问题包含问题） |
| `terminology.py:26-33` | 管理页面搜索 `ILIKE '%kw%'`（管理页列表搜索，非问数流程，不动） |
| `data_training.py:24-29` | 管理页面搜索 `ILIKE '%kw%'`（同上，不动） |

> 注意：`terminology.py:73`、`869` 的 JSONB contains 是数据源范围过滤，不是关键词检索，保留。

#### 已存在的双路召回合并入口（关键函数）

- **`select_terminology_by_word`**（`terminology.py:842-939`）：
  1. 先 ILIKE 关键词查询（849-881，**改造点1 替换此段**）
  2. 若 `settings.EMBEDDING_ENABLED` 再做 pgvector 余弦召回并合并去重（886-910，**保留**）
  3. 按 pid 去重（子命中归并到父词组），回表取 word/description，组装 `{words:[], description}` 结构（912-939）
- **`select_training_by_question`**（`data_training.py:521-593`）：结构相同，先双向 ILIKE（529-548，**改造点1 替换此段**）+ 向量召回（550-570，**保留**），输出 `{'question':..., 'suggestion-answer':...}`

#### 向量召回 SQL（保留不动）

- 术语 embedding SQL：`terminology.py:798-839`（三个变体：通用/embedding_sql、带数据源、带高级应用；阈值 `EMBEDDING_TERMINOLOGY_SIMILARITY`，TOP `EMBEDDING_TERMINOLOGY_TOP_COUNT`）
- SQL 示例 embedding SQL：`data_training.py:497-518`（两个变体；阈值 `EMBEDDING_DATA_TRAINING_SIMILARITY`、TOP `EMBEDDING_DATA_TRAINING_TOP_COUNT`）

#### 检索结果 → prompt 模板包装

- 术语：`terminology.py:975-986` `get_terminology_template` → `to_xml_string`（952-972，XML root=terminologies）→ `get_base_terminology_template().format(...)`
- SQL 示例：`data_training.py:619-631` `get_training_template` → `to_xml_string`（596-616，root=sql-examples）
- 模板 getter：`backend/apps/template/generate_chart/generator.py:8-14`
- 模板正文：`backend/templates/template.yaml` 第2/5行（terminology/data_training），第332-342行（generate_terminologies_info / generate_data_training_info / generate_custom_prompt_info）

#### RAG 基础设施盘点（已具备）

| 组件 | 位置 | 说明 |
|---|---|---|
| Embedding 模型 | `backend/apps/ai_model/embedding.py:20-63` | 本地 HuggingFace `shibing624_text2vec-base-chinese`，`LOCAL_MODEL_PATH=/opt/sqlbot/models` |
| 配置项 | `backend/common/core/config.py:102-110, 129-131` | `EMBEDDING_ENABLED=True`、相似度 0.4、TOP 5、`TABLE_EMBEDDING_ENABLED=True` |
| 向量库 | PostgreSQL + pgvector | 距离算子 `<=>`，无独立向量库（Milvus/FAISS 均无） |
| 异步写向量 | `backend/common/utils/embedding_threads.py:16-48` | 术语/示例/表/数据源 回填线程 |
| 启动补向量 | `backend/main.py:45-57, 72-74` | `@SingleWorkerGuard.once` |
| 表向量召回 | `backend/apps/datasource/embedding/table_embedding.py:43-78` | Python 内存余弦排序（Text 列） |
| 数据源向量召回 | `backend/apps/datasource/embedding/ds_embedding.py:18-91` | 自动选数据源 |

> 两套机制并存：术语/示例用 pgvector SQL 召回；表/数据源用 Python 余弦。**没有 jieba 等分词库**（pyproject.toml 已确认无），改造点1 需自实现分词或加依赖。

### 2.2 自定义提示词（custom_prompt）现状（改造点2）

#### 表结构 DDL（存在）

- 建表：`backend/alembic/versions/046_add_custom_prompt.py:22-32`
  ```
  custom_prompt:
    id BigInteger Identity pk
    oid BigInteger
    type Enum('GENERATE_SQL','ANALYSIS','PREDICT_DATA', native_enum=False, length=20)
    create_time DateTime
    name VARCHAR(255)
    prompt Text
    specific_ds Boolean
    datasource_ids JSONB
  ```
- `069_term_custom_prompt.py` 加 `advanced_application BIGINT`
- `070_add_table_column_comments.py:130-140` 中文注释：自定义提示词表 / 提示词ID / 组织ID / 提示词类型 / 提示词名称 / 提示词内容 / 是否关联特定数据源 / 关联数据源ID列表 / 高级应用ID

#### 业务代码闭源（需补实现）

- ORM 模型不在本仓库：`backend/alembic/env.py:29` → `from sqlbot_xpack.custom_prompt.models.custom_prompt_model import ...`；依赖 `pyproject.toml:42` `sqlbot-xpack>=0.0.5.36`（testpypi）
- 开源仓库内只有**调用点**：
  - `backend/apps/chat/task/llm.py:22-23` 导入 `find_custom_prompts`、`CustomPromptTypeEnum`（xpack）
  - 调用处 `llm.py:392-418` `filter_custom_prompts()`，受 `SQLBotLicenseUtil.valid()` License 开关控制
  - 调用点：`llm.py:482`（ANALYSIS）、`:533`（PREDICT_DATA）、`:784`、`:1250`（GENERATE_SQL）
  - 审计日志：`backend/common/audit/schemas/log_utils.py:15,55-60,131` 引用 `CustomPrompt` 模型
- Swagger 文案已有接口描述：`backend/apps/swagger/i18n.py:96-98`、`locales/zh.json:189-195`（分页查询/创建更新/删除/导出/上传）
- i18n：`backend/locales/zh-CN.json:123-140`（`i18n_custom_prompt.*`）
- **`backend/apps/api.py` 没有 custom_prompt 路由** → 需要开源实现 CRUD 路由
- 路由由 `backend/main.py:253` `sqlbot_xpack.init_fastapi_app(app)` 注册（闭源）

#### 前端已完整对接（接口路径必须兼容）

`frontend/src/api/prompt.ts:3-14`：
```
POST   /system/custom_prompt/${type}/page/${pageNum}/${pageSize}   分页
PUT    /system/custom_prompt                                       创建/更新
DELETE /system/custom_prompt                                       删除
GET    /system/custom_prompt/${id}                                 详情
POST   /system/custom_prompt/${type}/export                        导出
POST   /system/custom_prompt/${type}/uploadExcel                   上传
GET    /system/custom_prompt/template                              模板
```

- 维护页面：`frontend/src/views/system/prompt/index.vue`（约1050行），路由 `/set/prompt`（`router/index.ts:143-146`），三类型 Tab：问数SQL/数据分析/数据预测（:107-127）
- 执行明细回显：`frontend/src/views/chat/execution-component/LogCustomPrompt.vue:24`（"匹配到 {0} 个自定义提示词"）

#### 参照物（开源侧完整 CRUD 范例）

- 术语维护：`backend/apps/terminology/api/terminology.py:25`（前缀 `/system/terminology`）+ `curd/terminology.py`（986行）+ 前端 `views/system/professional/`
- SQL 示例维护：`backend/apps/data_training/api/data_training.py:26`（前缀 `/system/data-training`）+ `curd/data_training.py`（631行）+ 前端 `views/system/training/index.vue`

### 2.3 问数主流程（改造点2/3 的挂接点）

```
POST /chat/question                          chat/api/chat.py:245 question_answer()
  └─ question_answer_inner()                 chat/api/chat.py:253
       └─ stream_sql()                       chat/api/chat.py:346
            ├─ LLMService.create(...)        chat/task/llm.py:216
            ├─ init_record()                 chat/task/llm.py:350
            └─ run_task()                    chat/task/llm.py:1236
                 ├─ [有数据源] llm.py:1242-1252:
                 │    filter_terminology_template()   llm.py:367  ← 改造点1（内部调 select_terminology_by_word）
                 │    filter_training_template()      llm.py:420/427-440  ← 改造点1（内部调 select_training_by_question）
                 │    filter_custom_prompts()         llm.py:392  ← 改造点2（当前走 xpack，需开源实现）
                 │    init_messages()                 llm.py:270→1252
                 ├─ [无数据源] select_datasource()    llm.py:646，选定后 llm.py:776-786 同样执行上面四步
                 ├─ generate_sql()                    llm.py:791
                 ├─ check_sql / 表名校验              llm.py:1331-1346
                 ├─ generate_filter / dynamic sql     llm.py:1348-1370
                 ├─ execute_sql()                     llm.py:1184/1403
                 └─ generate_chart()                  llm.py:964
```

#### filter 三个方法详情（llm.py）

- `filter_terminology_template`（367-390）：高级应用 type==1 时按 `current_assistant.id` 过滤且忽略 ds；否则按 ds_id。调 `get_terminology_template` → 写回 `self.chat_question.terminologies`
- `filter_custom_prompts`（392-418）：受 `SQLBotLicenseUtil.valid()` 控制，调 xpack `find_custom_prompts` → 写回 `self.chat_question.custom_prompt`
- `filter_training_template`（420-444）：与术语同构 → `self.chat_question.data_training`
- 结果均通过 `start_log(OperationEnum...)` / `end_log(full_message=...)` 落 `chat_log` 表（前端执行明细展示）
- 日志枚举：`chat_model.py:35-49` `FILTER_TERMS='9'`、`FILTER_SQL_EXAMPLE='10'`、`FILTER_CUSTOM_PROMPT='11'`

#### Prompt 组装（改造点3 过滤结果注入点）

1. **`ChatQuestion.sql_sys_question()`**（`chat_model.py:258-301`）把检索结果格式化进模板：
   - `generate_terminologies_info` / `generate_data_training_info` / `generate_custom_prompt_info`
2. **`LLMService.init_messages()`**（`llm.py:270-305`）拼成 LangChain 多轮伪 system：
   ```
   system(Instruction) → rules(规则) → AI确认 → schema → AI确认
   → custom_prompt → AI确认 → terminologies → AI确认 → data_training → AI确认
   → 历史轮次 → 当前问题(user)
   ```
   消息类型 `SystemPromptMessage/HumanPromptMessage/AIPromptMessage`（`chat_model.py:430-454`，`sqlbot_system=True` 标记）
3. 模板键占位：`template.yaml:340-342` `generate_custom_prompt_info: 以下是你可以参考的额外信息：{custom_prompt}`

#### 其他场景注入点（对照）

- 分析：`llm.py:480-485` → `analysis_sys_question()`（`chat_model.py:323-325`，template.yaml:586-609）
- 预测：`llm.py:533-537` → `predict_sys_question()`（`chat_model.py:330-332`，template.yaml:619-647）

---

## 三、改造计划与进度

### 改造点1：模糊 ILIKE → RAG 典型关键词检索（BM25）【已完成 2026-09-24】

**状态：代码已改完。ruff 新增代码告警为零，BM25 分词/打分冒烟测试通过。**

实际落地内容：

1. 新建 `backend/common/utils/keyword_retrieval.py`：
   - `tokenize()`：无词典轻量分词——英文/数字按词切分；中文产出单字(unigram)+相邻二元组(bigram)
   - `BM25` 类：标准 Okapi BM25（k1=1.5, b=0.75 可配）
   - `bm25_search()`：通用打分接口，(doc, score) 降序 Top-K，min_score 严格大于阈值
   - `bm25_retrieve()`：按 settings 配置执行的便捷封装（curd 层使用）
2. `config.py:135-141` 新增配置（带【改造标记 RAG-KEYWORD】）：
   - `KEYWORD_RETRIEVAL_ENABLED=True`、`KEYWORD_RETRIEVAL_TOP_COUNT=10`
   - `KEYWORD_RETRIEVAL_MIN_SCORE=0.0`（严格大于，0 即要求至少一个分词命中）
   - `KEYWORD_RETRIEVAL_MAX_CANDIDATES=2000`（候选集上限，防全表捞）
   - `KEYWORD_RETRIEVAL_BM25_K1=1.5`、`KEYWORD_RETRIEVAL_BM25_B=0.75`
   - `KEYWORD_RETRIEVAL_ENABLED` 已加入 `lowercase_bool` 校验器（config.py:145）
3. `terminology.py` `select_terminology_by_word`（851-929）：
   - 旧 ILIKE 段整块注释保留（852-889，含数据源/高级应用过滤与 params 构造）
   - 新代码（891-929）：同 where 条件（oid/enabled/数据源/高级应用，去掉 ILIKE）+ LIMIT 候选集 → `bm25_retrieve` 打分 → 组装 `(id, pid, word)` 行；E712 用 `.is_(True/False)` 等价写法
   - pgvector 向量段、pid 归并去重、模板组装保留未动
4. `data_training.py` `select_training_by_question`（531-575）：旧双向 ILIKE 注释保留，新候选集 + BM25 产出 `(id, question)`；向量段保留
5. 管理页列表搜索 ILIKE（terminology.py:26、data_training.py:24）**未动**（按计划）
6. 验证：
   - `ruff check common/utils/keyword_retrieval.py` → All checks passed（含 B905 zip strict 修复）
   - 两个 curd 文件 ruff 剩余告警均为存量（UP045/E712/I001 原文件已有）
   - 冒烟测试：`bm25_search('什么是GDP国内生产总值', ...)` 正确排序 GDP/国内生产总值，无命中查询返回 []

### 改造点2：自定义提示词开源实现【已完成 2026-09-24】

**状态：7 个新文件 + 4 处替换全部完成；ruff / py_compile / 三轮冒烟 / import main 全部通过。**

#### 上午完成的调研（通过反射/字节码探测 xpack 闭源包，结论已固化进代码）

xpack 安装位置：`C:\Users\gaohu\aiPyProject\nl2sqlPros\SQLBot\backend\.venv\Lib\site-packages\sqlbot_xpack`（编译 .pyd，无法读源码，用 inspect/MagicMock 探测出以下行为）：

1. **模型共存问题（最大风险点，已实测解决）**：
   - xpack 与 SQLModel 共享全局 metadata，`import sqlbot_xpack` 即注册 `custom_prompt` 表；xpack 侧**未开** `extend_existing`，若开源模型先定义该表、xpack 后加载会直接抛 `Table already defined` 崩溃（已实测复现）
   - 方案：开源模型模块顶部先 `try: import sqlbot_xpack.custom_prompt.models.custom_prompt_model except Exception: pass`（保证 xpack 先注册），然后**条件双分支**定义类：
     - xpack 表已存在 → `__table__ = existing_table` + 每个字段 `Field(sa_column=既有列)`（复用列对象，不替换，双 mapper 共存 select/insert 均正常——已用测试脚本验证）
     - xpack 不在场 → `__tablename__` 自建表（按 046/069 DDL）——已验证
   - 枚举：xpack 的 `CustomPromptTypeEnum` **不是 str 子类**（plain Enum，name==value）；SQLAlchemy Enum 列绑定跨枚举类成员/普通字符串均已实测可正常 bind；pydantic DTO 按值归一化（xpack 成员/字符串 → 开源枚举）已验证
2. **xpack 接口面（反射确认，开源实现与之逐一对齐）**：
   - 模型字段：id, oid(default=1), type(enum length=20), create_time, name(255), prompt(Text), specific_ds(default=False), datasource_ids(JSONB default=[]), advanced_application(BIGINT)
   - DTO：`CustomPromptInfo`（含 datasource_names/advanced_application_name）、`CustomPromptInfoResult`（advanced_application 为 **str**）、`SearchCustomPromptInfo{name, ds_list, adv_list}`
   - curd 函数签名：`page_custom_prompt / get_all_custom_prompt / build_custom_prompt_query / execute_custom_prompt_query / create/update/delete/batch_create / get_custom_prompt_base_query / find_custom_prompts / to_xml_string`
   - 路由（prefix `/system/custom_prompt`, tags `CustomPrompt`，**无 require_permissions**，有 system_log 审计）：
     - `POST /{custom_prompt_type}/page/{current_page}/{page_size}`（body SearchCustomPromptInfo）
     - `PUT ''`、`DELETE ''`（body list[int]）、`POST /{custom_prompt_type}/export`、`GET /template`、`POST /{custom_prompt_type}/uploadExcel`
   - **注册顺序**：`main.py:245 app.include_router(api_router)` 在 `main.py:253 sqlbot_xpack.init_fastapi_app(app)` **之前** → 开源路由先注册，同路径时开源路由优先生效（Starlette 按注册顺序匹配），xpack 同名路由被遮蔽
3. **行为细节（Mock session 探测 SQL 确认，已按此实现）**：
   - `find_custom_prompts` 返回 `(xml, list[str])`：xml=`<Other-Infos>\n\t<content>prompt</content>\n</Other-Infos>\n`（root=Other-Infos、item=content）；日志列表是**纯 prompt 文本字符串**（LogCustomPrompt.vue `v-dompurify-html="ele"` 直接渲染，与 LogTerm 渲染 dict 不同）
   - 过滤三分支（与术语同构）：adv_id 非空 → `advanced_application = :adv`；否则 ds 非空 → `(specific_ds false/null) OR (specific_ds true AND ds非空 AND datasource_ids @> jsonb_build_array(:ds))`；否则 → `specific_ds false/null`。SELECT 只取 id/name/prompt，**xpack 原版无 question 参数、全量返回**
   - 改造点2 增强：开源版加 `question` 参数，候选集（LIMIT MAX_CANDIDATES）→ `bm25_retrieve(question, rows, name+prompt)` 取 Top-K；`KEYWORD_RETRIEVAL_ENABLED=False` 时回退全量（近似 xpack 行为）
   - exists 重名校验：`name+oid+type[+id!=self]` AND `((specific_ds true AND jsonb_len>0) OR specific_ds false)`；校验顺序 name→prompt→type→specific_ds(`i18n_data_training.datasource_assistant_cannot_be_none`)→exists(`i18n_custom_prompt.exists_in_db`)
   - update：先 `count(oid,id)`=0 → `i18n_custom_prompt.not_exists`；create 成功后 `add→flush→refresh→commit`（开源版返回 row.id，xpack 返回 None，前端不读返回值，兼容）
   - 分页 SQL：`lower(name) LIKE lower(:kw)`、order by create_time desc、page_size=max(10,·)、page clamp；外层 `jsonb_array_elements` join `core_datasource` 聚合 datasource_names + `sys_assistant(type=1)` join advanced_application_name + GROUP BY
   - Excel 4 列（按 i18n 模板键顺序推断）：name, prompt, datasource(逗号分隔), all_data_sources(Y/N)；模板/导出/上传自洽（xpack 内部列数因 RequestContext 依赖无法探测，此为唯一推断点，若现场发现不匹配再调）
   - Swagger `CustomPrompt` tag 组已存在于 `apps/swagger/i18n.py:96-98`；i18n 键 `custom_prompt_page/create_or_update/delete/export/excel_template/upload` 均已就绪；`OperationModules.PROMPT_WORDS` 已存在

#### 已创建的 7 个新文件

| 文件 | 内容 |
|---|---|
| `backend/apps/custom_prompt/__init__.py` | 空 |
| `backend/apps/custom_prompt/models/__init__.py` | 空 |
| `backend/apps/custom_prompt/models/custom_prompt_model.py` | xpack 预加载 shim + 条件双分支 `CustomPrompt` + `CustomPromptTypeEnum` + 3 个 DTO（Info/InfoResult/Search）+ 导出 `SQLModel`（供 alembic env.py 用） |
| `backend/apps/custom_prompt/curd/__init__.py` | 空 |
| `backend/apps/custom_prompt/curd/custom_prompt.py` | `get_custom_prompt_base_query / build_custom_prompt_query / execute_custom_prompt_query / page_custom_prompt / get_all_custom_prompt / _validate_custom_prompt / create / update / delete / batch_create / to_xml_string(root=Other-Infos,item=content) / find_custom_prompts(+question+bm25_retrieve)` |
| `backend/apps/custom_prompt/api/__init__.py` | 空 |
| `backend/apps/custom_prompt/api/custom_prompt.py` | 与 xpack 完全同构的 6 路由 + 新增 `GET /{id:int}`（注册在 `/template` 之后）；system_log 用 `PROMPT_WORDS`；**无 require_permissions**（xpack 也没有）；上传/导出/模板参照 terminology 写法（asyncio.to_thread + xlsxwriter + Uploader 契约返回 `{success_count, failed_count, duplicate_count, original_count, error_excel_filename}`） |

#### 已修改的 4 处既有文件（旧代码全部注释保留 + 醒目【改造标记 CUSTOM-PROMPT】）

1. `backend/apps/chat/task/llm.py`
   - 22-24 行：注释 xpack 的 `find_custom_prompts / CustomPromptTypeEnum / SQLBotLicenseUtil` 三行导入
   - apps 导入块：新增开源 `from apps.custom_prompt.curd... import find_custom_prompts`、`from apps.custom_prompt.models... import CustomPromptTypeEnum`
   - `filter_custom_prompts`（约392行起）：注释 `if SQLBotLicenseUtil.valid():`（License 开关常开，函数体保持原缩进直接执行）；两处 `find_custom_prompts` 调用注释旧版、新调用追加 `question=self.chat_question.question`；start/end_log 与调用点 482/533/784/1250 不变
2. `backend/common/audit/schemas/log_utils.py:15`：注释 xpack CustomPrompt 导入，改为 `from apps.custom_prompt.models.custom_prompt_model import CustomPrompt`（union 查询只用 id/name，兼容）
3. `backend/alembic/env.py:29`：注释 xpack SQLModel 导入，改为从开源模型模块导 SQLModel（metadata 同源）
4. `backend/apps/api.py`：新增 `from apps.custom_prompt.api import custom_prompt` + `api_router.include_router(custom_prompt.router)`（terminology 之后）

#### 验证遗留（非阻塞，上线后观察）

- **Excel 列数为推断值 4**（i18n 键序）：若现场上传旧 xpack 导出文件列数不符会报 `col_num_not_match`，届时调整 `api/custom_prompt.py` 的 `use_cols`
- DB 实测未做（密码未知）：flush/commit、JSONB contains、分页 SQL 的真实执行需现场联调
- BM25 `MIN_SCORE=0.0` 严格大于 → 问题与提示词零分词交集时召回为空（xpack 是全量注入）；`KEYWORD_RETRIEVAL_ENABLED=False` 可回退全量
- 冷启动 `import apps.api`（不先 import xpack）会撞 xpack 链路循环导入——**存量入口顺序问题**，main.py:4 已保证先 xpack 后 apps.api，非本次改造引入

#### 下午待办（按顺序）→ 已于 2026-09-24 下午全部执行完毕

1. ✅ `ruff check apps/custom_prompt apps/chat/task/llm.py common/audit/schemas/log_utils.py apps/api.py` + `alembic/env.py`：
   - `apps/custom_prompt` **All checks passed**（中途 66 处 UP045/I001 已 `ruff --fix` 清零）
   - llm.py/api.py/log_utils.py 共 58 处告警**全部为存量**（用 `ruff --diff` 核对：isort 拟议改动只动旧导入行，我的行原位不动；filter_custom_prompts 改动区域零告警；无 F821——`SQLBotLicenseUtil` 使用处与导入处均已注释）
   - `alembic/env.py` 被 ruff exclude（显式传参才检查）：8 处错误全为存量模式（多 SQLModel 重绑在改造前就存在，运行时最后一个 import 生效的行为未变）
2. ✅ `py_compile`：llm.py / env.py / api.py / log_utils.py / custom_prompt 三文件全过（注释 if 后缩进语法合法）
3. ✅ 冒烟脚本（临时目录 `C:\Users\gaohu\AppData\Local\Temp\opencode\smoke_*.py`，用 SQLBot venv 的 python）：
   - **ORDER-A**（先 xpack 后开源，= main.py 真实顺序）：复用分支生效、双方共享同一 Table 对象、双 mapper select 均可编译、DTO 接受外类枚举/字符串并归一化 ✓
   - **ORDER-B**（冷启动只导开源模型）：shim 预加载 xpack 成功、表复用 ✓、`to_xml_string` 输出与 xpack 实测格式逐字节一致（`<Other-Infos>\n\t<content>...</content>\n</Other-Infos>\n`）✓
   - **ROUTES**：6 条路径+方法与 prompt.ts 契约逐一断言；`{id:int}` 用 starlette `Route.matches` 做真实匹配（`GET /system/custom_prompt/5` 命中详情、`/template` 不被吞、POST 分页/导出/上传命中）✓
   - **import main**：完整应用装配通过（alembic 插件、fastapi_mcp、XPack core initialized successfully），`LLMService.filter_custom_prompts` 源码含 `question=self.chat_question.question` ✓
4. ✅ 冒烟期间发现并修复 1 处缺陷：pydantic 拒绝**外类枚举成员**输入（原以为按值可过，实测报 ValidationError）→ 模型文件新增 `PromptTypeField = Annotated[CustomPromptTypeEnum, BeforeValidator(_normalize_prompt_type)]`，`CustomPromptInfo`/`CustomPromptInfoResult` 的 type 字段改用之（带【改造标记】）
5. ✅ 缺陷修复（2026-09-29 下午，连真实 DB 复现坐实）：**列级 enum 跨类绑定** —— xpack 注册的 `custom_prompt.type` 列其 `SQLAlchemyEnum` 绑定的是 xpack 自己的 plain `Enum` 成员（`_valid_lookup` 只含「xpack 成员 + 字符串值」），开源侧 `CustomPromptTypeEnum` 是另一个 plain `Enum` 类，成员按身份 hash/eq 查不到字符串键 → `LookupError`，`CustomPrompt.type == <成员>` 的 where/insert 全挂（问数召回、分页、导出、上传）；读行路径不受影响（返回 xpack 成员，靠第 4 条的 `_normalize_prompt_type` 归一化）。
   修复：模型文件 `CustomPromptTypeEnum(Enum)` → **`StrEnum`**（成员同时是 str，按 hash/eq 命中字符串键，与列绑定的具体枚举类无关，读写两侧统一），带【改造标记 CUSTOM-PROMPT】成对注释，未改任何查询点。
   验证：`repro_find_custom_prompts.py` 由 **FAILED 6/6 → 0/6**；insert 我方成员/类型过滤/BM25 召回/跨类型不串行往返全过（探针已清理）；ruff 零新增、py_compile、`check_markers.py` ALL PAIRED。
5. ✅ 本记录已更新为已完成

### 改造点3：RAG 候选项 → 大模型过滤【已完成 2026-09-24】

**状态：代码完成，5 项逻辑冒烟 + 资产解析 + ruff 零新增 + import main 装配全通过。**

#### 设计定稿（调研结论）

- **挂接点（按计划两处，均为 GENERATE_SQL 主路径）**：
  1. `select_datasource()` 尾部：三 filter 之后、`init_messages()` 之前（`llm.py` 约816行，`if _error` 之前）
  2. `run_task()` 已有数据源分支：三 filter 之后、`init_messages()` 之前（`llm.py` 约1405行）
  - analysis/predict 路径（`generate_analysis`/`generate_analysis_or_predict`）本次**未挂接**（按记录计划范围），候选项暂存了但不过滤——列为后续可选扩展
- **候选项获取**：三个 filter 方法在 `end_log` 后各加 1 行暂存 `self._{terminology,data_training,custom_prompt}_candidates`（term_list/example_list/prompt_list 本来就是日志返回的结构化列表，零额外查询）
- **LLM 调用**：复用 `self.llm.stream + process_stream`（与 generate_sql 同范式），SystemPromptMessage + HumanMessage 双消息；模型即当前问数所选 ai_modal
- **重组回写**：
  - terminology：`get_base_terminology_template().format(terminologies=terminology_to_xml(subset))`（与 `get_terminology_template` 产出一致）
  - data_training：`get_base_data_training_template().format(data_training=data_training_to_xml(subset))`
  - custom_prompt：`custom_prompt_to_xml(subset)`（裸 Other-Infos XML，与 `find_custom_prompts` 产出一致）
  - 空子集 → 字段置 `''`（`sql_sys_question` 对空字段自动跳过）
- **响应解析**：`extract_nested_json` 取首个合法 JSON（支持对象/数组），期望 `{"retain": [全局编号]}`；非法/缺失 → **保留全部候选项**并记 note（宁可不过滤不可误删）
- **日志**：新增 `OperationEnum.LLM_CONTEXT_FILTER='14'`；`chat_log.operate` 为 `native_enum=False` 且历史 '7'-'13' 均无 CHECK 迁移 → **无需 DDL**；`start_log` 即写入 system+human 两条消息、`end_log` 追加 ai 消息（summary JSON：counts/retained/dropped/note），**消息结构与 LogWithAi.vue 期望的 `[{type,content}]` 数组对齐，前端零组件改动**；token_usage 正常累计展示
- **失败兜底**：整段 try/except，异常 → 保留原始候选项 + `SQLBotLogUtil.error` + 日志追加错误消息 + `trigger_log_error`，**不抛出、不阻断问数**
- **成本控制**：`LLM_CONTEXT_FILTER_ENABLED=True`（默认开，进 lowercase_bool 校验器）+ `LLM_CONTEXT_FILTER_MIN_CANDIDATES=3`（候选项总数 <3 直接跳过，不调 LLM）
- **索引映射**：三类候选拼全局连续编号（sections：`[术语]/[SQL示例]/[自定义提示词]`），`index_map=[(category, local_i)]`；条目文本截断（术语描述/SQL 500、问题 200、提示词 500）防 prompt 过长

#### 落地文件清单（全部带【改造标记 LLM-CONTEXT-FILTER】）

| 文件 | 改动 |
|---|---|
| `backend/common/core/config.py` | 新增 `LLM_CONTEXT_FILTER_ENABLED`/`LLM_CONTEXT_FILTER_MIN_CANDIDATES` + ENABLED 加入 `lowercase_bool` 校验器 |
| `backend/apps/chat/models/chat_model.py` | `OperationEnum` 新增 `LLM_CONTEXT_FILTER = '14'` |
| `backend/templates/template.yaml` | `template:` 根下新增 `llm_context_filter` 提示词模板（`{{"retain"...}}` 双花括号转义） |
| `backend/apps/chat/task/llm.py` | ① 导入 `custom_prompt_to_xml/data_training_to_xml/terminology_to_xml/get_base_*_template/get_base_template`；② 三个 filter 各 +1 行暂存候选；③ 新增 `llm_filter_context()`（约130行）；④ 两处挂接调用 |
| `frontend/src/i18n/{zh-CN,zh-TW,en,ko-KR}.json` | `chat.log.LLM_CONTEXT_FILTER` 日志标题（标题走 `t('chat.log.'+operate)`，operate 由后端序列化为枚举 name） |

> **改造标记例外（2026-09-29 补记）**：`frontend/src/i18n/*.json` 是纯 JSON，**不支持注释**，
> 无法按 `【改造标记 X】↓ 起始 / 【改造标记 X】↑ 截止` 规范打成对标记。
> 这 4 个文件的改造范围以本表对应行为准（每个语言文件仅新增 `chat.log.LLM_CONTEXT_FILTER` 1 行，第 816 行）；
> 其余所有代码文件的标记已由 `%LOCALAPPDATA%\Temp\opencode\check_markers.py` 校验通过（17 文件 94 个标记，全部成对，09-29 下午复跑）。

#### 验证结果（2026-09-24 下午）

1. `ruff check llm.py/chat_model.py/config.py`：llm.py 56 处=基线（新代码区域 470-610 零告警，3 处 `List[...]` 已改内建泛型清零）；chat_model/config 告警全为存量（改动行无告警）
2. `py_compile` 三文件通过
3. `smoke_ctx3_assets.py`：template.yaml 解析、`llm_context_filter.format()` 输出含问题/候选/`{"retain"}`、相邻键（sql/terminology/data_training）完好；前端 4 语言 JSON 解析且 key 存在
4. `smoke_ctx3_logic.py` 5 用例全过（mock LLM + monkeypatch start/end_log，不依赖 DB）：
   - CASE1 候选 <3 跳过（不调 LLM 不写日志）
   - CASE2 retain[0,2] → 正确重组回写（terminologies 含 GDP 不含 CPI、data_training 含 gdp 不含 cpi、custom_prompt 清空）、日志 system+human+ai 结构、summary counts/retained/dropped 精确、token_usage 传递、system 含三段编号候选
   - CASE3 LLM 返回不可解析 → 保留全部 6 候选、note 记录、不触发 error 日志
   - CASE4 LLM 抛异常 → 三字段保持过滤前原值、日志 ai 消息含 keep original candidates、`trigger_log_error` 触发
   - CASE5 配置开关关闭 → 跳过
5. `import main` 最终装配：2 处挂接、`llm_filter_context` 方法、枚举 '14'、配置默认值、yaml 模板 key 全部确认；XPack core 初始化正常

#### 后续可选扩展（未做，非阻塞）

- analysis/predict 路径挂接 `llm_filter_context`（各 +1 行即可，注意它们没有 data_training 候选）
- 前端专用日志组件（当前走 LogWithAi 通用渲染已可用）

---

## 四、关键文件索引（速查）

| 用途 | 路径 |
|---|---|
| BM25 关键词检索工具（改造点1 新增） | `backend/common/utils/keyword_retrieval.py` |
| custom_prompt 模型（改造点2 新增） | `backend/apps/custom_prompt/models/custom_prompt_model.py` |
| custom_prompt curd+召回（改造点2 新增） | `backend/apps/custom_prompt/curd/custom_prompt.py` |
| custom_prompt 路由（改造点2 新增） | `backend/apps/custom_prompt/api/custom_prompt.py` |
| 大模型上下文过滤（改造点3） | `backend/apps/chat/task/llm.py` `llm_filter_context()` + 两处挂接 + 三 filter 暂存行 |
| 过滤配置（改造点3 新增） | `backend/common/core/config.py` `LLM_CONTEXT_FILTER_*` |
| 过滤日志枚举（改造点3 新增） | `backend/apps/chat/models/chat_model.py` `OperationEnum.LLM_CONTEXT_FILTER='14'` |
| 过滤提示词模板（改造点3 新增） | `backend/templates/template.yaml` `template.llm_context_filter` |
| 过滤日志前端标题（改造点3 新增） | `frontend/src/i18n/{zh-CN,zh-TW,en,ko-KR}.json` `chat.log.LLM_CONTEXT_FILTER` |
| 术语 curd（ILIKE+向量+模板） | `backend/apps/terminology/curd/terminology.py`（851-929 检索，975-986 模板） |
| SQL示例 curd | `backend/apps/data_training/curd/data_training.py`（531-575 检索，619-631 模板） |
| 问数主流程 | `backend/apps/chat/task/llm.py`（372/397/441 三个 filter，470 llm_filter_context，1405/816 挂接，init_messages，run_task） |
| ChatQuestion 模型/模板注入 | `backend/apps/chat/models/chat_model.py`（35-51 日志枚举，258-301 sql_sys_question，430-454 消息类型） |
| 聊天入口 | `backend/apps/chat/api/chat.py`（245 question_answer，346 stream_sql） |
| 提示词模板 | `backend/templates/template.yaml`（2/5/8 llm_context_filter/332-342/586-647） |
| 配置 | `backend/common/core/config.py`（102-110 embedding，135-141 BM25，143-151 LLM-CONTEXT-FILTER + bool 校验器） |
| custom_prompt DDL | `backend/alembic/versions/046_add_custom_prompt.py`、`069_term_custom_prompt.py` |
| xpack 导入替换点（改造点2 已完成） | `backend/apps/chat/task/llm.py:22-24`、`backend/alembic/env.py:29`、`backend/common/audit/schemas/log_utils.py:15`（均已注释旧导入） |
| 前端提示词 API | `frontend/src/api/prompt.ts`、`frontend/src/views/system/prompt/index.vue`、`frontend/src/views/chat/execution-component/LogCustomPrompt.vue`、`frontend/src/views/system/excel-upload/Uploader.vue` |
| 执行明细日志组件 | `frontend/src/views/chat/ExecutionDetails.vue`（operate_key 分发）、`execution-component/LogWithAi.vue`（通用）、`frontend/src/api/chat.ts:347`（t('chat.log.'+operate)） |
| API 注册 | `backend/apps/api.py`（已注册开源 router）、`backend/main.py:245/253`（开源先于 xpack 注册） |
| 开源 CRUD 参照 | `backend/apps/terminology/api/terminology.py`、`backend/apps/data_training/api/data_training.py` |
| xpack 反射探测位置 | `...\.venv\Lib\site-packages\sqlbot_xpack\custom_prompt\`（.pyd 无源码） |
| 冒烟脚本 | `C:\Users\gaohu\AppData\Local\Temp\opencode\smoke_{order_a,order_b,routes,ctx3_assets,ctx3_logic}.py` |
| 依赖 | `backend/pyproject.toml`（无 jieba；ruff select=E,W,F,I,B,C4,UP,ARG001，ignore=E501,B008,W191,B904，exclude=alembic） |

---

## 五、明日继续事项

1. ~~**改造点1**（BM25 关键词检索）~~ ✅ 已完成（2026-09-24）
2. ~~**改造点2**（自定义提示词开源实现）~~ ✅ 已完成（2026-09-24 全天）
3. ~~**改造点3**（LLM 上下文过滤层）~~ ✅ 已完成（2026-09-24 下午）
4. **三点改造全部收官。** 剩余为上线/联调阶段观察项：
   - [ ] DB 实联调：custom_prompt CRUD/分页/批量/Excel 全链路（本地 DB 密码未知未连库）、问数全链路过一遍确认过滤生效
   - [ ] Excel 4 列若与现场旧导出文件不符 → 调 `apps/custom_prompt/api/custom_prompt.py` 的 `use_cols`
   - [ ] 可选：analysis/predict 挂接 `llm_filter_context`（各 +1 行）
   - [ ] 可选：`LLM_CONTEXT_FILTER_MIN_CANDIDATES`/prompt 文案按现场 token 成本调优
