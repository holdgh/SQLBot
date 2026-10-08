# 个人理解

```text
开源sqlbot的问数处理逻辑：事先维护术语、SQL示例、自定义提示词。用户问题进来，基于关键词检索【实际上是模糊查询】、向量检索获取与用户问题相关的术语、SQL示例、自定义提示词，然后基于预设的提示词模板，填充”用户问题、术语、SQL示例、自定义提示词、数据源信息、相关的表结构信息“，得到SQL生成提示词和图表信息生成提示词，先后分别给到大模型生成SQL语句、执行SQL语句获得查询结果、生成图表信息，然后给到前端，渲染出问数答案【图表结果】。
```

你对 SQLBot（开源智能问数系统）的理解整体是准确的，而且你描述的流程实际上已经覆盖了当前很多 Text2SQL 产品的核心链路。

不过，从企业级智能问数角度看，这套方案属于 **“RAG增强型Text2SQL”**，它解决了传统 Text2SQL 的一部分问题，但仍然存在一些工程上的不足。我下面从：

1. SQLBot当前方案本质
2. 每个环节的作用
3. 它解决了什么问题
4. 还存在哪些不足
5. 与我们前面讨论的企业级智能问数架构对比

几个方面展开。

---

# 一、SQLBot整体流程复述（架构抽象）

你描述的流程可以抽象为：

```text
                  用户问题
                     |
                     ↓
            问题理解 / 检索增强
                     |
     ---------------------------------
     |              |                |
  术语库        SQL示例库        自定义Prompt
     |              |                |
     ---------------------------------
                     |
              Prompt组装
                     |
                     ↓
              LLM生成SQL
                     |
                     ↓
              SQL执行
                     |
                     ↓
              查询结果
                     |
                     ↓
          LLM生成图表配置
                     |
                     ↓
              前端可视化
```

本质：

> 利用企业已有知识增强LLM生成SQL能力。

---

# 二、各模块详细分析

---

# 1. 术语库（Term）

## 作用

解决：

> 用户语言 ≠ 数据库语言

的问题。

例如：

用户：

> “游客量”

数据库：

```sql
tourist_num
```

或者：

```sql
visitor_count
```

术语库维护：

```json
{
 "游客量":{
    "meaning":"旅游接待人数",
    "field":"visitor_count",
    "aliases":[
       "客流",
       "游客人数",
       "旅游人数"
    ]
 }
}
```

---

## SQLBot处理方式

用户问题：

> 上海五一游客量是多少？

关键词/向量检索：

召回：

```
游客量
客流
接待人数
```

然后放入Prompt：

```
相关业务术语：

游客量：
表示旅游接待人数，
对应字段visitor_count
```

帮助LLM理解。

---

## 优点

简单有效。

尤其对于：

* 中文业务词
* 行业黑话
* 缩写

效果明显。

---

## 不足

这里容易产生一个误区：

很多人认为：

> 有术语库 = 指标体系

实际上不是。

术语库只是：

```
词语 → 解释
```

而指标体系应该是：

```
指标
 |
 |--定义
 |--计算公式
 |--来源表
 |--过滤条件
 |--权限
 |--负责人
```

例如：

游客量：

术语：

```
游客量=visitor_count
```

指标中心：

```
游客量:

定义:
统计周期内去重游客数量

公式:
count(distinct user_id)

来源:
fact_tourism_order

时间字段:
visit_date

默认聚合:
sum

负责人:
旅游业务部门
```

二者不是一个层级。

---

# 2. SQL示例库

这是SQLBot方案中非常关键的一部分。

---

## 作用

解决：

> LLM不知道应该怎么查询

例如：

用户：

> 查询今年各城市游客排名

如果没有示例：

LLM可能生成：

```sql
select city,count(*)
```

但是实际上：

可能需要：

```sql
select 
 city,
 sum(visitor_num)
from tourism
where year=2026
group by city
order by sum(visitor_num) desc
```

---

SQL示例提供：

```text
问题:
查询各城市游客量排名

SQL:
select city,sum(visitor_num)
...
```

LLM通过few-shot学习。

---

## 本质

这其实就是：

# Example-based Prompting

也就是：

动态few-shot。

---

## 优点

对于固定业务：

效果非常好。

例如：

旅游行业：

* 同比
* 环比
* TOPN
* 排名
* 趋势

大量问题具有模式。

---

## 不足

SQL示例维护成本高。

例如：

1000张表。

需要多少示例？

问题：

如何覆盖？

---

所以企业级会进一步发展：

SQL示例 → SQL模板

例如：

同比模板：

```text
当前周期
去年同期
增长率
```

自动生成。

---

# 3. 自定义Prompt

这个比较容易理解。

例如：

业务要求：

```
查询游客量时必须过滤：

status=1
deleted=0
```

或者：

```
收入字段禁止直接sum，
必须使用订单金额字段
```

这些规则放Prompt。

---

## 本质

这是：

# 业务规则注入

---

## 问题

Prompt不是强约束。

例如：

你写：

```
不要查询xxx字段
```

LLM可能仍然生成。

所以：

重要规则：

不要只放Prompt。

应该：

Prompt + 程序校验。

---

# 4. 表结构信息

这是Text2SQL必须的。

例如：

提供：

```sql
table tourism_flow

columns:

date
city
visitor_num
```

LLM才能生成SQL。

---

但是这里有一个关键问题：

## Schema太大怎么办？

例如：

企业：

5000张表

10万个字段。

全部塞Prompt：

不可行。

所以必须：

Schema Retrieval。

也就是：

先找相关表。

---

SQLBot这里实际上也是RAG：

```
用户问题

↓

表结构向量检索

↓

相关schema

↓

Prompt
```

---

# 三、SQLBot真正的核心：RAG增强Text2SQL

整体可以表示：

```
                    用户问题
                       |
                       ↓
              Query Understanding
                       |
                       ↓
              Knowledge Retrieval
                       |
       --------------------------------
       |              |               |
    Term          SQL Example      Schema
       |              |               |
       --------------------------------
                       |
                       ↓
                 Prompt Assembly
                       |
                       ↓
                      LLM
                       |
                       ↓
                      SQL
```

这就是：

# Retrieval Augmented Text2SQL

---

# 四、这个方案解决了哪些传统Text2SQL问题？

## 问题1：字段不知道

解决：

schema retrieval

---

## 问题2：业务词不知道

解决：

术语库

---

## 问题3：SQL写法不知道

解决：

SQL example

---

## 问题4：行业规则不知道

解决：

custom prompt

---

所以相比：

```
用户
 ↓
LLM
 ↓
SQL
```

提升巨大。

---

# 五、但是它仍然存在几个关键问题

