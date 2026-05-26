# Hermes Agent `!` 前缀 Shell 命令执行功能 — 实现方案

## 一、输入处理流程概述

```
用户输入 → prompt_toolkit handle_enter (cli.py:10122)
         ↓
    _pending_input queue (或 _interrupt_queue)
         ↓
    process_loop() (cli.py:11575)
         ↓
    _looks_like_slash_command() 检查 (cli.py:11634)
         ↓ (是斜杠命令)          ↓ (不是斜杠命令)
    process_command()            self.chat(user_input)
    (cli.py:6389)                → AIAgent.run_conversation()
```

### 关键流程节点

1. **用户按 Enter** → `handle_enter()` (cli.py:10122)
   - 从 prompt_toolkit buffer 获取文本
   - 打包为 payload (可能含 images)
   - 如果 agent 正在运行且不是斜杠命令 → 路由到 `_interrupt_queue`
   - 否则 → 路由到 `_pending_input`

2. **process_loop** (cli.py:11575)
   - 从 `_pending_input` 取出用户输入 (line 11580)
   - 检测文件拖放 `_detect_file_drop()` (line 11619)
   - 检测斜杠命令 `_looks_like_slash_command()` (line 11634)
   - 斜杠命令 → `process_command()` (line 11636)
   - 普通文本 → `self.chat(user_input)` (line 11661)

3. **斜杠命令解析** `_looks_like_slash_command()` (cli.py:1840-1855)
   - 检查文本是否以 `/` 开头
   - 排除文件路径（第一个 word 中含多个 `/` 的）
   - 返回 True/False

4. **斜杠命令分发** `process_command()` (cli.py:6389)
   - `resolve_command()` 解析别名到规范名称
   - 大 if/elif 链分发到各处理函数

---

## 二、关键文件与行号

### CLI 输入处理
| 文件 | 行号 | 功能 |
|------|------|------|
| `cli.py` | 10122-10281 | `handle_enter()` — Enter 键处理，路由输入到队列 |
| `cli.py` | 11575-11695 | `process_loop()` — 主循环，从队列取输入并分发 |
| `cli.py` | 11634 | 斜杠命令检测入口 `_looks_like_slash_command()` |
| `cli.py` | 11636 | 斜杠命令分发 `process_command()` |
| `cli.py` | 11661 | 普通聊天 `self.chat(user_input)` |

### 斜杠命令系统
| 文件 | 行号 | 功能 |
|------|------|------|
| `cli.py` | 1840-1855 | `_looks_like_slash_command()` — 判断是否为斜杠命令 |
| `cli.py` | 6389 | `process_command()` — 斜杠命令分发入口 |
| `hermes_cli/commands.py` | 45-58 | `CommandDef` 数据类定义 |
| `hermes_cli/commands.py` | 64-215 | `COMMAND_REGISTRY` — 命令注册表 |
| `hermes_cli/commands.py` | 222-227 | `resolve_command()` — 名称/别名解析 |

### Terminal Tool（Shell 命令执行）
| 文件 | 行号 | 功能 |
|------|------|------|
| `tools/terminal_tool.py` | 1628-1668 | `terminal_tool()` — 核心命令执行函数 |
| `tools/terminal_tool.py` | 2321-2332 | `_handle_terminal()` — tool 调用入口 |
| `tools/terminal_tool.py` | 2334-2342 | `registry.register("terminal", ...)` — 工具注册 |

### Gateway 模式
| 文件 | 行号 | 功能 |
|------|------|------|
| `gateway/run.py` | 5016-5028 | 命令提取和别名解析 |
| `gateway/run.py` | 5085-5094 | 命令分发 (new, help, commands...) |
| `gateway/platforms/base.py` | 920-936 | `is_command()` / `get_command()` — 消息级命令检测 |
| `hermes_cli/commands.py` | 282-307 | `GATEWAY_KNOWN_COMMANDS` 和 `is_gateway_known_command()` |

---

## 三、`!` 前缀插入位置建议

### 主要修改位置：`process_loop()` (cli.py:11634 附近)

在斜杠命令检测**之前**，添加 `!` 前缀检测：

```python
# === 新增：! 前缀 shell 命令直接执行 ===
# 位于 cli.py process_loop() 中，约 line 11633 (在 _file_drop 检测之后、_looks_like_slash_command 之前)
if not _file_drop and isinstance(user_input, str) and user_input.lstrip().startswith("!"):
    shell_cmd = user_input.lstrip()[1:].strip()  # 去掉 ! 前缀
    if shell_cmd:
        _cprint(f"\n💻 {shell_cmd}")
        try:
            from tools.terminal_tool import terminal_tool
            result_json = terminal_tool(command=shell_cmd, timeout=180)
            import json
            result = json.loads(result_json)
            output = result.get("output", "")
            exit_code = result.get("exit_code", 0)
            if output:
                print(output)
            if exit_code != 0:
                _cprint(f"  {_DIM}Exit code: {exit_code}{_RST}")
        except Exception as e:
            _cprint(f"  {_DIM}Error: {e}{_RST}")
        continue
```

