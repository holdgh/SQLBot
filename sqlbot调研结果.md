我先浏览项目关键文件，从整体了解项目后再逐一分析9个方面。

这是 DataEase 开源的 SQLBot 项目。继续深入后端应用结构与前端分析。

grep 工具在当前环境不可用，改用 ls/read 继续核查。

分析已完成。以下基于对仓库代码的直接核查（README、`backend/pyproject.toml`、`backend/main.py`、`backend/apps/*`、`backend/apps/db/constant.py`、`backend/templates/template.yaml`、`frontend/src/router`、`frontend/package.json`、`g2-ssr`、`installer`、`docker-compose.yaml` 等）给出 9 个方面的结论。

---

## 1. 产品定位
本项目是飞致云 DataEase 团队开源的 **SQLBot —— 基于大语言模型 + RAG 的智能问数（ChatBI）系统**（版本 1.10.1）。核心定位是"对话式数据分析"：用户用自然语言提问，系统生成 SQL 查询数据库，并产出结论与图表，支持进一步智能分析（`analysis`/`predict` 能力）。它与示例竞品（本地优先的"多数据库管理 + SQL 工作区 + AI 助手"）有明显差异：**SQLBot 面向"问数"而非"管库"**，目标是让业务/分析人员直接对话取数，不存在面向开发者的手写 SQL 工作区、智能补全 IDE 类功能；数据库管理是支撑性前置能力。

## 2. 产品形态
- **Web 端**：Vue 3 SPA（`frontend/`），路由覆盖登录、数据问答（`/chat`）、仪表板（`/dashboard`、`/canvas`、预览）、数据源/表管理（`/dsTable`）、系统管理（模型、成员、权限、术语库、训练、提示词、嵌入管理、外观、参数、平台、审计）、以及助手嵌入页（`/assistant`、`/embeddedPage`、`/embeddedCommon`）。
- **Docker 部署**：`docker-compose.yaml` + `installer/`（`install.sh`、`sctl`、`sqlbot/docker-compose.yml`、`conf`），镜像 `dataease/sqlbot`，暴露 8000（Web/API）与 8001（MCP）两端口，依赖 PostgreSQL 存储与本地目录卷。
- **MCP 服务**：`main.py` 中基于 `FastApiMCP` 挂载独立 `mcp_app`（端口 8001，`mcp.setup_server()`），开放 7 个操作：`mcp_datasource_list`、`mcp_model_list`、`mcp_question`、`mcp_start`、`mcp_assistant`、`mcp_ws_list`、`access_token`，可嵌入 n8n/Dify/MaxKB/DataEase 等。
- **Web 嵌入/弹窗嵌入**：仓库根 `embedded.html`、`sqlbot-assistant-demo.html` 及前端嵌入页。
- **图表 SSR 服务**：`g2-ssr/`（Node.js + `@antv/g2-ssr` + `node-canvas` + pm2/`ecosystem.config.js`）用于服务端渲染图表图片。
- **无桌面端、无 CLI**：与示例形态（桌面 + Web + Docker + CLI + MCP）相比缺少前两者。

## 3. 底层技术实现路径
- **连接数据源并读取元数据**：创建数据源后同步表/字段/注释到 `core_table`/`core_field`（`apps/datasource/crud/datasource.py::sync_table`、`apps/db/db.py::get_tables/get_fields`），并异步生成表/数据源/术语/训练样本的向量（`apps/datasource/embedding/`、`common/utils/embedding_threads.py`，pgvector 存储）。
- **问数主链路**（`apps/chat/task/llm.py::LLMService`）：用户提问 → 基于向量检索召回表结构（M-Schema）、术语、SQL 示例 → 按 `backend/templates/template.yaml` 组装提示词（含 `<SQL-Generation-Process>`、数据量限制、多表限定、标识符保真等强制规则）→ LangChain 调 LLM 生成"SQL + 图表类型 + 标题"JSON → `exec_sql` 执行 SQL（前置行/列权限过滤）→ 结果格式化 → 再走一次 LLM 生成图表配置/结论 → 前端渲染，`g2-ssr` 可出图；执行出错时把 error-msg 回传让模型自纠重生成。
- **运行与迭代**：每次问答按步骤落 `ChatLog`（耗时、token 用量），支持 regenerate、多轮上下文、推荐问题；`analysis`（智能分析）/`predict`（指标预测）；结果可导出 Excel（`/chat/record/{id}/excel/export/{chat_id}`）。
- **数据导入**：Excel/CSV 作为数据源（`type=excel`），落地为 PostgreSQL 表再问答。

