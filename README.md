# 安全箍观察控制台 · v0.1.0

可运行的模拟原型：React/TypeScript、FastAPI、SQLite、REST 与同源 WebSocket。仅有模拟执行器，不连接真实机器人、相机、急停或断能。

## 公网审核

唯一演示入口：**https://safetyring.cpolar.cn/**。选择“操作员”，使用交付时单独提供的网页密码；观察员为只读。密码独立于 cpolar Authtoken。登录使用 HttpOnly / Secure / SameSite=Strict cookie，8 小时到期，后端检查角色与操作来源。

1. “实时观察”检查模拟帧、任务步骤、两条独立风险指标和算法健康。未校准指标不是概率，不相加。
2. “请求模拟暂停”后核对同一请求 ID 的“已请求 → 已接受 → 模拟执行已确认”。算法建议单独记事件，不自动执行。
3. 点击安全事件定位原始观测帧；或在“实验会话”打开回放、拖动/播放。HISTORY 历史视图禁用执行，回执按记录时刻截断。
4. “算法管理”可注入超时、断连、采集冻结 8 秒、下一次执行失败；回实时页检查异常和失败回执。测试后将插件改回正常。恢复模拟任务需评估未过期、算法健康且没有当前暂停建议。
5. “断开网页连接并验证重连”测试自动重连；关闭网页数秒再打开，设备仍继续采集和记录。“运行日志”可筛选并定位帧。

健康/版本：https://safetyring.cpolar.cn/healthz 。正常为 200、`status=ok`、`mode=simulation-only` 和完整提交 ID；采集陈旧/记录故障为 503。不公开日志、凭据或操作。

已部署，审核无需终端。必要维护：

```powershell
ssh ai-edge 'systemctl --user stop safecuff-console.service'
ssh ai-edge 'systemctl --user start safecuff-console.service'
# 设备重启或隧道退出后，复用同一固定隧道配置恢复
ssh ai-edge 'python3 /home/admin/safecuff-console-dev/scripts/recover-demo.py'
```

控制台由用户级 systemd 管理，启用用户服务启动、故障重启，与网页/SSH 无关。既有 cpolar 独立运行，恢复脚本发现它仍运行时绝不创建并行隧道，不改私有配置。

## 数据契约

定义：`backend/contracts.py`、`contracts/schema-v1.json`，版本 1。关联键为会话 UUID + 帧序号；每次重启新建会话/流世代。UTC 秒存储，页面本地时间显示；设备新鲜度和插件截止使用单调时钟。

- Observation：设备/源/会话/帧/流世代、采集/接收时间、时钟、视觉引用、机器人状态、任务步骤、可选候选动作。
- Assessment：算法/配置版本、关联观测/动作、风险类型、分数及含义、有效期、建议、耗时、健康。超时/断连分数为 null，不沿用旧结果。
- Intervention：UUID、来源/原因、动作、各生命周期状态及时间；相同 ID/内容返回已有结果，不同内容为 409。历史会话、缺失/陈旧帧被拒绝。重启未确认请求变 unknown，不补执行；模拟器启动默认暂停。
- Event/Session：关联帧、评估、请求、算法配置、结构化日志和定位；正常关闭标 closed，异常退出标 interrupted。

两种插件：`geometry-guard` 检查观测几何间距；`action-consistency` 联合候选动作和任务上下文核验限制区。均实现 `Algorithm.assess(Observation) -> Assessment`，独立版本/指标和 120 ms 模拟截止时间。在 `PLUGINS` 注册新实现。真实阻塞推理应另放进程/服务，不能直接塞进本服务事件循环。当前内置插件为可取消的异步模拟。

2 FPS SVG 画面通过同源 HTTPS 获取，从已存观测确定性重建，事件定位误差 0 帧。这不等于真实视频、MJPEG 或 WebRTC 验证。尚无三维、媒体协议转换或跨工具记录需求，暂不引入 Rerun、MediaMTX、MCAP。

