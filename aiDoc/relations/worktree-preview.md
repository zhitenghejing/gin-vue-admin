# Worktree 预览运行手册

## 启动与验收

Linux 上准备好开发工作流规定的工具链后，在任务 worktree 根目录执行：

```bash
make preview
make preview-status
make preview-url
make preview-check
```

首次启动会构建并嵌入当前前端，在实例目录生成私有配置、随机管理员凭据，初始化一次性 SQLite，重启后核验首页、健康检查、匿名拒绝与实际管理员登录。默认只监听 `127.0.0.1` 随机空闲端口。地址有效期为实例运行期间；stop/destroy 后不能继续访问。远程入口需显式配置，回环地址不代表远程可访问入口。

已有运行实例的 `preview` 会复用它。编辑完成后停止修改，再执行：

```bash
make preview-refresh
make preview-check
```

refresh 先构建候选版本，再停止旧进程并启动新版本，保留原端口、凭据、SQLite 与上传文件。SQLite 和配置在切换前备份；候选版本失败会停止候选、恢复数据/配置并尝试重新启动旧版本，命令仍返回失败。恢复也失败时保留注册、运行目录与日志，按错误继续排查，不把旧版本或失败版本称为验收通过。

`preview-status` 返回 build ID、commit、branch、未提交源码指纹、二进制 SHA-256、凭据文件位置及本地探测结果。源码指纹覆盖 Git 跟踪与未跟踪文件的内容和执行位，以及影响构建的 Vite/Go 环境设置。`preview-check` 会拒绝源码已变化的实例；status 仅报告变化，不隐式重建。

自动检查不代替浏览器和人工产品验收。自行从 status 返回的 `credentialsFile` 读取用户名和随机密码，不将密码或登录 token 放入仓库、URL 或公共日志。

## 目录与隔离边界

默认状态目录为 `~/.local/state/gva-preview/<worktree 路径摘要>/`，可通过 `GVA_PREVIEW_STATE` 指向源码 checkout 之外的独立登记目录。各 worktree 的实例互相独立。

| 内容 | 位置与行为 |
| --- | --- |
| 配置、随机凭据与注册 | 实例根目录；凭据和配置为 0600，实例目录为 0700 |
| SQLite | `data/preview.db`，不连接现有开发或生产数据库 |
| 上传文件 | `uploads/file/`；运行目录中的 uploads 链接指向此处 |
| 应用运行目录 | `builds/<build ID>/server/`，含二进制与 resource 模板 |
| 日志 | 私有 `server.log` 和 `log/` |
| 构建结果 | 仓库 `build/server` 仅用于构建，运行实例使用独立副本 |

预览环境变量只由管理器设置。Go 启动和配置重载将监听地址、端口、数据库与代码生成位置约束在实例资源，避免系统设置回写后指向源 checkout 或外部依赖。代码生成根目录是构建运行目录的父目录，模板操作不改任务源码。`system.listen-host` 的默认空值保留普通启动行为。

这是应用进程和数据的隔离，不是执行不可信代码的 OS 沙箱。SQLite 预览不代表 MySQL/PostgreSQL 等方言兼容性已验证。当前不共享 Nightingale 的 PostgreSQL、Prometheus、Redis、域名与状态目录；也不启动稳定生产实例。

## 停止、销毁和归档

```bash
make preview-stop       # 停止进程，保留数据、凭据与端口登记
make preview-destroy    # 停止并删除当前 worktree 的一次性实例数据
```

停止和销毁均可重复执行。发送信号前核对 PID 的启动标识及可执行文件路径，身份不匹配时拒绝误杀和删除。其他 worktree 的实例不受影响。实例暂停后用 `make preview` 重建当前代码并保留数据启动。

销毁前保存需要保留的数据与证据。Paseo teardown 使用同一 destroy 入口，在归档前清理；失败时保留工作区并排查。默认实例和显式指定其他 `GVA_PREVIEW_STATE` 的实例分别管理，归档前需自行清理额外登记目录。

## 验证设施

```bash
python3 -B -m unittest discover -s scripts -p 'test_*.py'
python3 -B scripts/preview-smoke.py
```