## 4. 语义层/业务知识机制
**不提供完整企业语义层**，而是用四类载体组合近似实现"业务理解"：
- 数据库元数据：表/字段注释 + `custom_comment` 自定义注释、表关系（`table_relation` JSONB）；
- 术语库（`apps/terminology`）：词/同义词/描述/计算公式，可按数据源限定（`specific_ds`），向量检索后注入提示词；
- 数据训练/SQL 示例（`apps/data_training` + `templates/sql_examples/*.yaml` 12 个引擎模板）：question↔SQL/解释 样本，用于校准生成；
- 自定义提示词（`sqlbot_xpack.custom_prompt`）、系统参数/变量、问答历史。
检索与注入由 RAG（sentence-transformers + pgvector）统一完成，结构上仍是"元数据+示例级"的知识补给，而非指标/维度模型等企业语义层。

## 5. 数据源支持
内置 13 种（`apps/db/constant.py` 的 `DB` 枚举）：**Excel/CSV、AWS Redshift、ClickHouse、达梦 DM、Apache Doris、Elasticsearch、Kingbase、Microsoft SQL Server、MySQL、Oracle、PostgreSQL、StarRocks、Apache Hive**。连接分两类：SQLAlchemy 驱动（excel/ck/sqlServer/mysql/oracle/pg）与原生 Python 驱动（redshift/dm/doris/es/kingbase/starrocks/hive）。可扩展性较强：配置支持 `driver`、`extraJdbc`、`dbSchema` 等类 JDBC 参数，且每个引擎有独立 YAML 模板与方言（`sqlglot`），可通过增加模板扩展新引擎。**与示例（40+，含 MongoDB/Redis/SQLite/Snowflake/BigQuery/Trino）相比内置列表更少且更聚焦分析型库与国产库**，未覆盖文档型/缓存型数据库。

## 6. 技术栈
- **后端**：Python 3.11 + FastAPI + SQLModel/SQLAlchemy + Alembic + PostgreSQL（业务库，pgvector 向量）+ Redis（`fastapi-cache2` 缓存）+ JWT/passlib(bcrypt) + LangChain 0.3 / LangGraph + sentence-transformers（本地 embedding，可选 torch CPU/CU128）+ SQLGlot（方言解析）+ SQLParse + pandas + 多数据库驱动（pymysql、pyhive、oracledb、clickhouse-sqlalchemy、redshift-connector、dmpython、elasticsearch 等）；**关键商业闭源扩展 `sqlbot-xpack`**（pip 依赖，含 license 校验、自定义提示词、高级权限模型）。
- **前端**：Vue 3 + TypeScript + Vite 6 + Pinia + Vue Router + Element Plus + `@antv/g2`（图表）/`@antv/s2`（表格）/`@antv/x6`（画布类，仪表板编辑器）+ TinyMCE + markdown-it + highlight.js + DOMPurify + vue-i18n（zh-CN/zh-TW/en/ko-KR）。
- **图表 SSR**：Node.js + `@antv/g2-ssr` + `node-canvas` + pm2。
- **部署**：Docker/Dockerfile/Dockerfile-base/docker-compose + 一键安装脚本（含 1Panel 应用商店）。