这也是你之前讨论“智能问数可靠性”的核心。

---

# 问题1：LLM仍然负责业务理解

例如：

用户：

> 上海今年五一游客增长情况

LLM需要判断：

增长：

* 同比？
* 环比？
* 比去年同期？
* 比节前？

如果没有明确规则：

仍然可能错。

---

# 改进

增加：

## 意图解析层

先生成：

```json
{
 "metric":"游客量",
 "analysis":"同比",
 "period":"劳动节"
}
```

再进入SQL生成。

---

# 问题2：SQL正确 ≠ 数据正确

例如：

SQL：

```sql
select sum(visitor_num)
```

语法正确。

但是：

业务要求：

```sql
count(distinct visitor_id)
```

结果完全错误。

---

这就是：

# 指标口径问题

SQLBot靠术语库解决不了。

---

需要：

# Metric Layer

---

# 问题3：计算逻辑依然交给LLM

例如：

用户：

> 增长率多少？

LLM可能生成：

```sql
(current-last)/last
```

也可能：

```sql
current/last
```

---

更可靠：

SQL只负责取数据：

```json
{
"current":100,
"last":80
}
```

程序计算：

```python
25%
```

---

# 问题4：分析能力不足

SQLBot：

```
查询
↓
图表
```

但是：

用户：

> 为什么下降？

需要：

* 异常检测
* 归因分析
* 多因素分析

单纯Text2SQL无法解决。

---

# 六、和我们之前讨论的企业级架构对应关系

你可以这样理解：

| SQLBot能力 | 企业级能力         |
| -------- | ------------- |
| 术语库      | 语义层           |
| SQL示例    | Few-shot / 模板 |
| Prompt   | 规则注入          |
| Schema检索 | 元数据检索         |
| LLM生成SQL | SQL Agent     |
| 执行SQL    | 数据执行层         |
| 图表生成     | 表达层           |

缺少：

| 能力   | 原因     |
| ---- | ------ |
| 指标中心 | 业务治理不足 |
| 计算引擎 | 依赖LLM  |
| 分析引擎 | 偏查询    |
| 权限体系 | 需企业扩展  |
| 可信校验 | 需二次建设  |

---

# 七、如果让我基于SQLBot改造成企业级智能问数，我会这样改

## 第一阶段：保留SQLBot核心

继续使用：

* 术语库
* SQL示例
* schema检索
* Prompt增强

---

## 第二阶段：增加语义解析层

新增：

```
用户问题

↓

Intent Parser

↓

结构化Query
```

例如：

```json
{
"metric":"游客量",
"time":"五一",
"compare":"同比"
}
```

---

## 第三阶段：增加指标中心

替代简单术语。

---

## 第四阶段：SQL生成改为DSL

不要：

```
LLM → SQL
```

改：

```
LLM → Query DSL → SQL
```

---

## 第五阶段：增加计算引擎

例如：

同比：

Python计算。

---

## 第六阶段：增加分析Agent

支持：

* 为什么
* 趋势
* 预测
* 异常

---

# 八、总结评价你的理解

你对SQLBot流程的理解：

> “关键词检索/向量检索获取术语、SQL示例、自定义Prompt，然后组装提示词让LLM生成SQL”

这个判断：

✅ 正确
✅ 抓住了RAG增强Text2SQL核心
✅ 比传统NL2SQL方案成熟

但是需要进一步升级认识：

SQLBot解决的是：

> **让LLM更容易生成正确SQL**

而企业级智能问数需要解决：

> **让系统输出可信的数据分析结果**

二者差异：

|    | SQLBot   | 企业级问数  |
| -- | -------- | ------ |
| 目标 | 生成SQL    | 业务决策支持 |
| 核心 | Prompt增强 | 语义治理   |
| 知识 | 术语+示例    | 指标体系   |
| 计算 | SQL/LLM  | 计算引擎   |
| 分析 | 弱        | 强      |
| 可信 | 有限       | 强校验    |

---

结合你之前正在做的**文旅智能问数 Agent**，我认为 SQLBot 的设计非常值得借鉴，但不要直接照搬。更适合作为：

> **数据查询执行Agent**

嵌入到你之前设计的“文旅数据分析规划Agent → SQL生成 → 计算 → 分析 → 总结”的整体链路中。你之前提出的“先规划分析任务，再执行SQL，再代码计算，最后LLM总结”的方向，实际上已经比传统SQLBot更接近下一代智能问数架构。

# 追问：开源sqlbot中看起来并没有schema检索

你这个纠正是对的，我前面的表述需要修正一下。

如果严格按照你描述的 SQLBot 实现流程来看：

> 关键词检索（模糊查询）、向量检索 → 术语、SQL示例、自定义提示词 → Prompt组装（用户问题、术语、SQL示例、自定义提示词、数据源信息、相关表结构信息） → LLM生成SQL

这里的**表结构信息（schema）并不是通过检索得到的**，而是作为已经配置的数据源元信息直接注入 Prompt。

我之前把“企业级 Text2SQL 常见做法”中的 schema retrieval 混入了 SQLBot 描述，这是两个层面的概念，需要区分。

---

# 一、SQLBot实际架构更准确的抽象

根据你的描述，SQLBot更接近：

```text
                         用户问题
                             |
                             ↓
                   知识增强检索层
                             |
          ---------------------------------
          |               |               |
       术语检索        SQL示例检索       Prompt检索
          |               |               |
          ---------------------------------
                             |
                             ↓
                    Prompt上下文组装
                             |
          ---------------------------------
          |
          | 用户问题
          | 业务术语
          | SQL案例
          | 自定义规则
          | 数据源信息
          | 表结构信息(schema)
          |
          ↓
                         LLM
                          |
                          ↓
                         SQL
                          |
                          ↓
                       SQL执行
                          |
                          ↓
                     结果+图表配置
                          |
                          ↓
                         前端
```

其中：

* 术语：动态检索
* SQL示例：动态检索
* 自定义Prompt：动态检索
* schema：静态加载/配置加载

这和我之前说的：

> schema retrieval

不是一回事。

---

# 二、为什么 SQLBot 不一定需要 schema retrieval？

这是一个很值得分析的问题。

因为很多 Text2SQL 系统都会遇到：

> 数据库表太多，schema太大，无法全部塞Prompt。

于是才引入：

```text
用户问题
 ↓
schema embedding检索
 ↓
相关表
 ↓
LLM
```

但是 SQLBot 可能采用了另外一种假设：

## 假设：

> 用户配置的数据源规模有限，或者用户主动选择数据范围。

例如：

一个企业配置：

```
数据源：
上海文旅数据库

表：
旅游咨询中心数据
景区客流数据
游客来源数据
```

只有几十张表。

