# SecurityCuff Console · 安全箍观察控制台

用于查看安全监测数据、跟踪模拟干预和复盘事件的 Web 控制台。开箱即可运行内置模拟器，使用 React、FastAPI、WebSocket 和 SQLite。

[打开在线演示](https://safetyring.cpolar.cn/) · [查看数据契约](contracts/schema-v1.json)

- **实时观察**：查看模拟画面、任务进度、算法状态和风险指标。
- **事件回放**：从安全事件跳转到触发帧，回看会话、日志和执行回执。
- **模拟操作**：提交模拟干预或注入故障，检查界面和执行器的响应。

## 快速开始

需要 Git、Python 3.10+ 和 Node.js 22.12+。

```sh
git clone https://github.com/Siruiu/SecurityCuff-Console.git
cd SecurityCuff-Console
npm ci --prefix frontend
npm run build --prefix frontend
```

**Linux / macOS**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-runtime.lock
cp config/example.json config/local.json
SAFECUFF_CONFIG=config/local.json .venv/bin/python -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 18081
```

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-runtime.lock
Copy-Item config/example.json config/local.json
$env:SAFECUFF_CONFIG = 'config/local.json'
.\.venv\Scripts\python.exe -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 18081
```

打开 <http://127.0.0.1:18081/> 观看模拟数据。健康检查位于 `/healthz`，会话保存在 `data/sessions.sqlite3`。

## 访问设置

示例配置允许免登录浏览、暂停和注入故障。共享演示中的访客操作作用于同一个模拟实例。接入真实设备前，将 `anonymous_operator` 和 `public_viewer` 都设为 `false`，配置独立密码和签名密钥，再重启后端。

| 配置 | 用途 |
| --- | --- |
| `anonymous_operator` | 设为 `true` 允许免登录执行模拟操作。 |
| `public_viewer` | 在关闭免登录操作后，设为 `true` 允许免登录只读访问。 |
| `operator_password`、`cookie_secret` | 在关闭免登录操作后，为操作员配置独立强密码和随机签名密钥。 |
| `viewer_password` | 关闭免登录时，为只读观察员设置独立密码。 |
| `allowed_origins` | 填入浏览器使用的完整来源，如 `https://example.cpolar.cn`，末尾无需斜杠。 |
| `secure_cookie` | 本机 HTTP 使用 `false`，HTTPS 部署使用 `true`。 |

## 用 cpolar 分享模拟实例

### 共用固定域名

首次按「快速开始」构建前端并在虚拟环境中安装依赖，然后安装 [cpolar](https://www.cpolar.com/docs)。各成员在自己的机器上将同一份私有 cpolar 配置保存在仓库外。首次配置可参考 [cpolar 配置示例](config/cpolar.example.yml)。Linux / macOS 可用 `chmod 600` 限制配置文件权限。

从已激活的项目虚拟环境运行下面的命令，将配置路径和 HTTPS 地址换成团队正在使用的值。脚本启动本机模拟器，通过健康检查后再启动 cpolar，并自动配置公开地址供页面和 WebSocket 使用。

```sh
python scripts/start-demo.py --cpolar-config /path/to/cpolar.yml --public-origin https://example.cpolar.cn
```

默认使用本机端口 `18080`，与示例 cpolar 配置一致。若配置用了其他端口，传入 `--port`。若文件内有多个隧道，传入 `--tunnel` 指明本项目的隧道名称。cpolar 不在 PATH 时传入 `--cpolar-bin`。

同一个固定域名由一台机器对外提供演示。换人托管时，原托管者先停止隧道，下一位再启动。使用上面的脚本时，按 `Ctrl+C` 会同时停止它启动的模拟器和隧道。若需要两台机器同时对外演示，为它们分配不同的隧道地址，并确认账号支持所需的在线客户端数。

### 临时地址

1. 在运行控制台的机器上安装 [cpolar](https://www.cpolar.com/docs)，用自己的账号完成客户端认证。先确认 `http://127.0.0.1:18081/healthz` 可访问。
2. 启动 HTTP 隧道。

   ```sh
   cpolar http -region=cn 18081
   ```

3. 将 cpolar 分配的 **HTTPS 地址**加入 `config/local.json` 的 `allowed_origins`，重启控制台后端，再访问公网首页和 `/healthz`。

## 开发与测试

| 目录 | 内容 |
| --- | --- |
| [frontend/](frontend/) | React / TypeScript 控制台 |
| [backend/](backend/) | FastAPI、模拟器、算法插件与会话存储 |
| [contracts/](contracts/) | 观测、评估、干预、事件及会话的 JSON Schema |
| [tests/](tests/) | 后端接口和模拟流程测试 |

后端运行时，使用 `npm run dev --prefix frontend` 开启前端热更新。Vite 将接口与 WebSocket 代理到 `127.0.0.1:18081`。

在项目虚拟环境中运行测试：

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
npm run build --prefix frontend
```

浏览器测试使用 Playwright。安装 Chromium 后，执行 `npm run test:e2e --prefix frontend`。可用 `DEMO_URL` 指定测试实例，默认为本地控制台。测试实例启用密码时，通过环境变量 `DEMO_PASSWORD` 提供密码。测试会向模拟器发送干预和故障请求。
