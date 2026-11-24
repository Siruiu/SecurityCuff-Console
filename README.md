# SecurityCuff Console · 安全箍观察控制台

用于查看安全监测数据、跟踪模拟干预和复盘事件的 Web 控制台。开箱即可运行内置模拟器，使用 React、FastAPI、WebSocket 和 SQLite。

[打开在线演示](https://safetyring.cpolar.cn/) · [查看数据契约](contracts/schema-v1.json)

- **实时观察**：查看模拟画面、任务进度、算法状态和风险指标。
- **事件回放**：从安全事件跳转到触发帧，回看会话、日志和执行回执。
- **模拟操作**：操作员可提交模拟干预或注入故障，检查界面和执行器的响应。

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

示例配置开启 `public_viewer`，可直接查看实时数据和历史回放。对外共享时请使用模拟数据。修改配置后重启后端。

| 配置 | 用途 |
| --- | --- |
| `public_viewer` | 设为 `true` 启用免登录只读访问，设为 `false` 要求所有访客登录。 |
| `operator_password`、`cookie_secret` | 配置独立强密码和随机签名密钥，开启「操作员登录」。只有此角色可执行模拟操作。 |
| `viewer_password` | 关闭免登录时，为只读观察员设置独立密码。 |
| `allowed_origins` | 填入浏览器使用的完整来源，如 `https://example.cpolar.cn`，末尾无需斜杠。 |
| `secure_cookie` | 本机 HTTP 使用 `false`，HTTPS 部署使用 `true`。 |

## 用 cpolar 分享模拟实例

1. 在运行控制台的机器上安装 [cpolar](https://www.cpolar.com/docs)，用自己的账号完成客户端认证。先确认 `http://127.0.0.1:18081/healthz` 可访问。
2. 启动 HTTP 隧道。

   ```sh
   cpolar http -region=cn 18081
   ```

3. 将 cpolar 分配的 **HTTPS 地址**加入 `config/local.json` 的 `allowed_origins`，并设 `secure_cookie` 为 `true`。重启控制台后端，再访问公网首页和 `/healthz`。首页应显示实时连接和持续更新的模拟帧。

如果已经在自己的账号中预留了域名，将 [cpolar 配置示例](config/cpolar.example.yml) 复制到仓库外，填写账号令牌和预留时选择的区域及子域名。将以下示例路径替换为实际配置文件路径，即可按名称启动隧道。

```sh
cpolar start -config=/path/to/cpolar.yml safecuff
```

现有的 [recover-demo.py](scripts/recover-demo.py) 用于恢复已部署的固定演示实例。合作者可以用上面的命令独立启动自己的隧道。

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

浏览器测试使用 Playwright。安装 Chromium 后，从环境传入 `DEMO_PASSWORD`，执行 `npm run test:e2e --prefix frontend`。可用 `DEMO_URL` 指定测试实例，默认为本地控制台。测试会向模拟器发送干预和故障请求。
