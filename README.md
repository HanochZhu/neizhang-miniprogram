# 内账小程序客户端（neizhang-client）

微信小程序前端，提供对话记账、图片识别记账与财务汇总等能力。

后端 API 为独立仓库，请先按服务端文档完成部署后再调试本客户端：

**服务端仓库：[HanochZhu/neizhang-server](https://github.com/HanochZhu/neizhang-server)**

---

## 环境要求

- 安装 [微信开发者工具](https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html)
- 本地或远程已运行的 **neizhang-server**（默认 `http://127.0.0.1:8000`）

---

## 快速开始

### 1. 启动后端

克隆并启动服务端（安装、`.env` 配置、启动命令等详见服务端 README）：

```bash
git clone https://github.com/HanochZhu/neizhang-server.git
cd neizhang-server
# 按 https://github.com/HanochZhu/neizhang-server 文档创建虚拟环境、安装依赖并启动 uvicorn
```

确认健康检查正常：`http://127.0.0.1:8000/health` 返回 `{"status":"ok"}`。

### 2. 用微信开发者工具打开项目

1. 打开微信开发者工具 → **导入项目**。
2. 目录选择本仓库中的 **`neizhang-client/`**（内含 `project.config.json` 与 `miniprogram/`）。
3. AppID 使用你方小程序（可与 `project.config.json` 中 `appid` 一致；仅本地体验可选用测试号，但登录等能力可能受限）。

### 3. 配置后端地址

小程序请求基址在 `miniprogram/app.js` 的 `globalData.serverUrl`，默认示例：

```text
http://127.0.0.1:8000
```

- **模拟器**：与后端同机时建议使用 `127.0.0.1`（在微信开发者工具里通常比 `localhost` 更少出现连接/超时问题）。
- **真机预览**：手机无法访问你电脑上的 `localhost`，需把 `serverUrl` 改为你电脑的 **局域网 IP**（例如 `http://192.168.1.10:8000`），并保证手机与电脑在同一 Wi-Fi，且防火墙放行 `8000` 端口。

### 4. 本地调试网络（必读）

连本地后端 `http://127.0.0.1:8000` 时，**不能依赖**公众平台里配置的 request 合法域名（那里只能是已备案的 **HTTPS** 域名，`localhost` 也加不进去）。开发阶段请任选其一（可同时做）：

1. **微信开发者工具**：**详情 → 本地设置**，勾选 **不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书**。改完后若仍报错，可尝试 **清除缓存 → 全部清除** 再编译。
2. **项目配置**：`project.config.json` 中 `setting.urlCheck` 已设为 `false`，减轻模拟器里对域名的拦截（发版前请按微信要求恢复并配置正式域名）。

若未关闭校验，控制台会出现 `request 合法域名校验出错`、本地地址不在合法域名列表等提示，请求被拦后界面常表现为 **`Error: timeout`**，与手机号登录本身无关。

**正式上线**：将 API 部署到 **HTTPS** 域名，在 [公众平台](https://mp.weixin.qq.com/) **开发管理 → 开发设置 → 服务器域名** 中把该域名加入 request 合法域名，并把小程序里的 `serverUrl` 改为该 HTTPS 地址。

---

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `miniprogram/` | 小程序页面、组件与服务 |
| `miniprogram/app.js` | 全局配置（含 `serverUrl`） |
| `miniprogram/services/` | API 与鉴权封装 |
| `WXMINIPROGRAM_API.md` | 客户端调用的 API 说明 |

---

## 后端管理界面

服务端启动后可在浏览器访问（详见 [neizhang-server](https://github.com/HanochZhu/neizhang-server)）：

```text
http://127.0.0.1:8000/admin
```

---

## 常见问题

### 登录时报 `Error: timeout` 或合法域名错误

多半是当前环境仍在校验域名，按上文 **「本地调试网络」** 勾选不校验或确认 `urlCheck` 已为 `false`，并确保后端 **已在 8000 端口运行**（可先访问 `http://127.0.0.1:8000/health`）。

### 真机预览仍连不上

真机不能使用 `localhost`，请把 `app.js` 里 `serverUrl` 改成电脑的 **局域网 IP**（如 `http://192.168.x.x:8000`），手机与电脑同 Wi-Fi，且电脑防火墙放行端口；真机上是否仍受域名校验取决于客户端与基础库，线上环境必须以 HTTPS 合法域名为准。

---

## 建议启动顺序

1. 按 [neizhang-server](https://github.com/HanochZhu/neizhang-server) 文档启动后端，确认 `/health` 正常。
2. 再打开 **微信开发者工具** 编译/预览小程序。

如在真机调试，同步修改 `serverUrl` 并保证手机能访问该地址。
