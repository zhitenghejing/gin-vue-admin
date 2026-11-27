# Go 内嵌前端发行模式

## 构建与启动

在仓库根目录执行（需要 Node 24、pnpm 10 和满足 `server/go.mod` 的 Go）：

```bash
make build-embed
cd server
../build/server -c config.yaml
```

构建会安装前端依赖并强制使用同源 `/api` 地址，检查 `web/dist/index.html` 非空，清空并复制产物到 `server/internal/webui/dist`，再用 `-tags embedweb` 编译到 `build/server`。

`system.router-prefix` 必须为空；默认配置已满足。启动后访问 `http://localhost:8888/`（端口取决于配置）。开发模式继续使用 Vite 和普通 `go run .`，不需要 dist。

如需只重编译后端，可在已有且确认最新的嵌入产物基础上执行 `go build -tags embedweb`；正式发行优先使用 `make build-embed`，避免误打包旧页面。缺少 dist 时带标签编译会失败。

## URL 与缓存契约

| 浏览器路径 | 处理方式 |
| --- | --- |
| `/` | 内嵌 `index.html` |
| `/assets/<文件>`、`/favicon.ico`、`/logo.png` | 内嵌产物中的普通文件 |
| `/api/<路径>` | 剥离 `/api` 后交给现有 Gin，包括上传文件与 Swagger |
| `/health` 等原有原生路径 | 继续交给 Gin |
| 缺失文件、未知 API | 保持 Gin 的 404，不返回前端 HTML |

静态文件仅接受 GET/HEAD，不提供目录列表；缓存策略为 `no-cache`，未增加 gzip/Brotli。使用 Hash 路由，因此 `/#/login` 的刷新只请求 `/`。当前 Vite `base=/`，不支持直接迁移到任意 URL 子目录。

前端随二进制更新，运行时修改环境变量不会改变已经编译的 Vite 配置。升级后，旧页面可能请求上一版本懒加载文件，应刷新页面；当前不保留旧版本 chunk。

## Docker

```bash
make build-image-embed
# 或从仓库根目录执行：
docker build -f deploy/docker/Dockerfile.embed -t gva-server-embed:local .
```

镜像采用 Node 构建前端、Go 编译、Alpine 运行三个阶段。专属 `Dockerfile.embed.dockerignore` 排除本地生成物；根目录 `.dockerignore` 也排除依赖树，以兼容旧 Docker builder，并保留原有镜像依赖的 `build/` 目录。容器仍监听 8888，入口读取 `/app/config.docker.yaml`；按部署需要挂载配置与持久化上传目录等数据。

本模式只嵌入前端：配置、数据库、上传目录、日志仍为外部依赖。运行镜像仍携带 `resource/` 模板；代码生成等开发能力仍可能需要源码目录。TLS、压缩、CDN 可由外部网关提供。

## 验证

```bash
cd server
go test ./internal/webui
```

根目录执行 `make test-embed` 会重新生成真实前端产物并测试嵌入版本。测试覆盖 API 前缀、请求体与响应头、鉴权拒绝、文件访问路径、静态资源 MIME、HEAD、缓存、目录列表和 404；嵌入测试遍历所有嵌入文件，核对响应状态与字节内容。

CI 中独立的 embedded 任务先构建前端与 Go，再运行嵌入测试，不依赖其他任务的工作目录。