### 理由

1. **`process_loop()` 是最佳位置**，因为：
   - 它是所有用户输入的统一入口
   - 斜杠命令 (`/help`) 和普通聊天都在这里分流
   - `!` 前缀与 `/` 前缀是同一层级的"快捷方式"概念

2. **放在 `_detect_file_drop()` 之后**：
   - 文件拖放检测优先级最高（用户拖了文件进来不应该当命令执行）

3. **放在 `_looks_like_slash_command()` 之前**：
   - `!` 和 `/` 是互斥的前缀，不会冲突
   - `!` 优先级与 `/` 相同

### handle_enter() 中的路由也要调整 (cli.py:10222)

```python
# 原代码 line 10222:
if self._agent_running and not (text and _looks_like_slash_command(text)):
# 应改为：
if self._agent_running and not (text and (_looks_like_slash_command(text) or text.lstrip().startswith('!'))):
```

这确保 `!` 命令在 agent 运行时也能正确路由到 `_pending_input` 而不是被当作中断。

---

## 四、Gateway 模式处理

Gateway 模式**也应该支持** `!` 前缀。修改位置：

### gateway/platforms/base.py — 消息级检测

在 `is_command()` (line 920) 附近添加：
```python
def is_shell_exec(self) -> bool:
    """Check if this is a direct shell exec message (e.g., !ls -la)."""
    return self.text.lstrip().startswith("!")

def get_shell_command(self) -> Optional[str]:
    """Extract shell command if this is a ! exec message."""
    if not self.is_shell_exec():
        return None
    return self.text.lstrip()[1:].strip()
```

### gateway/run.py — 命令分发 (line 5016 附近)

在 `command = event.get_command()` 检查之后，添加 `!` 前缀检测：
```python
# Check for direct shell exec (! command)
shell_cmd = event.get_shell_command() if hasattr(event, 'get_shell_command') else None
if shell_cmd:
    from tools.terminal_tool import terminal_tool
    result_json = terminal_tool(command=shell_cmd, timeout=180)
    # ... format and return result
```

---

## 五、需要修改的文件列表

| 优先级 | 文件 | 修改内容 |
|--------|------|----------|
| **P0** | `cli.py` (~line 11633) | `process_loop()` 中添加 `!` 前缀检测和执行 |
| **P0** | `cli.py` (~line 10222) | `handle_enter()` 中确保 `!` 输入路由正确 |
| **P1** | `gateway/platforms/base.py` (~line 920) | 添加 `is_shell_exec()` / `get_shell_command()` |
| **P1** | `gateway/run.py` (~line 5016) | 在命令分发中添加 `!` 前缀处理 |
| **P2** | `hermes_cli/commands.py` | 可选：将 `!` 注册为特殊命令类型 |
| **P2** | `hermes_cli/tips.py` | 添加提示告知用户 `!` 前缀功能 |

### 不需要修改的文件
- `tools/terminal_tool.py` — 直接调用 `terminal_tool()` 函数即可，无需改动
- `run_agent.py` — `!` 命令不经过 agent 循环
- `model_tools.py` — `!` 命令不经过工具调度

---

## 六、实现细节

### 安全考虑
1. **应复用 `terminal_tool()` 的安全检查**：dangerous command approval、tirith 扫描等
2. **不建议绕过 `terminal_tool` 直接 `subprocess.run()`**：会丢失安全检查
3. **`force=True` 参数不应暴露**：`!` 命令仍需经过安全检查

### 输出格式
- 直接 print 到终端，不经过 Rich/Markdown 渲染
- 显示 exit code（非零时）
- 错误信息简洁显示

### 边界情况
- `!` 后无内容 → 忽略（不执行空命令）
- `! ` 多个空格 → strip 后执行
- `!!` → 执行 `!` 命令（shell history 扩展？建议不支持，只看第一个 `!`）
- 多行 `!` 输入 → 只执行第一行或整段作为 shell script

### 历史记录
- `!` 命令应加入 prompt_toolkit 的 FileHistory，方便用户通过 ↑ 箭头回溯
- 已由 `event.app.current_buffer.reset(append_to_history=True)` 自动处理