那么：

直接把：

```sql
CREATE TABLE xxx
字段说明
```

放入Prompt：

完全可接受。

---

# 三、这其实反映了两种不同路线

## 路线1：SQLBot这种“小规模增强型Text2SQL”

架构：

```text
固定schema
+
术语RAG
+
SQL案例RAG
+
Prompt增强
+
LLM
```

适合：

* 单业务库
* 表数量有限
* 数据治理较好
* BI问数场景

优点：

简单。

效果容易调。

---

缺点：

扩展性有限。

例如：

5000张表：

Prompt直接爆炸。

---

# 路线2：企业级Text2SQL

架构：

```text
用户问题

↓

意图识别

↓

schema检索

↓

指标检索

↓

SQL案例检索

↓

SQL生成

```

例如：

企业：

```
ODS:
3000张表

DWD:
2000张表

ADS:
500张表
```

不可能全部塞进去。

必须：

先找相关领域。

---

# 四、不过这里还有一个更深的问题

即使 SQLBot 把 schema 放 Prompt：

它解决的是：

> “模型知道有哪些字段”

但没有解决：

> “模型知道应该使用哪个业务指标”

这是两个不同问题。

举例：

数据库：

```
tourism_statistics

字段：

visitor_num
visitor_count
person_num
order_user_num
```

用户：

> 游客量多少？

Schema告诉LLM：

有这些字段。

但是：

哪个才是游客量？

schema不知道。

---

所以：

真正企业级需要：

## Schema层

解决：

> 数据库有什么

*

## Metric层

解决：

> 业务应该用什么

例如：

指标中心：

```
指标：
游客量

定义：
统计周期内接待游客人数

字段：
tourism_statistics.visitor_count

计算：
sum(visitor_count)

过滤：
status=1
```

---

# 五、结合你之前文旅问数场景，我认为SQLBot当前方案适合放在哪？

结合你之前设计：

> 文旅数据分析规划Agent → SQL生成 → 数据计算 → 分析 → 总结

我认为 SQLBot对应的位置应该是：

```
用户问题
   |
   ↓
文旅分析规划Agent
   |
   | 输出：
   | - 查询指标
   | - 时间范围
   | - 分析类型
   | - 维度
   |
   ↓
SQLBot能力模块
   |
   | 负责：
   | - 术语匹配
   | - SQL生成
   | - 查询执行
   |
   ↓
计算分析Agent
   |
   ↓
LLM总结
```

也就是说：

SQLBot更像：

# Query Agent

而不是完整的：

# Data Analyst Agent

---

# 六、SQLBot方案还可以怎么增强？

如果基于 SQLBot 改造，我认为优先级如下：

---

## 第一优先级：增加指标中心

比 schema retrieval 更重要。

增加：

```
metric
 |
 |--名称
 |--别名
 |--定义
 |--字段
 |--计算规则
 |--过滤条件
```

---

## 第二优先级：增加schema检索

当数据规模扩大：

增加：

```
表描述
字段描述
业务领域
```

向量化。

例如：

用户：

> 五一期间游客来源情况

召回：

```
游客来源表
节假日表
区域维度表
```

---

## 第三优先级：SQL生成前增加DSL

不要：

```
LLM → SQL
```

改：

```
LLM
 ↓
Query Plan
 ↓
SQL
```

例如：

```json
{
 "analysis":"ranking",
 "metric":"游客量",
 "dimension":"省份",
 "time":"2026劳动节"
}
```

---

## 第四优先级：增加计算引擎

例如：

SQL返回：

```
今年:
100万

去年:
80万
```

程序：

```
增长率=25%
```

LLM只描述。

---

# 七、总结修正

你的观察：

> “SQLBot中看起来并没有schema检索”

是正确的。

更准确地说：

| 能力         | SQLBot |
| ---------- | ------ |
| 术语检索       | 有      |
| SQL案例检索    | 有      |
| Prompt检索   | 有      |
| schema注入   | 有      |
| schema动态检索 | 未必有    |
| 指标中心       | 通常没有   |
| 计算引擎       | 弱      |
| 分析Agent    | 弱      |

所以 SQLBot 属于：

> **RAG增强型 Text2SQL 工具**

而不是：

> **完整企业级智能问数Agent**

这也和你之前设计的文旅问数Agent形成一个很好的互补关系：
你的规划Agent解决“问什么、怎么算、如何分析”，SQLBot解决“怎么查数据”。这两个组合起来，反而更接近现在企业级 BI Agent 的发展方向。

# 追问：我准备对sqlbot进行企业级问数系统改造，请你给出最终改造建议方案。

结合我们前面关于**企业级智能问数架构**的讨论，以及你对 SQLBot 当前实现的分析，我认为对 SQLBot 的改造目标不应该是“把 SQLBot 做得更像一个大模型聊天工具”，而应该是：

> **将 SQLBot 从一个 RAG 增强型 Text2SQL 工具，升级为企业级可信智能问数 Agent 的数据查询执行底座。**

也就是说：

* 保留 SQLBot 已经验证有效的能力：

  * 术语检索
  * SQL 示例检索
  * Prompt 增强
  * SQL 生成
  * SQL 执行
  * 图表生成

* 增强企业级能力：

  * 指标治理
  * 语义解析
  * 查询规划
  * SQL生成约束
  * 计算分析
  * 可信验证
  * Agent化编排

下面给出一个完整改造方案。

---

# 一、最终目标架构

改造后的系统建议演进为：

```text
                         用户问题
                            |
                            ↓
                  ┌─────────────────┐
                  │ 对话交互层       │
                  │ Chat/Web/API    │
                  └────────┬────────┘
                           |
                           ↓
                  ┌─────────────────┐
                  │ Query Planner   │
                  │ 问题理解规划Agent │
                  └────────┬────────┘
                           |
             输出结构化分析计划
                           |
                           ↓
        ┌────────────────────────────────┐
        │        Semantic Layer          │
        │          业务语义层             │
        ├────────────────────────────────┤
        │ 指标中心 Metric                │
        │ 维度中心 Dimension             │
        │ 术语库 Term                    │
        │ 业务规则 Rule                  │
        └──────────────┬─────────────────┘
                       |
                       ↓
             ┌─────────────────┐
             │ Query Builder   │
             │ 查询构造Agent    │
             └────────┬────────┘
                      |
              DSL / Query Plan
                      |
                      ↓
             ┌─────────────────┐
             │ SQL Generator   │
             │ SQLBot核心能力   │
             └────────┬────────┘
                      |
                      ↓
             ┌─────────────────┐
             │ SQL Validator   │
             │ SQL审核校验      │
             └────────┬────────┘
                      |
                      ↓
             ┌─────────────────┐
             │ Query Executor  │
             │ 数据执行层       │
             └────────┬────────┘
                      |
                      ↓
             ┌─────────────────┐
             │ Compute Engine  │
             │ 计算分析引擎      │
             └────────┬────────┘
                      |
                      ↓
             ┌─────────────────┐
             │ Insight Agent   │
             │ 分析洞察Agent    │
             └────────┬────────┘
                      |
                      ↓
             ┌─────────────────┐
             │ Answer Generator│
             │ LLM总结表达      │
             └─────────────────┘
```

