# 开发工作流

本项目统一开发规范、验证入口与工具链。生命周期参考 Nightingale，具体实现沿用本仓库的 Go/Gin、Vue 和 embed 发行结构。

## 准备任务

1. 检查 `git status --short`、当前分支和最近提交，确认任务范围与验收步骤，保留其他修改。
2. 按 `AGENT.MD` 读取相关模块与前后端约定。可用 GVA Helper / MCP 时优先获取项目建议。
3. 按任务选择目标分支；参考职责为 main 生产、develop 集成、feature/* 功能、hotfix/* 修复。一个任务/worktree 由一个主要实现者修改代码。
4. 使用 `web/.node-version` 指定的 Node 和 `web/package.json` 指定的 pnpm。Go 版本须满足 `server/go.mod`，验证工具使用 Python 3.11+ 与 GNU Make。

```bash
make frontend-install
make setup-hooks
```

前端命令优先通过 Corepack 选择项目指定的 pnpm；没有 Corepack 时需要自行提供同版本 pnpm。`frontend-install` 会检查版本，并执行 `pnpm install --frozen-lockfile --prod=false`。依赖变动使用指定 pnpm 更新锁文件，审查并提交 `web/pnpm-lock.yaml`，随后重新执行冻结安装。

`setup-hooks` 在本仓库 Git 配置中安装 `.githooks`，对共享该仓库配置的 worktree 生效。已有自定义 hooksPath 或默认 pre-push 时保留原值并返回失败，需把 `make verify` 合并到原有 pre-push。Paseo setup 调用同一安装器；install、verify、verify-all、build-embed 脚本见根目录 `paseo.json`。

## 实现与审查

先分析需求和接口，再设计 Model/请求结构，随后实现 Service、API、Router，最后接入 initialize、插件或前端。前后端契约以后端真实行为及 Swagger 为准；需要并行开发时可使用 Mock。

实施前检查方案的接口、权限、兼容性和验证方法；实施中运行相关行为测试；实现后对照固定基线审查 diff 与调用链。小改动简短记录，跨模块改动说明取舍和受影响路径。修复后重跑受影响检查。

测试使用临时文件和一次性数据库。AST/代码生成测试的写入必须落在临时目录；MCP 客户端测试使用进程内测试服务器，默认验证不连接开发服务。临时 Git 仓库清除继承的仓库环境变量，验证过程保持任务仓库的源码、索引、引用和配置不变。

## 统一验证

```bash
make verify
make verify-all
```

| 入口 | 执行范围 |
| --- | --- |
| `make verify` | 相对基线的 Go 文件格式、工作流设施测试、冻结安装、前端 Node 测试与生产构建、普通 Go 全包构建与测试、embed 全包构建及资源/路由测试 |
| `make verify-all` | 上述内容，加全包 Go vet、全包竞态测试及 embed 资源/路由竞态测试 |
| `make frontend-build` | 冻结安装并构建前端 |
| `make frontend-verify` | 冻结安装、前端测试与构建，准备嵌入目录 |
| `make build-embed` | 构建并嵌入当前前端，输出 `build/server` |

本地、pre-push、Paseo 和 CI 调用同一验证器；CI 执行 `make verify-all`。Go 命令在 `server/` 下运行，前端命令在 `web/` 下运行。检查保留失败退出码，测试输出分别统计通过、失败和跳过；跳过不计作已验证。当前前端构建失败时不使用旧 dist 执行 embed 检查。

格式检查默认相对 main 的 merge-base（不存在则用 HEAD），并包含未跟踪文件。需要固定基线时设置 `GVA_VERIFY_BASE=<commit>`；CI 使用事件基线。Go 格式检查覆盖变更文件，构建和测试始终覆盖全包。普通 Go 构建仍无需前端产物。

前端 `pnpm lint` 是显式专项检查，目前旧源码存在 lint 基线问题，尚未加入默认门禁；`verify-all` 不代表这些问题已通过或被修复。具体基线与实际验证结果见[工作流验证记录](development-workflow-validation.md)。

## 验收与交付

根据变更选择实际 UI/API 场景，覆盖成功、错误及权限拒绝。交付记录包含版本、命令、实际结果、验收步骤和未验证项；将自动测试、Agent 浏览器检查、人工验收及发布结果分别说明。

本阶段没有移植 Nightingale 的隔离预览管理器、域名槽位或 build ID 系统。需要运行实例验收时显式准备隔离配置与数据，不把 Nightingale 的地址或数据用于本项目。后续预览需单独适配 YAML、初始化、JWT 和上传目录。

提交使用 `type(scope): description`。沿用会话中的授权完成提交、推送、PR、合并和发布；有本地通过记录不代表远端 CI 或人工验收已通过。接口、配置与使用行为变化时同步相关文档和需求记忆。
