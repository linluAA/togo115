# ToGo115

115 网盘资源订阅与追新系统。当前版本提供可运行的管理后台、订阅管理、配置持久化、日志查看、后台监控循环，以及 Telegram 历史搜索/实时监听、115 扫码登录和分享链接转存入口。

## 默认账号

- 账号：`admin`
- 密码：`admin123`

登录后请到“设置 / 账号安全”修改。

## Docker 部署

推荐直接拉取远程镜像部署，无需本地构建。

镜像地址：

```text
ghcr.io/linluaa/togo115-app:main
```

两种方式任选其一：

1. **Docker Compose**（推荐，配置可复用）
2. **docker run**（无需 compose 文件）

访问地址均为：

```text
http://localhost:8000
```

- 默认账号：`admin` / `admin123`（登录后请到「设置 / 账号安全」修改）
- 数据建议挂载到宿主机目录，例如 `./data`

### 方式一：Docker Compose

#### 1. 准备文件

```bash
mkdir -p togo115/data && cd togo115
```

写入 `docker-compose.yml`：

```yaml
services:
  togo115:
    image: ghcr.io/linluaa/togo115-app:main
    container_name: togo115
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      TOGO115_SECRET_KEY: "please-change-this-secret"
      TOGO115_MONITOR_INTERVAL_SECONDS: "60"
      # 全部活跃订阅定时重搜间隔（秒）。0 关闭。默认 1800=30 分钟。
      TOGO115_SUBSCRIPTION_RESCAN_INTERVAL_SECONDS: "1800"
    volumes:
      - ./data:/data
```

也可直接使用仓库根目录的 `docker-compose.yml`（内容相同）。

部署前请把 `TOGO115_SECRET_KEY` 改成随机长字符串；端口可按需改成 `宿主机端口:8000`。

#### 2. 拉取并启动

```bash
docker compose pull
docker compose up -d
```

#### 3. 更新 / 运维

```bash
# 更新到最新 main 镜像
docker compose pull
docker compose up -d

# 查看日志
docker compose logs -f togo115

# 停止容器（保留 ./data）
docker compose down
```

### 方式二：docker run（不使用 Compose）

适合没有安装 Compose、或只想一条命令启动的场景。

#### 1. 准备数据目录

```bash
mkdir -p /opt/togo115/data
```

路径可按自己习惯修改，后面的挂载参数保持一致即可。

#### 2. 拉取镜像

```bash
docker pull ghcr.io/linluaa/togo115-app:main
```

#### 3. 启动容器

```bash
docker run -d \
  --name togo115 \
  --restart unless-stopped \
  -p 8000:8000 \
  -e TOGO115_SECRET_KEY="please-change-this-secret" \
  -e TOGO115_MONITOR_INTERVAL_SECONDS=60 \
  -e TOGO115_SUBSCRIPTION_RESCAN_INTERVAL_SECONDS=1800 \
  -v /opt/togo115/data:/data \
  ghcr.io/linluaa/togo115-app:main
```

说明：

- 请把 `TOGO115_SECRET_KEY` 改成随机长字符串
- `-p 8000:8000` 可改成 `宿主机端口:8000`
- `-v /opt/togo115/data:/data` 用于持久化数据库、Cookie、会话等数据

#### 4. 更新 / 运维

```bash
# 查看日志
docker logs -f togo115

# 更新到最新镜像
docker pull ghcr.io/linluaa/togo115-app:main
docker stop togo115
docker rm togo115
# 然后重新执行上面的 docker run 命令（数据目录不变即可保留配置）

# 停止 / 删除容器（保留数据目录）
docker stop togo115
docker rm togo115
```

### 环境变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `TOGO115_SECRET_KEY` | 应用密钥，生产环境务必修改 | 示例占位值 |
| `TOGO115_MONITOR_INTERVAL_SECONDS` | 监控心跳间隔（秒） | `60` |
| `TOGO115_SUBSCRIPTION_RESCAN_INTERVAL_SECONDS` | 全部活跃订阅定时重搜间隔（秒）；`0` 关闭 | `1800` |
| `TOGO115_DATA_DIR` | 容器内数据目录 | `/data` |
| `TOGO115_DATABASE_PATH` | SQLite 路径 | `/data/togo115.sqlite3` |

