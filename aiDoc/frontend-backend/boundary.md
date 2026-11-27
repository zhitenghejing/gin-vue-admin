# 前后端边界说明

## 归属边界

- 后端负责路由、参数校验、业务逻辑和响应结构
- 前端负责页面流程、交互体验、本地状态和展示层
- 共同行为通过明确的 API 契约协作，不通过隐式约定耦合

## 契约规则

- 保持统一响应结构：`{ code, data, msg }`
- 保持统一分页结构：`{ page, pageSize, total, list }`
- 字段名不要随意漂移
- 前后端字段类型必须保持一致
- 后端必须提供完整而准确的 Swagger 接口说明
- 前端接口调用应以实际 Swagger 与后端实现为准

## 可选内嵌前端发行模式

- `make build-embed` 构建前端后，将 `web/dist` 复制到 `server/internal/webui/dist`，使用 `embedweb` 标签编译 Go；生成目录不提交。
- 普通 `go build` / `go run` 保持原有行为，无需前端产物，开发仍使用 Vite。
- 内嵌模式固定前端 `VITE_BASE_API=/api`、`VITE_FILE_API=/api`；Go HTTP 入口剥离 `/api` 后交给原有 Gin，保持上传、Swagger、鉴权和业务接口契约。
- 内嵌模式要求 `system.router-prefix` 为空；非空时启动失败并输出明确原因，防止双重前缀。
- 页面部署在根路径，沿用 Hash 路由。仅提供产物中的普通文件，禁止目录列表；未知地址不回退到 HTML，仍由 Gin 处理原生 API 或返回 404。
- HTML 与静态资源使用 `Cache-Control: no-cache`；当前版本未增加预压缩或旧版本 chunk 保留策略。
- 详情见 `aiDoc/relations/embedded-web.md`。

## 变更规则

- 涉及破坏性接口调整时，要先写清楚变更范围
- Swagger 或其他接口说明必须与真实实现一致
- 前端接口封装应继续放在 `web/src/api/` 或 `web/src/plugin/<name>/api/`
- 可复用逻辑优先复用 `web/src/utils/` 现有能力

## 完成前检查

跨前后端改动结束前，至少确认以下几点：

1. 后端响应结构仍然满足前端预期
2. 前端仍在使用正确的字段名和数据类型
3. 若契约发生了长期变化，对应说明已经补到 `aiDoc/`

## 预览运行配置

- `system.listen-host` 是可选绑定地址，默认空值保持原有监听行为。
- 由预览管理器设置 `GVA_PREVIEW_BUILD_ID`、绝对 `GVA_PREVIEW_DATA_DIR` 与 `GVA_PREVIEW_PORT` 后，启动与配置重载固定使用回环监听、实例 SQLite、相对上传路径和实例代码生成目录，并关闭外部数据库列表、Redis 与 Mongo。
- 预览响应增加 `X-GVA-Preview-Build`，用于版本探测；业务响应结构和鉴权保持不变。普通启动不设置预览环境变量时行为不变。
