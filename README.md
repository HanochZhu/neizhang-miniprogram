# 内账（neizhang）

微信小程序客户端 + FastAPI 后端的项目结构如下：

| 目录 | 说明 |
| --- | --- |
| `neizhang-client/` | 微信小程序（使用微信开发者工具打开） |
| `neizhang-server/` | 后端 API（FastAPI + SQLite，默认端口 `8000`） |

---

## 环境要求

- **服务端**：Python 3.10 或以上、`pip`
- **客户端**：安装 [微信开发者工具](https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html)

---

## 服务端（neizhang-server）

### 1. 安装依赖

```bash
cd neizhang-server
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置环境变量

在 `neizhang-server` 下创建或编辑 `.env`（文件名固定为 `.env`，与 `app/config.py` 中 `pydantic-settings` 约定一致）。常用项包括：

| 变量名 | 说明 |
| --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek（Anthropic 兼容端点）API Key，供对话等功能使用 |
| `DEEPSEEK_BASE_URL` | 可选，默认 `https://api.deepseek.com/anthropic` |
| `DEEPSEEK_MODEL` | 可选，默认 `deepseek-v4-pro` |
| `WECHAT_APP_ID` | 微信小程序 AppID（需与客户端 `project.config.json` 中 `appid` 一致） |
| `WECHAT_APP_SECRET` | 微信小程序 AppSecret（登录 `code` 换 `openid` 等） |
| `JWT_SECRET` | 可选；不填时程序会每次随机生成，**重启后已有 token 会失效**，团队开发建议固定一条密钥 |
| `DATABASE_URL` | 可选，默认本目录下 SQLite：`sqlite+aiosqlite:///./neizhang.db` |
| `UPLOAD_DIR` | 可选，文件上传目录，默认 `uploads` |

勿将含密钥的 `.env` 提交到版本库。

### 3. 启动

```bash
cd neizhang-server
source .venv/bin/activate   # 若已激活可省略
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- 启动后会自动建库、建表，并在 **`http://127.0.0.1:8000`** 提供服务。
- 健康检查：**`curl http://127.0.0.1:8000/health`**，返回 `{"status":"ok"}` 即正常。

### 4. 自动化测试（pytest）

在 **`neizhang-server`** 目录下安装开发依赖并运行用例（使用独立临时 SQLite 与测试用 JWT 密钥，不读写你本地的 `neizhang.db`）：

```bash
cd neizhang-server
pip install -r requirements-dev.txt
pytest
```

建议按 **TDD**：先为要改的行为在 `neizhang-server/tests/` 增加或调整用例，再实现功能，最后保持 `pytest` 全绿。

---

## 客户端（neizhang-client）

### 1. 用微信开发者工具打开项目

1. 打开微信开发者工具 → **导入项目**。
2. 目录选择仓库中的 **`neizhang-client`**（内含 `project.config.json`）。
3. AppID 使用你方小程序（可与 `project.config.json` 中 `appid` 一致；仅本地体验可选用测试号，但登录等能力可能受限）。

### 2. 指向后端地址

小程序请求基址在 `neizhang-client/miniprogram/app.js` 的 `globalData.serverUrl`，默认：

```text
http://127.0.0.1:8000
```

- **模拟器**：与后端同机时默认已用 `127.0.0.1`（在微信开发者工具里通常比 `localhost` 更少出现连接/超时问题）。
- **真机预览**：手机无法访问你电脑上的 `localhost`，需把 `serverUrl` 改为你电脑的 **局域网 IP**（例如 `http://192.168.1.10:8000`），并保证手机与电脑在同一 Wi-Fi，且防火墙放行 `8000` 端口。

### 3. 本地调试网络（必读）

连本地后端 `http://127.0.0.1:8000` 时，**不能依赖**公众平台里配置的 request 合法域名（那里只能是已备案的 **HTTPS** 域名，`localhost` 也加不进去）。开发阶段请任选其一（可同时做）：

1. **微信开发者工具**：**详情 → 本地设置**，勾选 **不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书**。改完后若仍报错，可尝试 **清除缓存 → 全部清除** 再编译。
2. **项目配置**：本仓库已将 `neizhang-client/project.config.json` 中 `setting.urlCheck` 设为 `false`，减轻模拟器里对域名的拦截（发版前请按微信要求恢复并配置正式域名）。

若未关闭校验，控制台会出现 `request 合法域名校验出错`、本地地址不在合法域名列表等提示，请求被拦后界面常表现为 **`Error: timeout`**，与手机号登录本身无关。

**正式上线**：将 API 部署到 **HTTPS** 域名，在 [公众平台](https://mp.weixin.qq.com/) **开发管理 → 开发设置 → 服务器域名** 中把该域名加入 request 合法域名，并把小程序里的 `serverUrl` 改为该 HTTPS 地址。

### 4. 后端管理界面

```
http://127.0.0.1:8000/admin
```

---

## 常见问题

### 登录时报 `Error: timeout` 或合法域名错误

多半是当前环境仍在校验域名，按上文 **「本地调试网络」** 勾选不校验或确认 `urlCheck` 已为 `false`，并确保本机 **uvicorn 已在 8000 端口运行**（可先 `curl http://127.0.0.1:8000/health`）。

### 真机预览仍连不上

真机不能使用 `localhost`，请把 `app.js` 里 `serverUrl` 改成电脑的 **局域网 IP**（如 `http://192.168.x.x:8000`），手机与电脑同 Wi-Fi，且电脑防火墙放行端口；真机上是否仍受域名校验取决于客户端与基础库，线上环境必须以 HTTPS 合法域名为准。

---

## 建议启动顺序

1. 先启动 **服务端**（`uvicorn`），确认 `/health` 正常。
2. 再打开 **微信开发者工具** 编译/预览小程序。

如在真机调试，同步修改 `serverUrl` 并保证手机能访问该地址。
