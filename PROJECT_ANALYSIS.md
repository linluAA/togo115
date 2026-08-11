# ToGo115 项目分析报告

> 分析时间：2026-08-06 ｜ 工作区：`d:/成品/togo115`

## 1. 项目概述

**ToGo115** 是一个 **115 网盘资源订阅与追新系统**。它帮助用户从 Telegram 频道/群组、RSS/Torznab、站点插件、海搜（Haisou）API 等来源自动发现影视资源，匹配后转存到 115 网盘（离线下载），并可与 Emby 联动同步入库状态。

- 类型：个人/家庭媒体自动化工具（self-hosted）
- 形态：带 Web 管理后台的 FastAPI 后端 + 单页原生前端
- 默认账号：`admin / admin123`（README 提示登录后修改）

## 2. 技术栈

| 层面 | 选型 |
|------|------|
| 语言 | Python 3.12 |
| Web 框架 | FastAPI 0.115 + Uvicorn 0.34 |
| 配置 | pydantic-settings（环境变量前缀 `TOGO115_`） |
| 数据库 | SQLite（单文件，WAL 模式） |
| 会话 | itsdangerous 签名 Cookie |
| HTTP 客户端 | httpx 0.28（支持 PySocks 代理） |
| Telegram | telethon 1.38 + cryptg |
| 二维码 | qrcode[pil]（扫码登录） |
| 前端 | 原生 HTML/JS/CSS（单页 `index.html` + `app.js` + `styles.css`） |
| 部署 | Docker / Docker Compose（GHCR 镜像） |

## 3. 代码规模

| 指标 | 数值 |
|------|------|
| 非测试 Python 文件 | 236 个 |
| 非测试 Python 代码行 | ≈ 21,402 行 |
| 测试文件 | 50 个 |
| 前端 JS/CSS 文件 | 28 个（17 JS + 11 CSS） |
| 单文件最大行数 | 374 行（`text_cjk/tables.py`） |
| 平均单文件行数 | ≈ 91 行 |

整体呈现**高内聚、小文件、多模块**风格，单文件普遍较小，模块化拆分细致，可维护性较好。

## 4. 目录结构与架构

```
app/
  main.py              # FastAPI 入口、路由挂载、startup/shutdown、/api/health、/api/qr
  config.py            # pydantic-settings 配置
  auth.py              # 会话鉴权依赖 current_user
  db*.py / schemas.py  # SQLite 数据访问层 + Pydantic 模型
  routers/             # HTTP 接口层：auth / integrations / media / settings / subscriptions / system
  services/            # 业务逻辑层
      adapters/        # 外部系统集成适配
          telegram/    # TG 客户端/历史搜索/扫描/Bot/会话/限流 (53 文件)
          pan115*.py   # 115 扫码/分享/离线下载/状态/状态机
          media_*.py   # TMDB / Emby 适配
      sources/         # 订阅源：rss_torznab.py + rss/ + haisou/
      subscription/    # 订阅领域核心（见下）
      link/            # 链接抽取/解析（TG 消息、HTML、下载）
      magnet/          # 磁力搜索/缓存/排序/回复
      monitor.py       # 后台监控循环
      job_worker.py / jobs.py   # 后台任务队列/Worker
      *.py             # 资源匹配、设置存储、指标、健康度等
  static/              # 前端单页应用
```

### 订阅领域模块（`services/subscription/`，按 README）
- `crud/` 增删改查 · `episode/` 剧集解析 · `match/` 标题/年份/清晰度匹配
- `resource/` 资源行去重与守卫 · `library/` Emby 同步入库
- `delivery/` 投递 + 115 复核 · `search/` TG/RSS 搜索编排与任务
- `attach/` 实时消息附加到订阅 · `api.py` 稳定公共 API

## 5. 核心业务流程（订阅追新）

```
创建订阅 / 手动搜索 / TG 实时消息
        │
        ▼
搜索编排 (subscription/search)
   ├─ Telegram 历史消息搜索（含按钮点击提取 115 链接）
   ├─ RSS / Torznab / 站点插件
   └─ 海搜(Haisou) API  ── 作为 Telegram 未命中的 fallback
        │
        ▼
资源匹配 (subscription/match)
   标题 / 年份 / 清晰度 匹配 → 去重
        │
        ▼
投递 (subscription/delivery)
   分享链接 → 115 转存 → 离线下载 → 入库
        │
        ▼
后台监控 (monitor.py, 心跳 60s)
   定时全量重搜(默认30min) / Emby 同步 / 失败资源重试 / DB 维护
        │
        ▼
Emby 同步入库状态 + 日志
```

