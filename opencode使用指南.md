# opencode 使用指南

> 创建时间：2026-10-13
> 目的：帮助用户了解 opencode 的规则注入、命令/技能加载、会话记忆与权限机制，从而更好地跨会话使用 AI 助手。
> 依据：opencode 官方文档（docs/rules、docs/commands、docs/skills、docs/permissions、docs/cli）——均为已核实内容；文中标注【实证】的为本机实际验证。

---

## 一、机制总览

```
opencode 启动
 ├─ 1. 规则注入（系统上下文，每个会话自动带上）
 │     项目 AGENTS.md → 全局 ~/.config/opencode/AGENTS.md → ~/.claude/CLAUDE.md（回退）
 │     + opencode.json 的 instructions 字段挂载的文件
 ├─ 2. 命令发现（/xxx 可用）
 │     ~/.config/opencode/commands/*.md（全局）+ .opencode/commands/*.md（项目）
 ├─ 3. 技能发现（仅"名字+描述"进上下文，全文按需加载）
 │     ~/.config/opencode/skills/*/SKILL.md、~/.agents/skills/*/SKILL.md、
 │     ~/.claude/skills/*/SKILL.md + 三个项目级对应目录
 └─ 4. 权限策略加载（edit/bash/... 的 allow/ask/deny）
       opencode.json 的 permission 字段（由程序强制，不依赖模型记忆）
```

**关键认知**：加载路径与 opencode 二进制安装位置（npm 目录）**无关**，一切按配置目录（XDG 惯例）发现。

---

## 二、规则注入（跨会话持久记忆的正解）

### 2.1 加载层级与优先级

| 层 | 位置 | 作用域 | 是否自动注入 |
| -- | ---- | ---- | ---- |
| 项目规则 | `<项目根>/AGENTS.md` | 该项目 | ✅ 每会话 |
| **全局规则** | **`~/.config/opencode/AGENTS.md`** | **所有项目** | ✅ 每会话 |
| 指令挂载 | `opencode.json` 的 `instructions: [...]` | 随配置生效 | ✅ 每会话 |
| Claude 兼容 | `CLAUDE.md` / `~/.claude/CLAUDE.md` | 回退（同名时被 AGENTS.md 覆盖） | ✅ |

- 同类别取第一个匹配（AGENTS.md 优先于 CLAUDE.md）；
- `instructions` 支持通配符与远程 URL（5 秒超时）；
- 这些内容属于**系统上下文**，不走对话历史——**上下文压缩（compaction）摘要的是对话，动不到它们**。

### 2.2 为什么"让助手先读 profile.md"不可靠

让助手在会话中"记得去读某文件"依赖对话记忆，会随压缩/长会话稀释；而写进 AGENTS.md 是**启动即注入**，两者可靠性不同量级。

### 2.3 本机当前落地情况【实证】

- 已创建 **`C:\Users\gaohu\.config\opencode\AGENTS.md`**：内容 = 阶段门控硬规则（未经明确指令禁止改文件）+ 用户使用风格画像（源自 `sqlbot_pro/selfdoc/profile.md` 审阅确认版）。
- 效果：**此后每个 opencode 会话（任何项目）自动携带**，不依赖助手记忆。
- 项目内 `selfdoc/profile.md` 保留作为人读的源文档；两者更新时注意同步。

---

## 三、命令机制（`/xxx`）

### 3.1 加载位置

- 全局：`~/.config/opencode/commands/<name>.md`
- 项目：`.opencode/commands/<name>.md`
- 文件名即命令名（`test.md` → `/test`）；**自定义可覆盖内置命令**（如同名覆盖 `/init`）。

### 3.2 文件格式

```markdown
---
description: 命令描述（TUI 中显示）
agent: build            # 可选：指定执行 agent
model: provider/model   # 可选：指定模型
subtask: true           # 可选：强制子代理执行（不污染主上下文）
---

提示词正文。特殊语法：
- $ARGUMENTS / $1 $2 $3   位置参数替换
- !`git log -10`           执行 bash 并注入输出
- @src/foo.ts              自动内联文件内容
```

【实证】本机 `~/.config/opencode/commands/` 已有 `cli-anything*.md` 等 6 个自定义命令。

---

## 四、技能机制（SKILL.md，按需加载）

### 4.1 六个搜索位置

| 位置 | 说明 |
| ---- | ---- |
| `~/.config/opencode/skills/<name>/SKILL.md` | 全局·原生 |
| **`~/.agents/skills/<name>/SKILL.md`** | **全局·agent 兼容格式** |
| `~/.claude/skills/<name>/SKILL.md` | 全局·Claude 兼容 |
| `.opencode/skills/`、`.agents/skills/`、`.claude/skills/` | 项目级（从 cwd 向上走到 git 根沿途发现） |

【实证】本机 `~/.agents/skills/` 下的 understand 系列技能已在会话中可见（系统上下文含 `<available_skills>` 列表）。

### 4.2 加载模型：发现 ≠ 注入

- **启动时**只把「名字 + 描述」放进系统上下文（`<available_skills>`）；
- **助手调用 `skill` 工具时**才注入 SKILL.md 全文——所以技能再多也不挤占上下文；
- `metadata: { opencode/autoinvoke: "false" }`：不出现在自动选择引导中（仅可按名手动加载）；
- `metadata: { opencode/slash: "true" }`：暴露为 `/name` 命令。

### 4.3 命名与排障

- `name` 规则：`^[a-z0-9]+(-[a-z0-9]+)*$`，1~64 字符，**必须与目录名一致**；`name`、`description` 必填；
- 不出现时检查：是否全大写 `SKILL.md`、frontmatter 是否齐全、是否被 `permission.skill` deny、autoinvoke 是否为 false。