普通/完整 verify 运行设施单测及 Go 版本标识、配置约束测试。真实 smoke 是显式入口：创建两个一次性登记目录，验证独立端口、凭据、SQLite、上传、刷新保留数据、停止互不影响、重启与幂等销毁，最后清理所有临时实例。运行期间停止编辑源码，避免将不同版本的结果混在一次验证中。

## 局域网和公网入口

本机回环后端保持不变。显式配置网络入口后，网关只绑定指定 RFC1918 地址和同端口的回环地址，将请求转发到当前登记且 PID/可执行文件身份匹配的预览：

```bash
python3 -B scripts/preview_network.py configure --host 192.168.0.152 --port 30410
make preview-status
make preview-check
```

IP/端口按实际主机选择，配置前检查两处绑定可用性。当前主机旧 GVA 的 30400 和另一服务的 30401 已被占用，本 worktree 使用独立 30410，不接管旧实例。

网络配置位于私有实例 `network.json`。局域网网关与 cloudflared 使用独立用户级 systemd 服务；preview up 自动启动，refresh 更新网关和隧道，stop/destroy 在停应用前停止两项网络服务。隧道日志位于实例 `network/tunnel.log`，status 返回当前 `lanUrl`、`publicUrl`、`publicMode`、服务状态及实际探测结果。

探测使用明确的应用标识 `GVA-Preview-Probe/1.0`，核对两入口的 build ID 和首页 SHA-256。边缘服务注入统计脚本导致首页字节改变时，先核验本机原始首页的登记哈希，再核对公网首页引用的全部本地入口 JS/CSS 路径及文件 SHA-256；入口资源缺失或内容不同都会失败。`networkIntegrity` 返回实际下载首页的大小、SHA-256 和校验资源数。此过程不调整 Cloudflare 安全规则。

临时公网使用 Cloudflare Quick Tunnel，地址会在隧道停止后失效，刷新/重启可能更换地址，以 status 为准。Quick Tunnel 不支持 SSE；需要流式功能时使用局域网入口或在补齐 DNS 权限后切换到正式命名隧道。[Cloudflare 官方限制](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)

固定域名需先用有相应权限的账号执行 `cloudflared tunnel login`，创建独立 Tunnel 并执行 `cloudflared tunnel route dns <tunnel-id> <hostname>`。已有证书能创建 Tunnel 但 DNS 返回 403 时，应核对账户/Zone 和证书是否过期或选错域名；也可使用仅限定该域名的 DNS Edit API Token，自动查询 Zone 时另加 Zone Read。Tunnel 运行 JSON/token 与 DNS 管理权限不同，不能互相替代。[权限说明](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/tunnel-permissions/)

DNS 路由完成后配置命名隧道，三个命名参数必须一起提供，凭据内 Tunnel ID 必须匹配：

```bash
python3 -B scripts/preview_network.py configure \
  --host 192.168.0.152 --port 30410 \
  --hostname gva-dev1.zhiteng.win \
  --tunnel-id 8c8fa18a-f6b6-47b9-ad99-8a0a7fd3b501 \
  --credentials "$HOME/.cloudflared/8c8fa18a-f6b6-47b9-ad99-8a0a7fd3b501.json"
```

管理器将运行凭据复制到私有实例目录，文件权限为 0600，按精确 hostname 转发，其余 hostname 返回 404。命名域名在刷新/重启时保持不变；后续仅配置 LAN 参数会保留命名配置。stop/destroy 停止本地隧道，但不会删除 Cloudflare DNS 和 Tunnel；destroy 删除实例内的凭据副本，原始 `~/.cloudflared/` 凭据继续保留。域名无预设到期时间，可访问性取决于实例、网关和隧道持续运行。

2026-11-27 用户重新授权后，证书绑定的 Zone 已更新，独立 `gva-dev1.zhiteng.win` DNS 路由创建成功，本 worktree 已切换到命名隧道。此前未使用的测试 Tunnel 已删除；没有更改旧 GVA/Nightingale 的服务、域名或凭据。