## 7. 可视化与输出
- **问答内嵌可视化**：回答由 LLM 按规则选定图表类型（table/column/bar/line/pie，见 template.yaml 步骤 7），前端用 G2 渲染图表、S2 渲染结果表，同时展示生成 SQL、执行耗时与 token；支持"live"数据接口（`record/{id}/data_live`）。
- **仪表板**：`apps/dashboard` + 前端 `DashboardEditor/预览/嵌入`，可将问答结果图表组织成仪表板画布并分享。
- **服务端出图**：`g2-ssr` 将图表配置渲染为图片（用于导出/分享场景）。
- **数据导入导出**：Excel 导出（xlsxwriter）、Excel/CSV 导入建表（openpyxl/calamine/xlrd）。
- **表结构可视化**：表/字段预览、表关系（`table_relation`）管理界面。
- 结论：可视化以"问答附图表 + 仪表板"为主线，无独立报表设计器；ER 图为轻量的表关系视角而非建模画布。

## 8. 附加功能
- **问答运营**：多轮会话历史、会话重命名、推荐问题（`ds_recommended_problem`）、最近问题、regenerate 重生成、步骤级日志与 token 用量、智能分析（analysis/thinking）与指标预测（predict）。
- **校准能力**：SQL 示例训练（data_training）、术语库、自定义提示词、系统变量与参数配置。
- **权限与安全**：工作空间（oid）级资源隔离、成员管理、细粒度行权限过滤（`row_permission.py`）、列/字段权限（`permission.py`）、API Key、LDAP 认证、JWT + SECRET_KEY、Host 头校验中间件、CORS 白名单、数据源密码与模型密钥 AES 解密存储（`common/utils/crypto.py`、启动时密钥迁移）。
- **审计**：操作日志 + 系统审计视图（audit 模块）。
- **开放集成**：MCP（7 操作）、Web 嵌入/弹窗嵌入/演示页、助手（Assistant/`appearance` 外观定制）承载第三方应用。
- **注意**：示例中的"智能补全、SQL 格式化"在本项目中体现为**模型生成 SQL 时按提示词规则输出（sqlparse/sqlglot 处理）并可复制/导出**，而非开发者向的手写 SQL 编辑器；工作区（`views/work`）仅是数据源入口卡片。

## 9. 重点调研结论
- **本质定位**：SQLBot 是**面向业务流程的 ChatBI/智能问数产品**（DataEase 生态一员），不是面向开发者的"多数据库管理 + SQL 工作区"工具；对"多人数据库管理客户端"类产品可按竞品思路借鉴其**开箱即用的 Text-to-SQL 效果**而非形态。
- **最值得借鉴的点**：① 多数据源统一接入 + YAML 模板化/方言扩展机制；② RAG 质量工程：M-Schema 表结构注入 + 术语库（同义词/公式）+ SQL 示例校准 + 自定义提示词，配合步骤式强制检查提示词（数据量限制、标识符保真、多表限定）显著提升生成稳定性；③ 模型层可插拔（OpenAI 兼容协议覆盖主流厂商 + Azure/vLLM/本地 embedding），密钥加密存储；④ MCP 与 Web 嵌入双通道，快速挂载到 n8n/Dify/MaxKB/DataEase 等外部应用；⑤ 安全工作空间隔离 + 行/列级权限 + 审计日志。
- **社区版边界（需与商业版区分）**：核心开源，但 `sqlbot-xpack`（闭源 pip 包）承载了**许可校验、自定义提示词、部分高级权限能力**；社区版按本地 Docker 单实例设计、多工作空间（oid）属于租户隔离而非 SaaS 云能力，**团队在线协作、企业级管控、云端托管属商业版范畴**，评估时须以 xpack 授权边界为准。
- 总体：**不面向业务小白提供全自助 ChatBI**，而是"配置数据源+维护术语/示例后，由用户在问答/仪表板中取数分析"的半托管模式——与示例产品的差异可概括为"**先治理知识，再对话问数**"。