### 4.4 技能权限

```json
{ "permission": { "skill": { "*": "allow", "experimental-*": "ask", "internal-*": "deny" } } }
```

---

## 五、会话与记忆管理

### 5.1 三层"记忆"及其失效模式

| 层 | 存储 | 失效模式 | 跨会话？ |
| -- | ---- | ---- | ---- |
| 系统上下文（规则/技能列表/权限） | 每次启动重新注入 | 基本不失效（对话压缩动不到它） | ✅ 靠配置文件 |
| 对话历史 | 会话内滚动 | 超限自动**压缩**（摘要化，细节丢失） | 会话内保留 |
| 会话本身 | 磁盘持久化 | 开新会话才为空 | ✅ 靠 `-c/-s` 恢复 |

**结论**：
- "/exit 后什么都不记得"只发生在**开新会话**时；用恢复命令可完整续接（非摘要）。
- "长对话忘事"= 对话层压缩；缓解 = 关键规则放系统层（AGENTS.md）、任务状态放 todo、阶段结论即时回填文档（项目内 markdown 即外部记忆）。

### 5.2 会话恢复命令

| 命令 | 作用 |
| ---- | ---- |
| `opencode -c`（`--continue`） | 继续**最近一次**会话（完整历史） |
| `opencode -s <sessionID>` | 恢复指定会话 |
| `opencode session list [-n 20]` | 列出历史会话（拿 ID） |
| `opencode --fork -c` | 基于恢复的会话开分支 |
| TUI 内 `/undo` `/redo` | 回滚/重做最近的文件修改 |
| `opencode export/import` | 导出/导入会话 JSON |

**推荐节奏**：进行中的任务用 `-c` 续接；任务闭环（验证通过、结论回填）后再开新会话。

### 5.3 压缩控制

- 自动压缩默认开启；`OPENCODE_DISABLE_AUTOCOMPACT=1` 可关闭，但上下文硬上限仍在，**不建议关**；
- 抗压缩的正确姿势：规则进 AGENTS.md、进度进 todo、结论进项目文档。

### 5.4 Plan mode（阶段门控的工具层实现）

- TUI 按 `Tab` 切换 Plan/Build：Plan 模式下助手**只读不写**；
- 适合「先讨论方案、后动手」的节奏：讨论全程 Plan，拍板后切 Build。

---

## 六、权限门控（唯一 100% 的"防自主修改"保证）

### 6.1 原理

规则/画像只提高助手的**遵守概率**；`permission` 配置由 **opencode 程序强制执行**——助手失忆也拦得住。

### 6.2 配置（`opencode.json` / `opencode.jsonc`）

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "permission": {
    "*": "allow",           // 默认放行
    "edit": "ask",          // ★ 一切文件修改（edit/write/patch）先弹确认
    "bash": {
      "*": "ask",           // shell 命令弹确认（噪音大，可按需放宽）
      "git status*": "allow",
      "rm *": "deny"        // 直接禁止
    },
    "webfetch": { "*": "ask", "https://opencode.ai/*": "allow" }
  }
}
```

- 三个动作：`allow`（直接执行）/ `ask`（弹窗确认）/ `deny`（禁止）；
- 模式通配 `*` `?`，**最后匹配的规则生效**（宽泛规则放前、具体规则放后）；
- `ask` 弹窗三选：`once`（仅本次）/ `always`（本会话内同类放行）/ `reject`；
- 可用环境变量 `OPENCODE_PERMISSION` 内联注入；可用 `agent` 字段按 agent 差异化。

### 6.3 建议档位（按用户风格）

| 档位 | 配置 | 适合 |
| ---- | ---- | ---- |
| 严（推荐先用） | `"edit": "ask"` | 每次改文件都经你确认，与"方案审阅制"习惯天然契合 |
| 宽 | `"edit": "allow"` + 依赖 AGENTS.md 硬规则 | 信任流程，换流畅度 |

---

## 七、针对本用户的工作流最佳实践（总结）

1. **持久习惯层**：`~/.config/opencode/AGENTS.md` 已放硬规则 + 画像（✅ 已落地）；项目级再放 `AGENTS.md`（构建/测试命令、项目约定，可用 `/init` 生成）。
2. **硬保证层**：✅ 已启用（2026-10-13）——`~/.config/opencode/opencode.jsonc` 配置 `"permission": { "edit": "ask" }`，一切文件修改先弹窗确认，重启 opencode 生效；`bash` 等其余工具维持默认放行。
3. **会话层**：进行中任务 `opencode -c` 续接；新开会话前确认阶段结论已回填 `selfdoc/*.md`。
4. **讨论层**：讨论期间用 Plan mode（Tab）；拍板后切 Build。
5. **文档层**：项目 `selfdoc/` 即外部记忆——问题、决策、进度都落文档，助手换会话也能接上。

---

## 八、常见误区速查

| 误区 | 事实 |
| ---- | ---- |
| "opencode 装在 npm 目录，所以加载 npm 下的东西" | ❌ 加载只认配置目录（`~/.config/opencode`、`~/.agents` 等） |
| "助手读过 profile.md 就记住了" | ❌ 对话记忆会被压缩；必须放进 AGENTS.md/instructions 才稳定 |
| "/exit 后历史丢了" | ❌ 历史在磁盘上，`-c`/`-s` 可完整恢复；开新会话才是空的 |
| "关掉压缩就永远不会忘" | ❌ 上下文硬上限仍在；正确做法是分层记忆（系统层/对话层/文档层） |
| "技能多会占用上下文" | ❌ 只有名字+描述进上下文，全文按需加载 |
| "AGENTS.md 和 permission 二选一" | 互补：AGENTS.md 管行为倾向（概率），permission 管硬拦截（确定） |