### 镜像说明

- 镜像：`ghcr.io/linluaa/togo115-app`
- `main` 分支推送后由 GitHub Actions 自动构建并发布
- 常用标签：`main`，以及版本 tag（如 `v1.0.0`）

若 GHCR 拉取需要登录：

```bash
echo <GITHUB_TOKEN> | docker login ghcr.io -u <GITHUB_USERNAME> --password-stdin
```

## 已实现模块

- 登录页：账号、密码、登录。
- 侧边栏：首页 TMDB 榜单、Emby 看板、我的订阅、日志、设置。
- TMDB：配置 API Key 后读取热门剧集和电影，支持一键订阅。
- 我的订阅：区分电视剧和电影，支持添加、取消、编辑关键词、手动触发搜索。
- 日志：支持简易日志和 Debug 日志切换。
- 设置：账号安全、115 Cookie/扫码、Telegram API/手机号验证码/扫码、TMDB、代理、订阅源、TG Bot、Emby。
- 后台监控：定时检查 Telegram/TG Bot 监听状态、同步 Emby 入库状态，并按间隔触发全部活跃订阅重搜（Telegram 历史 + 订阅源/磁力兜底）；创建订阅、手动搜索、TG 实时消息仍会即时触发。
- TG Bot：支持 `订阅 剧名` 搜索候选、选择剧集海报后确认订阅，支持 `订阅列表` 和 `取消订阅 名称/ID`。

## Telegram 配置

- `API ID` / `API HASH`：从 Telegram 官方开发者后台获取。
- `群组/频道`：填写 username、邀请加入后的频道名，或 Telethon 可识别的 chat id，多个用英文逗号分隔。
- `历史搜索条数`：每个关键词在每个来源内读取的历史消息数量。
- 保存配置后可用手机号接收 Telegram 验证码登录，也可点击“TG 扫码”生成二维码登录；如果账号开启两步验证，系统会在需要时显示密码输入框。

系统会在创建订阅、手动搜索、以及监控定时重搜时搜索 Telegram 历史消息；实时追新依赖 Telegram 新消息监听。如果消息带按钮，会尝试点击包含 `115`、`链接`、`查看`、`打开`、`资源`、`link` 的按钮并从响应里提取 115 分享链接。

## 订阅源配置

设置里的“订阅源”支持三种类型：

- `RSS`：填写 RSS URL，系统在定时重搜/手动搜索时读取条目并提取 115、magnet、torrent 链接。
- `Torznab`：填写 Torznab API URL，可使用 `{query}` 占位符，或让系统自动补 `t=search&q=剧名`。
- `站点插件`：选择内置插件后填写站点首页或搜索 URL 模板，例如 `https://yhdm33.com/s/{query}.html`。系统会先打开搜索页，再进入同站内疑似详情页，提取 `magnet` / `.torrent` 链接。

每个订阅源可以填写“测试关键词”，点击测试时会用该关键词替换 `{query}`；未填写时会回退使用源名称。
从 TMDB 添加订阅时会保存首播/上映年份；站点插件搜索页如果能识别结果年份，会优先只进入同年份详情页，并在资源匹配时拒绝明确标注为其它年份的结果。

站点插件依赖目标网站页面结构，站点改版时可能需要调整适配规则。旧的 `magnet_web` 配置会自动兼容为“站点插件”。磁力或 torrent 链接无法直接转存到 115，建议把全局推送方式设置为“发送到 TG Bot”。

## 115 配置

- 可直接粘贴 Cookie，也可以点击“115 扫码”后用 115 App 扫码。
- Cookie 会保存到 SQLite 中，Docker 数据卷重启后仍可使用。
- 自动转存走 115 分享链接转存接口，目标目录优先使用订阅的 `target_path`，否则使用设置里的默认转存目录。

## 仍需按账号实测的部分

115 网盘接口是非官方接口，扫码登录和转存参数可能随 115 调整。代码位置在 `app/services/integrations.py` 的 `Pan115Adapter`，如果接口响应字段变化，通常只需要调整这里。
