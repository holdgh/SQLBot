# 整体调用链 + yield 嵌套流式逻辑
> 这是**三层生成器嵌套**，本质是**惰性迭代、逐级透传 chunk**，不是一次性把结果全部加载到内存，典型 LLM SSE 流式输出模式。
调用顺序（调用栈）：
```
外层函数（chat 接口）
    ↳ self.generate_sql(_session) 【生成器A】
        ↳ process_stream(...) 【生成器B】
            ↳ self.llm.stream(...) 【底层大模型SDK原生生成器C】
```
`yield` 是**暂停函数、返回一个值，下次迭代从暂停位置继续执行**；生成器是**单向拉取**：外层 `for ... in X` 会驱动 X 内部执行直到遇到下一个 yield。

---

## 逐层拆解
### 1. 最底层：`self.llm.stream(self.sql_message)`（生成器C）
大模型 SDK 原生流式接口，每次迭代返回模型原始 chunk（一段增量文本），**模型吐一点，就产出一块**。
它是整个数据流的源头。

### 2. `process_stream(...)`（生成器B，中间解析层）
```python
for chunk in self.llm.stream(...):
    # 做标签解析：区分思考标签（）和普通内容
    if not in_thinking_block and current_thinking.strip() != '':
        output_content = content
        yield {
            'content': output_content,
            'reasoning_content': reasoning_content_chunk
        }
        get_token_usage(chunk, token_usage)
        continue
    # ...其余标签解析逻辑，满足条件也会 yield 字典
```
- `for chunk in self.llm.stream(...)`：**拉取模型原生chunk**
- 对原始流做解析：把模型输出拆成两块：
  - `content`：最终SQL文本
  - `reasoning_content`：思考过程（``里面的内容）
- **每次解析完成一块，就 yield 一个字典 `{content, reasoning_content}`**
> ⚠️关键点：
> `process_stream` 不会一次性读完所有模型流，**外层每拉一次，它才往下读一块模型数据、解析、yield 一个结构化chunk**，惰性执行。

### 3. `generate_sql()`（生成器A，SQL业务层）
```python
res = process_stream(self.llm.stream(self.sql_message), token_usage)
for chunk in res:      # for 驱动 process_stream 这个生成器B
    if chunk.get('content'):
        full_sql_text += chunk.get('content')
    if chunk.get('reasoning_content'):
        full_thinking_text += chunk.get('reasoning_content')
    yield chunk        # 【透传这个结构化字典给上层】
# ！！只有当 process_stream 迭代完全结束（所有chunk全部yield完）
# 下面这行才执行
self.sql_message.append(AIMessage(full_sql_text))
```
这里就是**嵌套yield最容易踩坑的地方**：
1. `for chunk in res`：开始迭代 `process_stream`，每一次循环：
   - 驱动底层 llm.stream → process_stream 产出一块结构化字典
   - 累加 `full_sql_text` / `full_thinking_text`（内存中拼接完整文本）
   - `yield chunk`：把这个字典**直接抛给外层调用方**，`generate_sql` 函数在这里**暂停**
2. **`self.sql_message.append(...)` 不会提前执行！**
   只有当外层把 `sql_res`（generate_sql生成器）全部遍历完、所有chunk全部取完，`for chunk in res` 循环退出，才会执行追加 AIMessage 到消息列表。
   > 流式过程中，消息列表不会实时追加，是**流结束之后一次性追加完整回答**，这是非常典型的写法。

### 4. 最外层：chat 接口层（SSE输出）
```python
sql_res = self.generate_sql(_session)
full_sql_text = ''
for chunk in sql_res:      # for 驱动 generate_sql 生成器A
    full_sql_text += chunk.get('content')
    if in_chat:
        yield 'data:' + orjson.dumps(...).decode() + '\n\n'
```
- `for chunk in sql_res` → 触发 `generate_sql` 运行，直到它 `yield chunk`
- 拿到结构化chunk，再包装成 SSE `data: {...}\n\n` 格式字符串，**再次 yield 给 web 框架**（FastAPI StreamingResponse）返回给前端浏览器
- 这里的 `full_sql_text` 是外层又一份拼接缓存，和 generate_sql 内部的 `full_sql_text` 是**两份独立变量**，互不干扰

---

# 完整时序演示（事件顺序）
1. 外层执行 `sql_res = self.generate_sql(_session)`
   ⚠️ **注意：仅仅创建生成器对象！generate_sql 函数内部代码此时完全没跑！** 生成器只有被迭代（for / next()）才会执行。
2. 外层进入 `for chunk in sql_res:` → 调用 next(sql_res)
   - 进入 `generate_sql`，执行 `res = process_stream(...)`，同样只是创建 process_stream 生成器，不执行里面代码
   - 进入 `for chunk in res:` → next(res)，进入 process_stream
   - process_stream 内部 `for chunk in llm.stream()` → next(底层模型生成器)，拿到模型原始token
   - 解析标签，组装 `{'content':..., 'reasoning_content':...}`，yield 字典 → process_stream暂停
   - 回到 generate_sql 的循环，累加字符串，`yield chunk` → generate_sql暂停
   - 回到最外层循环：拿到chunk，拼接full_sql_text，yield SSE字符串给前端
3. 前端收到一条SSE消息，然后框架再次调用 next(sql_res)，重复上面整个链条
4. 直到大模型流结束 → llm.stream迭代完毕 → process_stream循环结束退出 → generate_sql 的 `for chunk in res` 循环退出
5. 此时才执行：`self.sql_message.append(AIMessage(full_sql_text))`
6. generate_sql函数返回，外层for循环结束，SSE流关闭

---

# 关键坑点（工程上容易踩）
1. **生成器是懒启动**：`sql_res = self.generate_sql(...)` 这一行不会触发任何LLM调用；只有for遍历的时候才真正开始请求大模型。
2. **结束后置逻辑**：`append(AIMessage)` 在流式传输**全部完成之后**才执行。
   - 如果中途前端断开连接（浏览器取消请求），生成器会抛出异常、提前终止循环，**这行append不会执行**，对话上下文丢失这条SQL消息，需要做好异常捕获。
3. 两层 `full_sql_text`：
   - generate_sql 内部一份，用来构造 AIMessage 存入消息历史
   - 外层还有一份 full_sql_text
   属于冗余缓存，在长输出场景下会占用双倍内存，可以按需优化。
4. yield 只是传递值，**不会把变量同步回上层**，所有累加都是各自函数栈里的局部变量。
5. process_stream 里的 `continue`：遇到满足条件的块，直接yield，跳过后面标签解析逻辑，用来分离思考块和普通内容块。

---

# 数据流简图
```
LLM原始token流 → process_stream【解析、拆content/reasoning】
                      ↓ yield {dict}
              generate_sql【累加完整文本，透传dict】
                      ↓ yield {dict}
              外层chat逻辑【转SSE字符串】
                      ↓ yield "data:xxx\n\n" → 返回前端

【流全部结束之后】generate_sql才执行append(AIMessage)
```