---

# 二、改造原则

## 原则1：不要推翻 SQLBot

SQLBot已经解决：

* SQL生成
* Prompt组装
* 示例增强
* 执行流程

这些不要重写。

应该：

> 外挂能力增强。

类似：

```
SQLBot = Query Worker
```

上层增加：

```
Agent Orchestrator
```

---

## 原则2：LLM从“SQL生成者”变成“规划者”

原始：

```
用户
 ↓
LLM
 ↓
SQL
```

改为：

```
用户
 ↓
LLM
 ↓
查询计划
 ↓
SQL生成
```

---

# 三、核心改造模块设计

---

# 模块1：增加 Query Planner（问题分析规划Agent）

## 当前SQLBot缺陷

直接：

用户问题

↓

SQL生成

问题：

LLM需要同时完成：

* 理解问题
* 找指标
* 找表
* 写SQL
* 判断计算

任务太重。

---

## 增加：

Query Planner

输入：

```
上海五一游客量同比增长多少？
```

输出：

```json
{
 "intent":"COMPARE",
 "metric":"游客量",
 "dimension":"区域",
 "time":{
    "current":"2026劳动节",
    "previous":"2025劳动节"
 },
 "calculation":"同比增长率"
}
```

后续所有模块基于这个执行。

---

## 实现

可以使用：

* LangGraph
* AgentScope
* 自研Workflow

---

# 模块2：建设指标中心（最高优先级）

这是最大改造点。

---

## 当前SQLBot：

术语：

```
游客量
→ visitor_count
```

升级：

指标：

```
游客量

定义:
统计周期内接待游客人数

来源:
tourism_flow

字段:
visitor_count

计算:
sum(visitor_count)

时间字段:
visit_date

允许维度:
区域/日期/来源地

默认过滤:
status=1
```

---

## 数据模型建议

### metric表

```sql
metric_id
metric_name
description
formula
table_name
field_name
aggregation
owner
version
```

---

### metric_alias

```sql
metric_id
alias
```

例如：

```
游客量
客流
游客人数
旅游人数
```

---

### metric_rule

```sql
metric_id
rule_type
rule_content
```

例如：

```
收入必须过滤退款订单
```

---

# 模块3：增强语义检索

保留SQLBot：

* 术语向量检索

增加：

## 指标检索

优先级：

```
指标
 ↓
术语
 ↓
SQL案例
 ↓
Schema
```

因为：

业务正确性：

指标 > 字段

---

# 模块4：增加 Schema 检索（中大型企业必须）

你之前指出 SQLBot没有这个。

小规模可以。

企业必须增加。

---

## 建议建立 Metadata Store

维护：

```
数据库
 |
 表
 |
 字段
 |
 注释
 |
 业务描述
 |
 血缘
```

例如：

```json
{
"table":"tourism_flow",
"description":"景区游客流量统计",
"columns":[
 {
  "name":"visitor_count",
  "desc":"游客数量"
 }
]
}
```

建立Embedding。

用户问题：

```
游客来源分析
```

召回：

```
tourist_source
visitor_region
```

---

# 模块5：SQL生成改造

## 当前：

```
Prompt
+
Schema
+
Example

↓

SQL
```

保留。

但是增加：

## Query DSL

中间层：

```json
{
"type":"ranking",
"metric":"游客量",
"group":"省份",
"limit":10
}
```

然后：

DSL → SQL

---

优势：

避免：

LLM直接控制SQL。

---

# 模块6：SQL Validator（必须增加）

SQL生成后：

不要直接执行。

增加审核。

---

## 检查：

### 1. 安全

禁止：

```sql
delete
update
drop
```

---

### 2. 性能

检查：

* 全表扫描
* 大范围查询
* 缺where

---

### 3. 业务规则

例如：

指标：

游客量

必须：

```
where status=1
```

否则拒绝。

---

# 模块7：计算引擎（强烈建议）

这是你之前观点：

> 计算交给代码

完全正确。

---

不要：

LLM：

```
今年100
去年80

增长25%
```

应该：

SQL:

返回：

```
current=100
previous=80
```

Compute Engine:

```python
growth=(100-80)/80
```

输出：

```json
{
"growth":0.25
}
```

---

# 模块8：分析Agent

SQLBot目前偏：

查询。

增加：

分析。

---

## 输入：

查询结果：

```json
{
"2025":100,
"2026":70
}
```

分析Agent：

任务：

* 判断是否异常
* 找原因
* 推荐下一步分析

---

例如：

输出：

```json
{
"abnormal":true,
"possible_reason":[
 "天气因素",
 "客源下降"
],
"next_analysis":[
 "查询天气",
 "分析来源地区"
]
}
```

---

# 模块9：回答生成Agent

最后：

LLM只做：

表达。

输入：

```
事实：

游客量：
2026=70万

同比：
-30%

原因：
暴雨增加5天
```

输出：

自然语言。

---

# 四、SQLBot改造后的Agent划分

推荐：

```text
Supervisor Agent

        |
--------------------------------
|        |          |           |
Planner Metric   Query      Analyst
Agent    Agent    Agent     Agent

                      |
                  SQLBot
                  Worker
```

---

# 五、改造优先级路线

不要一次全部做。

建议：

---

# Phase 1：可信查询（1~2个月）

目标：

查对。

开发：

✅ Query Planner

✅ 指标中心

✅ 增强术语库

✅ SQL Validator

---

# Phase 2：企业可用（2~4个月）

目标：

稳定上线。

增加：

✅ Schema检索

✅ DSL

✅ 权限控制

✅ 计算引擎

---

# Phase 3：智能分析（4~6个月）

目标：

从问数到分析。

增加：

✅ 异常检测

✅ 归因分析

✅ 分析Agent

✅ 自动报告

---

# 六、结合你的文旅问数场景，我建议最终形态

你的场景：

* 景区客流
* 游客来源
* 咨询中心
* 节假日分析
* 文旅规划

非常适合：

```text
文旅分析规划Agent
        |
        ↓
生成分析DAG
        |
        ↓
SQLBot Query Agent
        |
        ↓
数据库查询
        |
        ↓
计算Agent
        |
        ↓
分析Agent
        |
        ↓
报告Agent
```