监控循环（`services/monitor.py:47`）周期性执行：
- 每 120s 复核待处理 115 资源
- 每 300s 重试失败资源（12 个）
- 每 480s 预热 TG 消息索引
- 每 600s 触发 Emby 订阅同步
- 每 86400s 执行数据库维护（WAL checkpoint，>50MB 才 VACUUM）
- 按 `subscription_rescan_interval_seconds` 触发全量订阅重搜

## 6. 功能模块清单

1. **账号与鉴权**：登录页、会话 Cookie、账号安全设置
2. **115 网盘**：Cookie 粘贴 + 扫码登录；分享链接转存/离线下载
3. **Telegram**：历史搜索 + 实时监听；手机号/扫码登录；两步验证；Bot 交互
4. **TMDB**：热门剧集/电影榜单，一键订阅
5. **Emby**：看板、入库状态同步
6. **订阅管理**：电视剧/电影分类、关键词编辑、手动触发、候选决策
7. **订阅源**：RSS / Torznab / 站点插件 / 海搜 API（fallback）
8. **设置中心**：账号安全、115、TG、TMDB、代理、海搜、订阅源、TG Bot、Emby
9. **日志与监控**：简易/Debug 日志切换、后台监控循环、健康检查 `/api/health`

## 7. 代码质量与测试

- **测试覆盖广**：50 个测试文件，覆盖 DB 并发、Emby 容错、海搜源、Telegram 各种场景（Bot/历史/管道/链接过滤/性能）、订阅匹配/解析/候选决策/首搜链路/重查、资源去重重试、RSS/Torznab、投递、编码守卫、静态资源等。
- **模块化清晰**：分包彻底（telegram 拆 53 文件、subscription 拆 70 文件），单文件职责小。
- **关注性能**：多处含 `perf`/`fast`/`cache`，含消息索引预热、最近消息缓存、海搜缓存等优化。
- **容错设计**：监控循环捕获异常自动重试；DB 维护按库大小差异化处理；海搜按官方建议超时 ≥65s 且不对失败盲目重试。

## 8. 部署

- 推荐 GHCR 镜像 `ghcr.io/linluaa/togo115-app:main`，无需本地构建
- Docker Compose / `docker run`，端口 `8000`，数据挂载 `./data`（SQLite、Cookie、会话持久化）
- 环境变量：`TOGO115_SECRET_KEY`、`TOGO115_MONITOR_INTERVAL_SECONDS`、`TOGO115_SUBSCRIPTION_RESCAN_INTERVAL_SECONDS`、`TOGO115_DATA_DIR`、`TOGO115_DATABASE_PATH`
- Dockerfile 采用 builder/runtime 多阶段 + venv 瘦身，含 `HEALTHCHECK`

## 9. 观察与改进建议

1. **`@app.on_event` 已弃用**：FastAPI 0.115 中该装饰器已弃用，建议迁移到 `lifespan` 上下文管理器。
2. **默认弱口令**：`admin/admin123` 用于快速上手，部署若不改密存在风险（可读考虑首次启动强制改密）。
3. **SQLite 单文件**：适合个人/轻度使用；多实例并发会成为瓶颈（单容器可接受）。
4. **115 接口非官方**：`Pan115Adapter` 封装非公开接口，网盘策略变化时需维护。
5. **依赖少而可控**：仅 9 个直接依赖，供应链面小，利于审计与部署。

**可选优化**：
- 引入异步 DB 驱动（`aiosqlite`）提升高并发吞吐（当前同步 SQLite + 连接池）。
- 迁移至 `lifespan` 生命周期 API。
- 增加首次启动引导与随机 `SECRET_KEY` 生成、强改密。
- 为超大订阅量场景提供 Postgres 适配器（保持 SQLite 默认）。

## 10. 总结

ToGo115 是一个**架构清晰、模块划分细致、测试覆盖良好**的 115 网盘媒体自动化订阅系统。核心亮点在于多来源资源发现（Telegram 为主 + RSS/海搜 fallback）与 115 转存/Emby 入库的闭环，以及健壮的后台监控与任务重试机制。代码风格偏向小而专的文件，可维护性高；主要技术债集中在 FastAPI 生命周期 API 版本迁移与单文件 SQLite 扩展性。