默认 1200 帧（约 10 分钟）轮换；最多 12 会话、128 MiB 软配额，每 60 帧检查，清理最旧完整会话及其帧/事件/命令并释放 SQLite 空间。活动会话接近配额时轮换。不是永久审计。页面最近 80 事件/40 回执；回放按历史时点检索。没有真实录像/模型。每浏览器队列最多 1 快照，慢端丢旧快照并计数，最多 16 订阅者；操作有频率及并发限制。

设备处理耗时独立测量；公网 RTT 来自心跳；“接收估计”用 HTTP 中点校时，显示半 RTT 不确定度，不是精确单向传输时延。漏周期、丢快照、队列和记录故障均可见。

## 开发者内部流程

本机 `main`，`edge=ai-edge:/home/admin/safecuff-console.git`，设备 `/home/admin/safecuff-console-dev` 的 `dev`。两位开发者各维护自己的设备/配置。仓库局部使用 Windows OpenSSH，不修改全局设置；本阶段不操作 GitHub 仓库。

1. 源码：审阅、明确暂存并提交后执行 `scripts/Sync-Edge.ps1`；两端干净、只快进并核对提交。脚本不安装依赖/重启服务，不强推、不覆盖设备修改。
2. 依赖：设备独立 ARM64 环境 `~/.local/share/safecuff-console/venv`，安装 `requirements-runtime.lock`；测试另装 `requirements-dev.txt`。Python 3.10+。缺 ensurepip 时按 [pip 官方方法](https://pip.pypa.io/en/stable/installation/) 在该虚拟环境引导 pip，不改系统解释器。
3. 静态构建：本机 Node 22.12+/24，`npm ci --prefix frontend`、`npm run build --prefix frontend`、`node scripts/build-web.mjs`。产物 manifest 记录 Git revision 和逐文件 SHA256。只打包 dist，经 SCP 交付至设备外部版本目录，原子切换 `web/current`；不复制 Windows 虚拟环境/node_modules。
4. 运行配置：从 `config/example.json` 初始化 `~/.local/state/safecuff-console/config.json`，目录 700/文件 600，独立随机生成网页密码和 cookie 密钥。`scripts/edge-service.py install` 验证干净源码、构建版本/摘要并安装用户服务；首次 `--takeover-test` 只替换核验过 PID/脚本的原测试 HTTP 服务，保留 cpolar。
5. 模型：第一版无模型；后续独立交付/校验摘要，外置配置引用路径。

本机热更新由 Vite 代理 `/api` 到 SSH 转发后的 `127.0.0.1:18081`。这个地址只在开发代理配置，不进入浏览器构建。设备由 FastAPI 提供静态页面与同源 API；浏览器依据当前页面构造 REST/WSS 地址。

验证：`python -m pytest -q`；`npm run build --prefix frontend`；`npm run test:e2e --prefix frontend`，后者从环境读取 `DEMO_URL` / `DEMO_PASSWORD`。`scripts/probe.py` 支持三阶段接口验收、故障演练和 WSS 持续测量，凭据只从外置文件/环境读取，不接受密码命令行参数。结果/截图保存在忽略的 `docs/planning/`。

已核对官方用法：[React TypeScript](https://react.dev/learn/typescript)、[FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)、[WebSocket](https://fastapi.tiangolo.com/advanced/websockets/)、[Vite 静态部署](https://vite.dev/guide/static-deploy)、[SQLite](https://docs.python.org/3/library/sqlite3.html)、[Lucide React](https://lucide.dev/guide/react)。具体安装版本以 lock 为准；后端选用支持设备 Python 3.10 的发行版，明确固定 Starlette 修复版本。

## 边界和下一步

`local_reference/`、`docs/` 继续忽略。参考资料、配置/凭据、依赖、数据库、模型、日志、录像、测试产物不提交，只提交无秘密示例。

真实接入前需确定机器人型号、SDK/ROS 接口/权限、相机来源/编码/时钟、任务状态和动作回执。先接只读适配器，再验证真实动作语义、期限、仲裁和独立安全措施。网页暂停只作用模拟器，不构成人身安全保证。SQLite 记录/清理与 API 仍在同一进程，尚无独立推理进程隔离、永久审计、多人控制租约或高可用；真实控制前必须另行实现和验证。