例如：

用户：

> “分析2026五一上海旅游市场变化情况”

不是直接SQL。

而是：

Planner生成：

```json
[
{
"type":"TREND",
"metric":"游客量"
},
{
"type":"COMPARE",
"metric":"游客来源"
},
{
"type":"RANK",
"metric":"热门景区"
}
]
```

然后执行多个查询。

这才是真正的：

**文旅智能分析Agent。**

---

# 七、最终改造建议总结

如果让我给 SQLBot 定位：

不要把它改造成：

> “更强的Text2SQL工具”

而应该改造成：

> **企业智能问数系统中的 Query Worker**

重点增强：

| 优先级   | 模块            |
| ----- | ------------- |
| ★★★★★ | 指标中心          |
| ★★★★★ | Query Planner |
| ★★★★★ | 计算引擎          |
| ★★★★  | Schema检索      |
| ★★★★  | SQL Validator |
| ★★★★  | 权限体系          |
| ★★★   | 分析Agent       |
| ★★★   | 自动洞察          |

其中最重要的三个：

1. **指标中心**
2. **查询规划Agent**
3. **程序化计算分析**

这三个决定了系统是否从“能生成SQL”升级到“可信业务分析系统”。

结合你之前的文旅问数规划Agent设计，我认为最合理路线不是替换 SQLBot，而是把 SQLBot 纳入你的 Agent 架构中，让它成为可靠的数据查询执行层。你之前提出的“规划-执行-验证-总结”模式，与这个改造方向高度一致。


# 追问：对于单纯的问数场景【数据分析及预测场景，sqlbot中已经存在相关功能，再说这部分改造优先级可以放后面进行】，也就是说要在sqlbot中增加指标管理模块、schema检索、dsl->sql、计算引擎

你的理解基本正确，而且你进一步限定了范围后，改造重点会更加清晰。

如果目标是：

> **单纯企业级智能问数（用户提问 → 查询数据 → 返回可信结果）**

而暂时不考虑：

* 自动分析洞察
* 原因归因
* 趋势预测
* 数据分析Agent

那么 SQLBot 的改造重点确实应该集中在：

1. **指标管理模块（Metric Layer）**
2. **Schema检索模块（Metadata Retrieval）**
3. **DSL → SQL 查询生成链路**
4. **计算引擎（Calculation Engine）**

其中优先级我建议调整为：

```
指标管理模块
        ↓
DSL查询规划
        ↓
DSL→SQL
        ↓
计算引擎
        ↓
Schema检索增强
```

为什么我把 Schema 检索放在指标之后，下面详细解释。

---

# 一、改造后的企业级问数架构

针对纯问数场景，推荐架构：

```
用户问题
    |
    ↓
问题解析 Agent
    |
    ↓
Query DSL
    |
    ↓
语义增强层
    |
    ├── 指标管理
    ├── 维度管理
    ├── 术语管理
    ├── Schema检索
    |
    ↓
SQL生成器
    |
    ↓
SQL Validator
    |
    ↓
SQL执行
    |
    ↓
计算引擎
    |
    ↓
结果格式化
    |
    ↓
图表生成
    |
    ↓
前端展示
```

其中：

SQLBot当前能力：

```
术语
+
SQL示例
+
Prompt
+
Schema
+
LLM
↓
SQL
```

升级为：

```
用户问题
↓
DSL
↓
指标/维度/schema约束
↓
SQL
```

核心变化：

> 从“让LLM猜SQL”变成“让系统生成SQL”。

---

# 二、第一优先级：指标管理模块（Metric Layer）

这是企业问数最应该补充的能力。

## 为什么优先级最高？

因为：

Schema只能告诉模型：

> 数据库有什么。

但是用户问的是：

> 业务指标是什么。

例如：

数据库：

```
tourism_statistics

字段：

visitor_num
visitor_count
person_num
order_count
```

用户：

> 五一游客量是多少？

Schema无法回答：

应该使用哪个字段。

指标管理可以。

---

# 三、指标管理模块设计

建议独立成一个服务。

类似：

```
Metric Service
```

---

## 1. 指标定义

核心表：

### metric_definition

| 字段            | 说明   |
| ------------- | ---- |
| metric_id     | 指标ID |
| metric_name   | 指标名称 |
| description   | 指标说明 |
| business_type | 业务分类 |
| table_name    | 来源表  |
| field_name    | 字段   |
| aggregation   | 聚合方式 |
| filter_rule   | 过滤条件 |
| time_field    | 时间字段 |

例如：

```json
{
 "metric_name":"游客量",
 "description":"统计周期内游客接待人数",
 "table":"tourism_flow",
 "field":"visitor_count",
 "aggregation":"sum",
 "filter":"status=1",
 "time_field":"visit_date"
}
```

---

## 2. 指标别名

解决用户表达。

例如：

```
游客量

别名：

客流
游客人数
旅游人数
接待人数
```

表：

```
metric_alias
```

---

## 3. 指标关联维度

例如：

游客量支持：

```
时间
城市
景区
来源地
```

不支持：

```
支付方式
订单状态
```

表：

```
metric_dimension_relation
```

---

## 4. 指标查询示例

维护：

```
指标：
游客量

典型查询：

按区域统计
按月份趋势
同比
排名
```

这个可以替代部分SQL Example。

---

# 四、第二优先级：DSL查询层

这是整个改造的关键。

## 为什么需要DSL？

因为：

现在：

```
用户问题
↓
LLM
↓
SQL
```

中间缺少控制。

改成：

```
用户问题
↓
LLM
↓
Query DSL
↓
SQL
```

---

# DSL是什么？

本质：

数据库无关的查询描述语言。

例如：

用户：

> 查询2026年五一上海游客量同比

LLM输出：

```json
{
 "query_type":"comparison",

 "metric":{
    "name":"游客量"
 },

 "filters":[
   {
    "dimension":"地区",
    "value":"上海"
   }
 ],

 "time":{
    "current":"2026-05-01~2026-05-05",
    "compare":"2025-05-01~2025-05-05"
 },

 "aggregation":"sum"
}
```

---

然后：

DSL解析器：

生成：

```sql
select
sum(visitor_count)
from tourism_flow
where
city='上海'
and date between ...
```

---

# DSL带来的价值

## 1. 控制SQL生成

LLM只负责理解。

## 2. 可测试

可以测试：

```
问题
↓
DSL
```

是否正确。

## 3. 可扩展

未来支持：

* Elasticsearch
* ClickHouse
* OLAP
* API

---

# 五、第三优先级：Schema检索

这里需要重新定位。

Schema检索不是不要，而是：

> 它解决的是“找数据在哪里”，指标解决的是“应该查什么”。

