# GLaDOS 自动签到故障修复交接文档

## 1. 交接信息

- 仓库：`zzusec/2026-glados-checkin`
- 默认分支：`main`
- 仓库性质：公开 Fork，来源为 `lankerr/2026-glados-checkin`
- 处理日期：2026-09-20
- 当前状态：已恢复，GitHub Actions 工作流为 `active`，最终真实签到运行成功
- 最终修复提交：`9a071c2`

## 2. 故障现象

用户反馈仓库已经较长时间没有自动签到。检查发现：

- 仓库最后一次旧活动：2026-07-08 00:32:03 UTC
- 最后一次旧定时签到：2026-09-06 06:09:15 UTC
- 主签到工作流 `GLaDOS 2026 Checkin` 状态：`disabled_inactivity`
- 独立保活工作流 `Keep Repository Active` 状态：`disabled_fork`

因此，9 月 6 日之后没有新的 schedule 运行记录，并不是签到脚本一直在运行但签到失败，而是主定时工作流已经停止触发。

## 3. 根因

### 3.1 主工作流因仓库长期无活动被停用

仓库从 2026-07-08 起没有新的提交活动。公开仓库长时间不活跃后，GitHub 自动把定时工作流标记为 `disabled_inactivity`。

### 3.2 原保活工作流在 Fork 中没有启用

原项目提供 `.github/workflows/keep-alive.yml`，但该仓库是 Fork。此工作流在 Fork 创建后一直处于 `disabled_fork`，没有产生任何新的保活提交。

仓库历史中 2026-07-08 以前的 `github-actions[bot]` 保活提交来自上游历史，不代表该 Fork 的保活任务曾正常运行。

### 3.3 签到失败不能可靠反映到 Actions

原来的 `checkin.py` 只有在完全没有 Cookie 时退出非零。账号网络错误、API 错误或签到失败时，脚本仍可能以退出码 0 结束，造成：

- Actions 运行记录显示成功，但实际签到失败；
- 工作流中的 `Retry on Failure` 无法被触发；
- 无法仅根据绿色状态判断签到是否成功。

### 3.4 GLaDOS 已更改重复签到成功文案

恢复后观察到当前重复签到响应为：

```text
Today's observation logged. Return tomorrow for more points.
```

旧代码只识别包含 `Checkin` 的消息，收紧成功判定后曾把该新版成功响应误判为失败。最终已加入兼容。

## 4. 已实施改动

### 4.1 合并保活与签到工作流

文件：`.github/workflows/checkin.yml`

- 保留每日两次签到：
  - `30 1 * * *`：北京时间 09:30
  - `30 13 * * *`：北京时间 21:30
- 新增每月两次保活：
  - `17 0 1,15 * *`：每月 1 日和 15 日 00:17 UTC
- 签到 job 会跳过保活 cron。
- 保活 job 只在保活 cron 触发时运行。
- 保活 job 仅申请 `contents: write` 权限。
- 保活提交使用 `[skip ci]`，避免提交时间戳后递归触发签到。

同时删除原来的 `.github/workflows/keep-alive.yml`，避免独立工作流继续处于 `disabled_fork` 并造成误导。

### 4.2 修复重试逻辑

原逻辑使用两个独立步骤：第一个步骤失败后运行第二个重试步骤。即使重试成功，前一步已经失败，job 仍可能保持失败状态。

现在在同一个 shell step 中最多执行两次：

1. 第一次执行 `python checkin.py`；
2. 失败后等待 60 秒；
3. 第二次执行；
4. 第二次成功则整个 step 成功，否则退出 1。

重试由 job 的 10 分钟总超时控制，不再让两次执行和等待共享一个过短的 5 分钟 step 超时。

### 4.3 让真实签到失败返回非零状态

文件：`checkin.py`

脚本会统计成功账号数量。如果不是所有账号都成功，则在推送通知后执行：

```python
if success_cnt != len(cookies):
    sys.exit(1)
```

这使 GitHub Actions 的状态能够反映实际签到结果，并让工作流重试生效。

### 4.4 明确识别当前已知成功响应

当前识别以下成功响应前缀：

```python
(
    "Checkin!",
    "Checkin Repeats!",
    "Today's observation logged.",
)
```

其中后两项均表示当天已经签到，不应重试或标记失败。

### 4.5 更新文档

`README.md` 已更新：

- 保活任务改为集成在 `checkin.yml` 中；
- 保活频率改为每月 1 日和 15 日；
- 补充新版重复签到响应说明；
- 明确 Fork 后仍需先启用工作流。

## 5. 提交记录

按时间顺序：

| 提交 | 说明 |
| --- | --- |
| `e414c36` | 合并保活任务、删除独立保活工作流、修复失败退出和重试 |
| `dde6808` | 将保活改为每月两次、放宽重试超时、收紧成功判断 |
| `9a071c2` | 兼容当前 GLaDOS 重复签到成功文案 |

