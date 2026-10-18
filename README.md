# Jun516 OSS Agent Contributor — autonomous PR prototype (v0.2.1)

**目的：** 由 GitHub Actions 每 3 小时自动寻找高质量 AI Agent / AI 全栈项目的真实 Bug，使用 Codex 完成最小修复，经独立测试与第二个只读 Codex 审核通过后，**无需每个 PR 再询问用户**，自动 Fork、Push 和向上游提交 **一个** PR。关闭电脑也不影响已经部署的 GitHub Actions。

**当前状态：工程已生成并通过离线测试，尚未部署到 GitHub，尚未执行任何真实跨仓库 PR。** 这不是可保证无故障的无人值守生产系统。实际运行需要用户一次性提供可信执行平台、API/ GitHub 机密和 GitHub Actions 权限。所有 PR 质量判断需在真实项目上验证。

## 主体流程

```
GitHub Actions 17 */3 * * * (UTC) / workflow_dispatch
  discover: GitHub只读查询 → 5k stars / issue / license / guidelines / collision checks
  propose: pinned upstream SHA + Codex (:workspace) → focused patch & test commands
  verify: fresh clean checkout → exact patch replay → focused tests (no publishing token)
  review: second Codex (:read-only) → approve LOW risk only (no publishing token)
  publish: SHA-bound reports + current upstream check + rate gate → Fork/Push/PR
```

每个扫描最多选择 1 个候选，每 24 小时最多新开 4 个 PR（按照当前 `Jun516` 账号的全部近期 PR 计数，包含手动创建的 PR；并非仅统计机器人），**不会自动合并、不发送催审评论、不更新已有 PR**。如果没找到真实可复现且未被认领的问题、CI/测试失败、Review 不批准或凭证缺失，自动停止本轮，不造 PR。

本项目根据用户最新明确指示，**取代上传的 Contributor Mode 对逐次 Fork/Push/PR 必须人工确认的要求**，但保留其质量标准以及 GitHub、平台和仓库自身规定；详见 `policies/CONTRIBUTOR_MODE_SOURCE.md`。

## 一次性部署（使用可信终端）

**原因：** 当前 ChatGPT GitHub 连接没有新建仓库、写入 GitHub Actions Secrets 的接口，不能在聊天中替你完成这两项动作，不能把本地 ZIP 当成已上线。

1. 在你的 Windows 电脑解压本 ZIP，安装 Git、GitHub CLI（`gh`），执行 `gh auth login --web`，确认 `gh api user --jq .login` 输出 `Jun516`。在解压目录执行 `./deploy.ps1`。它会新建 `Jun516/oss-agent-contributor`（公开仓库）并推送整个控制器工程；如果仓库已经存在，将停止自动推送，以免覆盖已有项目。Linux/macOS 使用 `./deploy.sh`。
2. 在控制器仓库 **Settings → Secrets and variables → Actions → Secrets** 配置两个 Secret：
   - `OPENAI_API_KEY`：可用于 Codex Action 的 OpenAI **API** 凭证；与 ChatGPT Plus 订阅无关。设置预算上限、使用提醒。
   - `OSS_DISCOVERY_TOKEN`：**推荐配置**用于跨仓库只读查询的专用 GitHub 用户令牌。使用权限尽可能少、能够读取公开仓库 Issue 和搜索 API 的令牌，不要使用发布用的 `OSS_BOT_TOKEN` 替代。未配置时回退到仓库自带的 `GITHUB_TOKEN`；它可能因为跨仓库访问权限返回 HTTP 403。仅保存为 GitHub Actions Secret。
   - `OSS_BOT_TOKEN`：**仅该系统发布 Job 使用**的 `Jun516` GitHub 授权 Token。需能对 `Jun516` 创建公共 Fork/写入个人 Fork，并能向目标上游发起 PR；能否跨仓库创建 PR 取决于 Token 类型、目标仓库政策和 GitHub 设置。当前发布器强制校验 `gh api user` 必须返回 `Jun516`，因此请使用能够以 `Jun516` 用户身份执行跨仓库 Fork / PR 的个人访问令牌。优先确认 Fine-grained Token 是否能完成目标公共仓库的完整写入链；某些跨仓库场景可能需要具有 `public_repo` 权限的 Classic PAT。Classic PAT 权限更宽，应缩短有效期、定期轮换，并设置预算和监控。不要使用 GitHub Actions 内置 `GITHUB_TOKEN` 冒充跨仓库发布 Token。绝不要把密钥发送到聊天中。