---

# Schema检索流程

建立Metadata库：

```
database

table

column

comment

business_description

embedding
```

例如：

```
table:
tourism_source_statistics

description:
游客来源统计

columns:

province
visitor_count
date
```

---

用户：

> 江苏游客数量

检索：

召回：

```
tourism_source_statistics
```

---

# 什么时候必须做？

## 小规模：

几十张表：

可以直接注入。

## 中大型：

几百～几千张表：

必须检索。

---

# 六、第四优先级：DSL→SQL

这里建议不要让LLM生成SQL。

设计：

```
DSL Parser

↓

SQL AST

↓

SQL Builder
```

例如：

DSL：

```json
{
metric:"游客量",
group:"省份"
}
```

解析：

找到：

```
metric:
 visitor_count

table:
 tourism_source
```

生成：

```sql
select
province,
sum(visitor_count)
from tourism_source
group by province
```

---

# 七、第五优先级：计算引擎

这里与你之前观点完全一致。

SQL负责：

```
数据获取
```

计算引擎负责：

```
业务计算
```

---

例如：

用户：

> 同比增长率

SQL：

查询：

```
2026:
100

2025:
80
```

计算：

```python
growth=(100-80)/80
```

结果：

```
25%
```

---

计算引擎管理：

## 基础计算

* sum
* avg
* count

## 分析计算

* 同比
* 环比
* 占比
* 增长率
* 排名

## 统计计算

* 最大值
* 最小值
* 方差
* 波动率

---

# 八、SQLBot现有模块如何调整？

我建议：

## 保留

### 术语库

升级为：

```
业务语义层
```

### SQL Example

升级为：

```
DSL Example
```

不要维护大量SQL。

维护：

```
问题模式
↓
DSL模板
```

### Prompt

降低作用。

以前：

Prompt承担业务规则。

以后：

规则进入：

* 指标中心
* DSL校验
* SQL Validator

---

# 九、最终改造优先级排序

如果投入有限，我建议：

## Phase 1（最重要）

### ① 指标管理

★★★★★

### ② DSL查询层

★★★★★

目标：

解决：

“查什么”

---

## Phase 2

### ③ DSL→SQL

★★★★★

### ④ SQL Validator

★★★★

目标：

解决：

“怎么查”

---

## Phase 3

### ⑤ Schema检索

★★★★

目标：

解决：

“去哪查”

---

## Phase 4

### ⑥ 计算引擎

★★★★

目标：

解决：

“怎么算”

---

# 十、结合你的文旅问数项目，我认为最佳落地路径

你当前已有：

> 文旅数据分析规划Agent输出DAG

那么 SQLBot 改造后应该作为：

```
文旅分析规划Agent

输出:

{
 metric:
 游客量,

 dimension:
 来源省份,

 time:
 五一,

 calculation:
 同比
}


        ↓


SQLBot Query Engine


        ↓


DSL


        ↓


SQL


        ↓


数据


        ↓


计算引擎


        ↓


结果
```

这个架构非常合理。

---

## 最终结论

对于“纯问数”场景，SQLBot改造重点确实就是：

| 模块        | 必要性      | 优先级   |
| --------- | -------- | ----- |
| 指标管理      | 解决业务口径   | ★★★★★ |
| DSL查询层    | 控制LLM输出  | ★★★★★ |
| DSL→SQL   | 保证SQL稳定  | ★★★★★ |
| 计算引擎      | 保证计算准确   | ★★★★  |
| Schema检索  | 解决大规模元数据 | ★★★★  |
| 分析预测Agent | 非当前重点    | ★★    |

其中最关键的架构变化：

> **从 RAG增强Text2SQL，升级为 Metric + DSL 驱动的企业查询系统。**

这也是目前企业级 Text2SQL / AI BI 系统比较主流的演进方向。你之前提出的“规划→执行→计算→总结”的思路，与这个方向是一致的。


# 追问：澄清改造细节

```text
澄清几点：
1、指标中心的指标数据检索，是对指标描述信息，延用sqlbot的基于rag【关键词检索、向量检索、可酌情增加llm过滤步骤】的数据检索吗？
2、schema检索的实现：是将数据表结构信息json化处理，视为文本，然后沿用sqlbot的基于rag的数据检索吗？如果是json，是否会引入json格式相关的额外语义干扰信息呢？
3、dsl如何转化成sql，是基于代码规则化的SQL生成吗？其实就是sql组装：查哪张表的哪些字段、查询条件是什么、组合条件什么。
4、整条链路看起来缺点东西：用户问题--相关指标、相关schema--dsl--sql，然是计算引擎是基于用户问题的计算意图来定的，所以这个计算意图放在哪里呢？是单独存在，还是放在哪个环节中？
```

你的这几个澄清问题非常关键，实际上已经触及企业级问数系统设计中最核心的几个边界：

* **语义理解层**
* **知识检索层**
* **查询规划层**
* **SQL生成层**
* **计算分析层**

我逐个回答，并顺便修正前面方案中一些容易模糊的地方。

---

# 1. 指标中心的指标数据检索，是不是延用 SQLBot 的 RAG？

你的理解基本正确，但需要区分：

> 检索的是“指标定义知识”，不是直接检索指标数据。

也就是说：

指标中心本质是一个**业务语义知识库**。

---

## 1.1 指标中心存储什么？

例如：

指标：

```
游客量
```

不是简单：

```
游客量 -> visitor_count
```

而应该是：

```json
{
  "metric_name": "游客量",

  "description": 
  "统计周期内进入景区或区域的游客人数",

  "aliases": [
    "客流",
    "游客人数",
    "旅游人数",
    "接待人数"
  ],

  "source_table": "tourism_flow",

  "source_field": "visitor_count",

  "aggregation": "sum",

  "time_field": "visit_date",

  "dimensions": [
    "区域",
    "日期",
    "来源地"
  ],

  "calculation_rules": [
    "同比增长率=(本期-同期)/同期"
  ]
}
```

---

## 1.2 检索过程

用户：

> 五一期间江苏游客数量

进入：

### Step 1：关键词检索

匹配：

```
游客数量
游客
数量
```

---

### Step 2：向量检索

理解：

```
游客数量
≈
游客量
≈
客流
≈
接待人数
```

召回：

```
游客量指标
游客接待量指标
景区客流指标
```

---

### Step 3：LLM rerank（可选）

为什么需要？

因为可能召回：

```
游客量
游客满意度
游客投诉量
```

向量相似，但是业务不同。

LLM判断：

哪个最符合问题。

---

所以：

你的理解：

> 指标检索 = SQLBot原有RAG能力复用

✅ 正确。

只是检索对象从：

```
术语
SQL案例
```