## 6. 验证记录

### 6.1 本地验证

已完成：

- `python3 -m py_compile checkin.py`
- GitHub Actions YAML 结构解析
- `git diff --check`
- 模拟签到结果回归测试：
  - `Checkin! Get 1 Day`：退出码 0
  - `Checkin Repeats! Please Try Tomorrow`：退出码 0
  - `Today's observation logged. Return tomorrow for more points.`：退出码 0
  - `Checkin failed`：退出码 1
  - `Network Error`：退出码 1

### 6.2 GitHub Actions 真实验证

| Run ID | 时间（UTC） | 结果 | 说明 |
| --- | --- | --- | --- |
| `35489103794` | 2026-09-20 04:25:26 | success | 首次恢复运行，完成当天签到 |
| `35490034098` | 2026-09-20 04:47:44 | failure | 暴露新版重复签到成功文案未被识别 |
| `35491244151` | 2026-09-20 05:16:16 | success | 最终修复后的真实运行验证通过 |

最终确认：

- 工作流状态：`active`
- `checkin` job：`success`
- `Run Checkin` step：`success`
- `keep-active` job：普通 push 运行中按设计跳过
- 本地 `main` 与 `origin/main` 同步

## 7. 当前运行方式

### 签到任务

- 每天北京时间 09:30
- 每天北京时间 21:30
- 手动 `workflow_dispatch`
- 普通推送到 `main` 时也会执行；包含 `[skip ci]` 的提交除外

### 保活任务

- 每月 1 日 00:17 UTC
- 每月 15 日 00:17 UTC
- 只更新时间戳文件 `.github/last-active.txt`
- 不执行签到

### Secrets

工作流当前使用：

- `GLADOS_COOKIE`：必需
- `PUSHPLUS_TOKEN`：可选

不要把 Secret 值写入代码、日志、Issue 或本交接文档。

## 8. 后续检查项

### 8.1 检查第一次真实保活运行

下一次预期保活时间为：

```text
2026-10-01 00:17 UTC
```

届时确认：

1. `keep-active` job 成功；
2. `.github/last-active.txt` 出现新的 bot 提交；
3. 提交信息为 `chore: keep repository active [skip ci]`；
4. 工作流状态仍为 `active`；
5. 保活提交没有额外触发签到。

### 8.2 观察下一批 schedule 运行

确认后续 09:30 和 21:30 的 schedule 运行持续出现，并检查 `Run Checkin` step 是否成功。不要只看 workflow 是否被触发。

### 8.3 关注 GLaDOS 响应文案变化

当前成功判断有意只接受明确的成功前缀。若 GLaDOS 再次修改成功响应，Actions 会标红而不是静默误报成功。

处理步骤：

1. 查看失败日志中的 `结果:`；
2. 先确认该响应是否确实代表签到成功；
3. 仅在确认后将新的稳定前缀加入 `checkin_succeeded`；
4. 补充成功和失败退出码回归测试；
5. 手动运行工作流验证。

## 9. 已知限制

- GitHub schedule 不是严格实时调度器，可能延迟，极端情况下也可能漏跑。要求更高可靠性时，继续保留 README 中的外部 cron 方案作为备选。
- 新保活 job 尚未经历第一次真实的保活 schedule；首次实际验证需等到 2026-10-01 00:17 UTC。
- `checkin.py` 支持 `PUSH_LEVEL`、Telegram Token 和 Chat ID，但当前 GitHub Actions 只注入了 `GLADOS_COOKIE` 与 `PUSHPLUS_TOKEN`。Telegram 和 `PUSH_LEVEL` 的工作流接线不在本次故障修复范围内。
- 成功判定依赖 API 返回文案前缀。如果 API 提供稳定的机器可读状态字段，后续应优先改为依据状态字段，而不是继续累积文案。

## 10. 故障排查速查

### 没有新的定时运行记录

1. 查看工作流是否为 `active`；
2. 查看仓库是否超过 60 天无提交活动；
3. 查看最近一次保活 job 和时间戳提交；
4. 检查工作流是否只存在于默认分支；
5. 必要时修改 schedule 并由有写权限的账号提交，或在 Actions 页面重新启用。

### 工作流运行但签到失败

1. 查看 `Run Checkin` 日志中的 `结果:`；
2. 若为 `Network Error`，检查三个 GLaDOS 域名的可用性；
3. 若为认证相关响应，更新 `GLADOS_COOKIE`；
4. 若为新的成功文案，不要直接放宽到模糊包含匹配，先确认语义并添加精确前缀；
5. 重新手动运行并确认所有账号都成功。

### 紧急回滚

如需回滚本次三个代码修复提交，应从新到旧执行 revert，并在推送前检查工作流内容：

```bash
git revert 9a071c2
git revert dde6808
git revert e414c36
```

注意：回滚会恢复本次已经确认存在的停签和误报问题，除非有替代方案，否则不建议执行。