3. 打开控制器仓库 **Actions**，手动执行一次 `OSS Contributor (autonomous)`，阅读 Scan、Propose、Test、Review、Publication artifacts。若发现候选且全部验证通过，会按照本配置自动创建一个 PR；没有候选则不会生成 PR。这也是首次真实端到端验证方式。
4. 如果想随时**暂停自动发布**，在控制器仓库 **Actions → Variables** 创建 `PAUSE_AUTOPUBLISH=true`；会继续发现候选和验证，但 Publish Job 不运行。设为 `false` 或删除变量才能恢复自动发布。

> GitHub Actions `schedule` 是尽力调度，不保证严格三小时整点执行；GitHub 还可能停用长时间不活跃的公开仓库的定时工作流。若需要运营级 24/7 SLA，应换用有运行监控的长期云端 Runner/调度服务。

## 安全与质量限制

- 只允许公开、未归档、至少 5000 Stars、近约 12 个月活跃、许可允许的仓库；排除 `exa-labs/exa-py`。
- 读取仓库贡献指导和 AGENTS.md。若禁止 AI PR、被认领、重复 PR、需维护者审批、最新主分支变动，拒绝提交。
- 单个 Issue 的范围最多 5 个文件；不修改 Actions、CI、授权与策略、许可、锁文件、依赖清单、隐藏文件或 Enterprise 源码；不提交二进制或符号链接。
- 修复和测试 Job **没有发布 Token**；最后的 Publish Job **不会运行第三方仓库的脚本或依赖**。
- 补丁 SHA-256、测试命令 SHA-256、PR 文本 SHA-256、基础 Commit SHA 四项绑定；只读第二审核 Agent 必须判定低风险通过。
- PR 正文披露 AI 自动贡献，维护者仍拥有最终 Review/合并权。
- 第三方项目的构建 / 测试是**不可信代码**。虽然与发布凭证隔离，但 GitHub-hosted runner 不是强隔离机密执行沙箱。不要在修复和测试阶段注入额外凭证；高安全场景需加入容器和 egress 限制、构建产物证明和独立安全审查。
- 成功的单元测试与第二 AI 审核依然不能保证修复的语义正确，更不能保证上游合并。

## 开发者自测

```bash
python -m pytest -q
python -m compileall -q oss_contributor
```

核心逻辑只有标准库依赖；测试需要 pytest，工作流使用 Python、Git、GitHub CLI、Codex Action。`tests/` 含真实本地 Git patch replay + focused pytest 检查、风险审查门禁、仓库规则与代码路径保护等。**离线测试通过不代表云端真的创建了 PR。**

## 必须完成的首次验收

记录这五项真实证据：① 成功的 Actions Run URL；② 已生成的 scan-report；③ 独立 verify 测试报告（指定 upstream SHA/patch SHA）；④ 只读审核报告；⑤ 若通过，则 GitHub PR URL、CI 状态以及 Review 状态。没有第五项不代表失败：可能根本没有合格候选。实际失败须按日志排查，不要编造 PR。

## 首次云端巡检排障（2026-10-18）

首次真实运行 `39107679921` 的 Discover 遇到 `/search/issues` HTTP 403，但旧版本把异常误判为扫描成功。本次修复会将 GitHub API 403、超时、鉴权和限流错误写进 `scan-report` 的 `incomplete` 状态，同时使 Discover Job 失败，避免声称“没有合格候选”。如果再次遇到 403，查看 GitHub 返回的错误摘要和 `rate_remaining`、`retry_after`；权限不足时配置独立只读 `OSS_DISCOVERY_TOKEN`，遇到限流时等待重试。扫描完整结束且没有异常时，才将“无候选”视为正常。

请保留 `PAUSE_AUTOPUBLISH=true`，直到真正完成发现、修复、独立测试、审核与发布权限的受控端到端验收。