扩展为：

```
指标知识
```

---

# 2. Schema检索是不是JSON文本RAG？

你的理解方向正确。

但是这里有一个工程细节：

> 不建议直接把数据库DDL JSON化后原样Embedding。

原因：

你提到的：

> JSON格式是否会引入语义干扰？

答案：

**会。**

---

## 2.1 不推荐方式

例如：

直接：

```json
{
"table":"tourism_flow",
"columns":[
 {
"name":"visitor_count",
"type":"bigint"
 }
]
}
```

直接embedding。

问题：

Embedding模型看到大量：

```
table
column
type
varchar
bigint
id
```

这些技术噪声。

---

# 2.2 推荐方式

构造“面向语义检索的文本”。

例如：

原始数据库：

```sql
CREATE TABLE tourism_flow(
 visitor_count bigint,
 visit_date datetime,
 province varchar
)
```

转换：

```text
表名称：
旅游客流统计表

业务描述：
用于统计各地区游客接待数量。

主要字段：

游客数量：
字段 visitor_count
含义：
统计游客人数。

日期：
字段 visit_date
含义：
统计日期。

来源地区：
字段 province
含义：
游客来源省份。


支持分析：
- 游客趋势
- 来源分析
- 区域排名
```

然后embedding。

---

## 2.3 为什么？

因为用户问题：

> 江苏游客数量

不是：

```
visitor_count
province
```

而是：

```
来源地区游客统计
```

需要语义匹配。

---

## 2.4 所以Schema检索流程应该是：

数据库：

```
表结构
字段注释
业务描述
血缘
```

↓

Metadata加工

↓

生成：

```
Schema Document
```

↓

Embedding

↓

RAG

---

# 3. DSL如何转SQL？

你的理解：

> 是不是代码规则化SQL生成，本质就是SQL组装？

基本正确。

这里需要强调：

## DSL不是SQL中间字符串

而应该是：

> 业务查询计划。

---

例如用户：

> 查询2026年五一江苏游客量

LLM不要输出：

```sql
select ...
```

而输出：

DSL：

```json
{
 "metric":"游客量",

 "dimensions":[
    "省份"
 ],

 "filters":[
   {
    "province":"江苏"
   }
 ],

 "time_range":{
   "start":"2026-05-01",
   "end":"2026-05-05"
 }
}
```

---

然后代码执行：

```
metric解析
      |
      ↓
找到：
tourism_flow.visitor_count


dimension解析
      |
      ↓
province字段


filter解析
      |
      ↓
where province='江苏'


SQL Builder
      |
      ↓
SQL
```

最终：

```sql
SELECT
sum(visitor_count)
FROM tourism_flow
WHERE
province='江苏'
AND visit_date between ...
```

---

所以：

你的理解：

> DSL→SQL就是查哪些表、字段、条件组合

✅ 对。

但更准确：

> DSL是业务查询意图，SQL Builder是确定性代码生成。

---

# 4. 你发现的最大问题：计算意图在哪里？

这个问题非常重要。

实际上你指出了目前链路缺失的一层：

```text
用户问题
 ↓
指标
 ↓
Schema
 ↓
DSL
 ↓
SQL
```

确实少了：

> 查询目的 / 计算意图 / 分析类型

---

# 正确架构应该是：

```text
用户问题

↓

语义解析层

↓

Query Intent

↓

指标检索

↓

Schema检索

↓

DSL

↓

SQL

↓

计算引擎
```

---

# 4.1 Query Intent是什么？

它不是指标。

例如：

用户：

> 2026年五一游客量同比增长多少？

指标：

```
游客量
```

维度：

```
时间
```

但是还有：

计算意图：

```
同比比较
```

---

结构：

```json
{
 "metric":"游客量",

 "query_type":"comparison",

 "calculation":{
    "type":"year_on_year"
 },

 "time":{
    "current":"2026五一",
    "previous":"2025五一"
 }
}
```

---

# 4.2 计算意图应该放哪里？

我的建议：

单独作为 Query Plan 的一部分。

不要：

放指标中心。

原因：

同一个指标：

游客量

可以：

查询：

```
当前值
```

计算：

```
同比
```

分析：

```
趋势
```

预测：

```
未来走势
```

指标不应该绑定所有计算方式。

---

应该：

```
Metric
+
Dimension
+
Filter
+
Time
+
Calculation Intent

=
Query Plan
```

---

# 5. 最终完整链路应该调整为

你指出的问题之后，我认为更准确的是：

```text
                 用户问题
                     |
                     ↓
          Query Understanding
              （语义解析）
                     |
          ---------------------
          |                   |
       查询意图             业务实体
          |                   |
          |              指标/维度
          |
          ↓
       Query Plan
          |
          |
 ----------------------------
 |            |             |
指标RAG     Schema RAG   规则库
 |            |             |
 ----------------------------
          |
          ↓
          DSL
          |
          ↓
       SQL Builder
          |
          ↓
          SQL
          |
          ↓
        数据库
          |
          ↓
      Calculation Engine
          |
          ↓
        Answer
```

---

# 6. 结合你的四个问题，最终修正版设计原则

## ① 指标中心

定位：

> 业务语义层

实现：

RAG检索。

输入：

用户问题。

输出：

指标定义。

---

## ② Schema检索

定位：

> 数据语义层

实现：

Metadata加工后的RAG。

不是直接DDL JSON embedding。

---

## ③ DSL→SQL

定位：

> 确定性生成

实现：

代码规则生成。

不是LLM生成SQL。

---

## ④ 计算意图

定位：

> Query Plan核心字段

不是指标属性。

应该由：

Query Understanding阶段识别。

---

# 7. 对 SQLBot 改造的最终模块划分

如果按照这个思路改造 SQLBot，我建议增加：

```
1. Query Understanding模块
   - 意图识别
   - 实体抽取
   - 计算意图识别


2. Metric Center
   - 指标RAG


3. Metadata Center
   - Schema RAG


4. Query DSL
   - 查询计划模型


5. SQL Generator
   - DSL→SQL


6. Calculation Engine
   - 同比
   - 环比
   - 占比
   - 排名
```

---

你提出的第4个问题其实是整个架构设计的关键点：**不要把“计算”理解成SQL之后的附加步骤，而应该在最开始的问题理解阶段就识别出来。**

这也和你之前设计的“文旅数据分析规划Agent输出DAG”的思路一致：
**先理解用户想做什么，再决定查什么数据、如何计算，而不是先生成SQL再补救。**


# 追问：也就是说：对于指标数据，至少要创建两张表，一张表存储指标数据，另一张表存储指标document和embedding及关键词分词列表。schema也类似。

你的理解方向是正确的，而且这实际上已经接近企业级语义层（Semantic Layer）的典型实现方式。

