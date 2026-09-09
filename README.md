# 滴答清单 Alfred Workflow v1.11

通过[滴答官方 MCP](https://help.dida365.com/articles/7438132116019216384)向收集箱添加任务，保留原有输入和预览方式。

## 安装与授权

1. 需要 macOS、Alfred Workflow 支持及 `/usr/bin/python3`（Python 3.9 或更新版本）。仅使用标准库，无需安装 Python 模块。
2. 双击导入 `滴答清单 v1.11.alfredworkflow`，替换旧版 workflow。
3. 在滴答网页版「头像 → 设置 → 账户与安全 → API 口令」创建并复制 Token。
4. 在 Alfred 输入 `tick_auth <token>`，回车授权。验证连接、工具能力和收集箱成功后才保存配置；失败不会覆盖原授权。

`tick_auth` 替代原来的 `tick_login`，不再使用用户名、密码或网页版 Cookie。旧配置需要重新授权。Token 失效或撤销后，再次执行 `tick_auth <token>`。

配置保存在 `~/.ticktick`，以 `0600` 权限原子替换；Token 使用固定密钥的 XOR＋位旋转混淆，并带有配置版本标记。**这是可逆混淆，不是强加密**，用于避免直接保存明文；了解代码的人可以还原。成功授权会移除旧配置中的用户名、密码和 Cookie。配置解码失败时要求重新授权，不回退读取明文。程序不在日志或通知中输出 Token。

## 使用

输入 `tick 任务 [日期] [时间]`，查看预览后回车创建任务。日期和时间可省略，任务始终进入收集箱。

- 日期：`tomorrow` / `tmr`、`mon` 至 `sun`、`next mon` 至 `next sun`、`month-day`。
- 重复：`every mon` 至 `every sun`（每周）、`every month-day`（每月）、`every hour:minute`（每天）。沿用原解析器；每天重复需要指定时间。
- 时间：`hour:minute`；指定时间时保留提前一分钟提醒。
- 优先级：`!` 低、`!!` 中、`!!!` 高。

例如：`tick 买牛奶 tmr 18:00`、`tick !!!周会 every mon 09:00`。

沿用本机日期、时间及预览规则，不增加 AI 解析。已有解析器的日期选择规则保持不变。提交超时或返回结果不确定时不会自动重发；请先检查收集箱，避免手动重试造成重复任务。

## 开发与验证

```sh
/usr/bin/python3 build_workflow.py
TZ=Asia/Shanghai PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tests -v
```

安装包只包含明确列出的脚本、workflow 配置及图标，不包含本机凭据。测试使用临时配置和模拟 MCP 响应，不修改真实账户或 `~/.ticktick`。

脚本接口：`tick.py auth <token>`、`tick.py parse '任务 [日期] [时间]'`、`tick.py '任务 [日期] [时间]'`。命令行直接传 Token 可能被 shell 历史记录保存；日常授权请使用 Alfred 入口。

# English

This workflow adds tasks to the inbox through the [official Dida365 MCP service](https://help.dida365.com/articles/7438132116019216384). It requires Alfred workflow support and `/usr/bin/python3` (Python 3.9+), with no third-party Python dependencies.

Import `滴答清单 v1.11.alfredworkflow`, replacing the previous workflow. Generate an API token in the Dida365 web app under Settings → Account & Security → API Token, then enter `tick_auth <token>` in Alfred. Authorization validates the MCP connection, tools and inbox before replacing the configuration. Failed authorization preserves the previous configuration.

The old username/password `tick_login` command is removed. Reauthorize old configurations and revoked or expired tokens using `tick_auth`. The versioned `~/.ticktick` configuration is replaced atomically with owner-only (`0600`) permissions. Tokens use reversible fixed-key XOR and bit rotation, **not strong encryption**. Successful authorization removes old usernames, passwords and cookies. Invalid configuration does not fall back to plaintext. The program does not print tokens in logs or notifications.

Task entry remains `tick task [date] [time]`, with the same preview and date-selection rules:

- Dates: `tomorrow` / `tmr`, `mon`–`sun`, `next mon`–`next sun`, `month-day`.
- Recurrence: `every mon`–`every sun` (weekly), `every month-day` (monthly), `every hour:minute` (daily; the existing parser requires a time).
- Time: `hour:minute`, with a reminder one minute before the task.
- Priority: `!` low, `!!` medium, `!!!` high.

Tasks always go to the inbox. There is no AI parsing or automatic retry of task submissions. If the result is uncertain, check the inbox before retrying manually. Development tests use simulated responses and temporary configuration only. The build script packages an explicit list of files, excluding credentials. Passing a token directly on a terminal command line may save it in shell history; use the Alfred authorization entry for normal use.