不过我建议稍微调整一下表述：

> **不是简单地“一张业务表 + 一张向量表”，而是将“业务元数据存储”和“检索索引存储”分离。**

也就是说：

* **结构化元数据（Source of Truth）**
* **面向检索的语义文档（Search Index）**

分离。

指标和 Schema 都采用类似模式。

---

# 一、指标中心推荐设计

## 1. 指标元数据表（Metric Metadata）

这是权威数据源。

例如：

### metric_definition

```sql
CREATE TABLE metric_definition
(
    id              bigint,

    metric_name     varchar(128),

    description     text,

    business_domain varchar(64),

    source_table    varchar(128),

    source_column   varchar(128),

    aggregation     varchar(32),

    filter_rule     text,

    time_field      varchar(128),

    status          int
);
```

存：

> 指标是什么。

例如：

| 字段            | 值             |
| ------------- | ------------- |
| metric_name   | 游客量           |
| source_table  | tourism_flow  |
| source_column | visitor_count |
| aggregation   | sum           |
| time_field    | visit_date    |

---

## 2. 指标别名表

通常独立。

### metric_alias

```sql
metric_id

alias
```

数据：

| metric_id | alias |
| --------- | ----- |
| 1001      | 游客人数  |
| 1001      | 客流    |
| 1001      | 接待人数  |

作用：

关键词检索。

---

## 3. 指标检索文档表

这个就是你说的 document 表。

例如：

### metric_document

```sql
CREATE TABLE metric_document
(
    id bigint,

    metric_id bigint,

    document_text text,

    keyword_list json,

    embedding vector
);
```

内容：

```text
指标名称：
游客量

业务含义：
用于统计旅游接待规模。

用户常见表达：
游客人数、客流、接待人数。

支持分析：
趋势、排名、同比。
```

embedding：

来自：

```text
document_text
```

---

# 二、为什么不直接用 metric_definition 做向量？

例如：

直接：

```text
游客量 tourism_flow visitor_count sum
```

embedding。

问题：

大量技术字段污染语义。

用户问：

> 五一客流

模型应该匹配：

```text
游客量
旅游接待规模
```

而不是：

```text
visitor_count
tourism_flow
```

所以需要：

**语义文档加工层。**

---

# 三、Schema也是同样设计

你的理解：

> schema也类似

完全正确。

但是 Schema 会更复杂。

---

# 四、Schema元数据设计

## 1. 表元数据

### table_metadata

```sql
table_id

database_name

table_name

table_comment

business_domain
```

例如：

```text
table_name:
tourism_flow

comment:
景区游客流量统计表
```

---

## 2. 字段元数据

### column_metadata

```sql
column_id

table_id

column_name

column_comment

data_type
```

例如：

| 字段            | 说明   |
| ------------- | ---- |
| visitor_count | 游客数量 |
| province      | 来源省份 |

---

## 3. Schema检索文档

### schema_document

```sql
id

object_type

object_id

document_text

keyword_list

embedding
```

---

例如：

document：

```text
数据表：
景区游客流量统计表

用途：
统计各景区每日游客接待情况。

主要字段：

游客数量：
visitor_count

日期：
visit_date

来源省份：
province

支持：
游客趋势分析
来源地分析
```

embedding。

---

# 五、关键词列表是否需要保存？

你的设计里面提到了：

> embedding及关键词分词列表

这个非常好。

实际上企业系统通常是：

## 两路检索

---

## 1. 关键词检索

例如：

Elasticsearch。

字段：

```json
{
"text":"游客量 客流 接待人数",
"keywords":[
 "游客",
 "客流",
 "人数"
]
}
```

优势：

精确。

---

## 2. 向量检索

例如：

Milvus / pgvector。

优势：

语义。

---

最终：

Hybrid Search：

```text
用户问题

    |
    |
 ----------------
 |              |
关键词召回     向量召回
 |              |
 ----------------
        |
      Rerank
        |
      TopK
```

这和 SQLBot 当前方案是一致的。

---

# 六、但是这里有一个重要优化

不要设计成：

```
metric_definition

metric_document

schema_definition

schema_document
```

然后完全独立。

因为：

指标和Schema存在天然关系。

推荐：

形成：

```text
Metric

  |
  | depends_on

  ↓

Table

  |
  |
 Column
```

---

例如：

指标：

```text
游客量
```

绑定：

```text
tourism_flow.visitor_count
```

Schema检索时：

可以先限定：

```text
tourism_flow
```

范围。

---

# 七、最终推荐整体模型

```text
                 用户问题

                     |
                     ↓

          Semantic Retrieval Layer

                     |
        -----------------------------
        |                           |
   Metric Search              Schema Search
        |                           |
        ↓                           ↓

 Metric Metadata             Metadata Store

        |
        |
        ↓

     Query DSL

        |
        ↓

     SQL Builder
```

---

# 八、对应你的 SQLBot 改造

实际上你已经把 SQLBot 原来的：

```
术语库
SQL示例库
Prompt库
```

演进成：

```
指标中心
Schema中心
规则中心
```

其中：

| SQLBot原组件   | 企业版         |
| ----------- | ----------- |
| 术语库         | 指标语义层       |
| SQL Example | DSL Example |
| Prompt规则    | 业务规则库       |
| Schema注入    | Schema检索    |
| LLM SQL生成   | DSL→SQL     |

---

# 九、补充一个容易忽略的问题：embedding不是一次生成永久不变

企业系统需要考虑：

## 指标变更

例如：

游客量计算规则变化：

以前：

```
sum(visitor_count)
```

后来：

```
count(distinct visitor_id)
```

需要：

重新生成：

metric_document。

---

## 表结构变更

字段新增：

需要：

重新生成：

schema_document。

所以还需要：

Metadata同步任务：

```text
数据库
 ↓
元数据采集
 ↓
文档生成
 ↓
关键词抽取
 ↓
Embedding生成
 ↓
索引更新
```

---

# 十、总结你的理解

你的总结：

> 指标至少两张表，一张存指标数据，一张存指标document和embedding及关键词；schema类似。

评价：

✅ 架构方向正确。

更准确地说：

企业级实现通常是：

```
结构化元数据层
        +
语义检索索引层
```

二者分离。

指标：

```
metric_definition
metric_alias
metric_document/vector
```

Schema：

```
table_metadata
column_metadata
schema_document/vector
```

然后通过：

```
Metric → Schema → DSL → SQL
```

形成完整链路。

你现在讨论的问题已经从“如何调用大模型生成SQL”进入了**企业级Text2SQL最核心的语义建模阶段**，这也是 SQLBot 从开源工具走向企业系统时最需要补齐的部分。
