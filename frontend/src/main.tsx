import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ShieldCheck,
  Radio,
  History,
  Activity,
  Layers,
  LogIn,
  LogOut,
  ChevronRight,
  Pause,
  Play,
  AlertTriangle,
  RefreshCw,
  Wifi,
  Camera,
  Terminal,
  ExternalLink,
} from "lucide-react";
import type { State, Frame, Session, Event, Command } from "./types";
import "./style.css";

async function api<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch("/api" + path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    const v = await r.json().catch(() => ({ detail: r.statusText }));
    throw Error(v.detail || r.statusText);
  }
  return r.json();
}
const clock = (n: number) =>
  new Date(n * 1000).toLocaleTimeString("zh-CN", { hour12: false });
const short = (s: string) => s.slice(0, 8);
const names: Record<string, string> = {
  "geometry-guard": "几何边界守卫",
  "action-consistency": "动作语义核验",
};
const statusNames: Record<string, string> = {
  ok: "正常",
  timeout: "超时",
  disconnected: "断连",
  error: "异常",
  requested: "已请求",
  accepted: "已接受 · 待确认",
  rejected: "已拒绝",
  executed: "模拟执行已确认",
  failed: "执行失败",
  unknown: "结果未知",
};

function App() {
  const [role, setRole] = useState(""),
    [loading, setLoading] = useState(true),
    [password, setPassword] = useState(""),
    [loginRole, setLoginRole] = useState("operator"),
    [publicViewer, setPublicViewer] = useState(false),
    [operatorLoginEnabled, setOperatorLoginEnabled] = useState(false),
    [showOperatorLogin, setShowOperatorLogin] = useState(false);
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [state, setState] = useState<State | null>(null),
    [connection, setConnection] = useState("连接中");
  const [page, setPage] = useState("live"),
    [sessions, setSessions] = useState<Session[]>([]),
    [selected, setSelected] = useState(""),
    [indices, setIndices] = useState<number[]>([]),
    [position, setPosition] = useState(0);
  const [history, setHistory] = useState<{
      live: Frame;
      events: Event[];
      interventions: Command[];
    } | null>(null),
    [playing, setPlaying] = useState(false),
    [logFilter, setLogFilter] = useState("");
  const [curve, setCurve] = useState<Frame[]>([]),
    [busy, setBusy] = useState(false),
    [now, setNow] = useState(Date.now()),
    [rtt, setRtt] = useState(0),
    [transport, setTransport] = useState<number | null>(null);
  const socket = useRef<WebSocket | null>(null),
    lastMessage = useRef(0),
    lastFrame = useRef(""),
    retry = useRef(0),
    clockOffset = useRef(0),
    clockRtt = useRef(0),
    replayGeneration = useRef(0),
    replayTarget = useRef<number | null>(null);
  const live = page !== "replay",
    frame = live ? state?.live : history?.live,
    obs = frame?.observation;
  const events = (live ? state?.events : history?.events) || [],
    commands = (live ? state?.interventions : history?.interventions) || [];
  const stale =
    !state ||
    now - lastMessage.current > 4000 ||
    state.metrics.data_age_ms + (now - lastMessage.current) > 2500;
  const writable =
    role === "operator" &&
    live &&
    connection === "已连接" &&
    !stale &&
    state?.metrics.recording_health === "ok";
  useEffect(() => {
    api<{
      role: string;
      public_viewer: boolean;
      operator_login_enabled: boolean;
    }>("/me")
      .then((v) => {
        setRole(v.role);
        setPublicViewer(v.public_viewer);
        setOperatorLoginEnabled(v.operator_login_enabled);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    if (!role) return;
    let stopped = false,
      timer: ReturnType<typeof setTimeout>,
      heartbeat: ReturnType<typeof setInterval>;
    async function sampleClock() {
      const start = Date.now();
      try {
        const v = await api<{ server_time: number }>("/clock");
        clockRtt.current = Date.now() - start;
        clockOffset.current = v.server_time * 1000 - (start + Date.now()) / 2;
      } catch {}
    }
    void sampleClock();
    function connect() {
      if (stopped) return;
      setConnection("连接中");
      const u = new URL("/api/ws", location.href);
      u.protocol = location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(u);
      socket.current = ws;
      ws.onopen = () => {
        retry.current = 0;
        setConnection("已连接");
        lastMessage.current = Date.now();
        heartbeat = setInterval(() => {
          if (Date.now() - lastMessage.current > 7000) {
            ws.close();
            return;
          }
          if (ws.readyState === 1)
            ws.send(
              JSON.stringify({ type: "ping", client_time: performance.now() }),
            );
        }, 3000);
      };
      ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.type === "pong") {
          setRtt(performance.now() - data.client_time);
          return;
        }
        lastMessage.current = Date.now();
        setState(data);
        const f = data.live as Frame | null;
        if (f) {
          const key = f.observation.session_id + ":" + f.observation.frame_id;
          if (lastFrame.current !== key) {
            lastFrame.current = key;
            setCurve((c) =>
              [
                ...c.filter(
                  (x) => x.observation.session_id === f.observation.session_id,
                ),
                f,
              ].slice(-80),
            );
          }
          setTransport(
            Math.max(
              0,
              Date.now() + clockOffset.current - data.server_sent_at * 1000,
            ),
          );
        }
      };
      ws.onclose = () => {
        clearInterval(heartbeat);
        if (!stopped) {
          setConnection("断开 · 自动重连");
          timer = setTimeout(
            connect,
            Math.min(1000 * 2 ** retry.current++, 10000),
          );
        }
      };
      ws.onerror = () => ws.close();
    }
    connect();
    const t = setInterval(sampleClock, 30000);
    return () => {
      stopped = true;
      clearTimeout(timer);
      clearInterval(heartbeat);
      clearInterval(t);
      socket.current?.close();
    };
  }, [role]);
  useEffect(() => {
    if (role && (page === "replay" || page === "sessions")) {
      api<Session[]>("/sessions")
        .then(setSessions)
        .catch((e) => setError(e.message));
    }
  }, [page, role]);
  useEffect(() => {
    if (!selected) return;
    setPlaying(false);
    setHistory(null);
    const gen = ++replayGeneration.current;
    api<number[]>("/sessions/" + selected + "/frames")
      .then((v) => {
        if (gen === replayGeneration.current) {
          setIndices(v);
          setPosition(
            replayTarget.current === null
              ? 0
              : Math.max(0, v.indexOf(replayTarget.current)),
          );
          replayTarget.current = null;
        }
      })
      .catch((e) => setError(e.message));
  }, [selected]);
  useEffect(() => {
    if (page !== "replay" || !selected || !indices.length) return;
    let cancelled = false;
    api<{ live: Frame; events: Event[]; interventions: Command[] }>(
      `/sessions/${selected}/frames/${indices[position]}`,
    )
      .then((v) => {
        if (!cancelled) setHistory(v);
      })
      .catch((e) => setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [page, selected, position, indices]);
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(
      () =>
        setPosition((p) => {
          if (p >= indices.length - 1) {
            setPlaying(false);
            return p;
          }
          return p + 1;
        }),
      500,
    );
    return () => clearInterval(t);
  }, [playing, indices]);
  async function login(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const v = await api<{ role: string }>("/login", {
        role: publicViewer ? "operator" : loginRole,
        password,
      });
      setRole(v.role);
      setPassword("");
      setShowOperatorLogin(false);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function action(value: string) {
    if (!writable || !obs) return;
    setBusy(true);
    setError("");
    try {
      const c = await api<Command>("/interventions", {
        request_id: crypto.randomUUID(),
        session_id: obs.session_id,
        frame_id: obs.frame_id,
        action: value,
        reason: "控制台人工模拟验证",
      });
      setNotice(`${statusNames[c.status]} · ${short(c.request_id)}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function fault(target: string, mode: string) {
    try {
      await api("/faults", { target, mode });
      setNotice("已注入模拟状态：" + mode);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function locate(e: Event) {
    replayTarget.current = e.frame_id;
    setPage("replay");
    setPlaying(false);
    setNotice(`已定位事件原帧 #${e.frame_id}，关联误差 0 帧`);
    if (selected !== e.session_id) {
      setSelected(e.session_id);
    } else {
      try {
        const ids = await api<number[]>(
          "/sessions/" + e.session_id + "/frames",
        );
        setIndices(ids);
        setPosition(Math.max(0, ids.indexOf(e.frame_id)));
        replayTarget.current = null;
      } catch (err) {
        setError((err as Error).message);
      }
    }
  }

  if (loading) return <div className="login">正在连接控制台…</div>;
  if (!role || showOperatorLogin)
    return (
      <div className="login">
        <form onSubmit={login}>
          <div className="brand-icon">
            <ShieldCheck size={32} />
          </div>
          <small>SAFECUFF / EDGE CONSOLE</small>
          <h1>安全箍观察控制台</h1>
          <p>设备侧持续记录，浏览器连接即可观察。</p>
          <div className="sim-note">模拟环境 · 不连接真实机器人</div>
          {!publicViewer && (
            <label>
              访问身份
              <select
                value={loginRole}
                onChange={(e) => setLoginRole(e.target.value)}
              >
                <option value="operator">操作员 · 可模拟干预</option>
                <option value="viewer">观察员 · 只读</option>
              </select>
            </label>
          )}
          <label>
            访问密码
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="primary" type="submit">
            进入控制台 <ChevronRight size={16} />
          </button>
          {publicViewer && (
            <button
              type="button"
              onClick={() => {
                setShowOperatorLogin(false);
                setPassword("");
                setError("");
              }}
            >
              返回公开演示
            </button>
          )}
          <span className="hint">登录有效期 8 小时 · 独立网页凭据</span>
        </form>
      </div>
    );
  const nav = [
    ["live", "实时观察", Radio],
    ["sessions", "实验会话", History],
    ["algorithms", "算法管理", Layers],
    ["logs", "运行日志", Terminal],
  ] as const;
  return (
    <div className="shell">
      <aside>
        <div className="brand">
          <ShieldCheck />
          <div>
            安全箍<small>SAFECUFF CONSOLE</small>
          </div>
        </div>
        <div className="workspace">
          <span className="dot" /> EDGE WORKSPACE <small>RK3588 · 单设备</small>
        </div>
        <nav>
          {nav.map(([key, label, Icon]) => (
            <button
              key={key}
              className={
                page === key || (key === "sessions" && page === "replay")
                  ? "active"
                  : ""
              }
              onClick={() => {
                setPage(key);
                setError("");
              }}
            >
              <Icon size={18} />
              {label}
              {page === key && <ChevronRight size={14} />}
            </button>
          ))}
        </nav>
        <div className="aside-bottom">
          <div className="device-mini">
            <span className="dot" /> rk3588-demo
            <small>仅模拟执行器已启用</small>
          </div>
          {(!publicViewer || role === "operator") && (
            <button
              onClick={async () => {
                try {
                  await api("/logout", {});
                  setRole(publicViewer ? "viewer" : "");
                  setState(null);
                } catch (err) {
                  setError((err as Error).message);
                }
              }}
            >
              <LogOut size={16} />
              退出{role === "operator" ? "操作员" : "观察员"}
            </button>
          )}
        </div>
      </aside>
      <div className="main">
        <header>
          <span>
            工作台 <ChevronRight size={14} />{" "}
            {page === "replay"
              ? "会话回放"
              : nav.find((x) => x[0] === page)?.[1]}
          </span>
          <div>
            {publicViewer &&
              role === "viewer" &&
              (operatorLoginEnabled ? (
                <button
                  onClick={() => {
                    setError("");
                    setShowOperatorLogin(true);
                  }}
                >
                  <LogIn size={14} /> 操作员登录
                </button>
              ) : (
                <small>公开只读</small>
              ))}
            <span className="simulation">SIMULATION</span>
            <span
              className={
                "connection " + (connection === "已连接" ? "good" : "bad")
              }
            >
              <Wifi size={14} />
              {connection}
            </span>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">EDGE SAFETY OBSERVABILITY</div>
              <h1>
                {page === "live"
                  ? "实时观察"
                  : page === "replay"
                    ? "会话回放"
                    : nav.find((x) => x[0] === page)?.[1]}
              </h1>
              <p>
                {page === "replay"
                  ? "历史快照 · 执行操作已关闭，实时采集仍在设备继续。"
                  : "从观测、算法建议到执行回执，让每一步都有据可查。"}
              </p>
            </div>
            <a
              className="health-link"
              href="/healthz"
              target="_blank"
              rel="noreferrer"
            >
              健康与版本 <ExternalLink size={14} />
            </a>
          </div>
          <div className="banner">
            <ShieldCheck size={17} />
            <b>模拟验证环境</b>
            <span>
              所有画面、算法与执行回执均为模拟数据；未接入机器人运动、急停或断能。
            </span>
          </div>
          {error && (
            <div className="error toast" role="alert">
              {error}
              <button onClick={() => setError("")}>关闭</button>
            </div>
          )}
          {notice && (
            <div className="notice toast" role="status">
              {notice}
              <button onClick={() => setNotice("")}>收起</button>
            </div>
          )}
          {(stale || connection !== "已连接") && (
            <div className="error toast">
              <AlertTriangle size={16} />
              实时数据陈旧或连接中断 · 模拟干预已禁用 · 设备采集独立运行
            </div>
          )}
          {(page === "live" || page === "replay") && (
            <>
              {page === "replay" && (
                <section className="card replay">
                  <div className="row">
                    <b>
                      <History size={16} /> 历史时间轴
                    </b>
                    <select
                      aria-label="选择回放会话"
                      value={selected}
                      onChange={(e) => setSelected(e.target.value)}
                    >
                      <option value="">请选择会话</option>
                      {sessions.map((s) => (
                        <option key={s.session_id} value={s.session_id}>
                          {clock(s.started_at)} · {short(s.session_id)} ·{" "}
                          {s.status}
                        </option>
                      ))}
                    </select>
                    <button
                      disabled={!indices.length}
                      onClick={() => setPlaying(!playing)}
                    >
                      {playing ? <Pause size={16} /> : <Play size={16} />}{" "}
                      {playing ? "暂停回放" : "播放回放"}
                    </button>
                    <button
                      onClick={() => {
                        setPlaying(false);
                        setPage("live");
                      }}
                    >
                      返回实时
                    </button>
                  </div>
                  <input
                    aria-label="回放帧"
                    type="range"
                    min={0}
                    max={Math.max(0, indices.length - 1)}
                    value={position}
                    onChange={(e) => {
                      setPlaying(false);
                      setPosition(Number(e.target.value));
                    }}
                  />
                  <span className="muted">
                    帧 #{indices[position] || "—"} / {indices.length}{" "}
                    个已记录快照 · {selected && short(selected)}
                  </span>
                </section>
              )}
              <div className="stats">
                <div>
                  <span>观测源</span>
                  <b>
                    {live ? (stale ? "数据陈旧" : "持续采集") : "历史快照"}
                    <span className={"dot " + (stale && live ? "amber" : "")} />
                  </b>
                  <small>
                    {live ? "2 FPS · 设备独立记录" : "时间轴定位 · 2 FPS"}
                  </small>
                </div>
                <div>
                  <span>当前任务</span>
                  <b>{obs?.task_step.name || "等待观测"}</b>
                  <small>
                    步骤 {obs?.task_step.step || "—"} / 4 ·{" "}
                    {obs?.task_step.label}
                  </small>
                </div>
                <div>
                  <span>算法状态</span>
                  <b>
                    {frame?.assessments.filter((a) => a.health === "ok")
                      .length || 0}{" "}
                    <em>/ 2 正常</em>
                  </b>
                  <small>分数独立解释 · 不进行相加</small>
                </div>
                <div>
                  <span>{live ? "数据新鲜度" : "记录时间"}</span>
                  <b>
                    {live
                      ? `${Math.round((state?.metrics.data_age_ms || 0) + (now - lastMessage.current))} ms`
                      : obs
                        ? clock(obs.captured_at)
                        : "—"}
                  </b>
                  <small>
                    {live
                      ? `设备处理 ${frame?.processing_ms.toFixed(1) || "—"} ms`
                      : "UTC 存储 / 本地时间显示"}
                  </small>
                </div>
              </div>
              <div className="observation-grid">
                <section className="card visual">
                  <div className="card-title">
                    <b>
                      <Camera size={17} />
                      视觉观测
                    </b>
                    <span className={"pill " + (live ? "green" : "orange")}>
                      {live ? "LIVE / 模拟" : "HISTORY / 只读"}
                    </span>
                  </div>
                  <div className="image-wrap">
                    {obs ? (
                      <img
                        src={obs.visual_ref}
                        alt={`模拟观测帧 ${obs.frame_id}`}
                      />
                    ) : (
                      <div className="empty">等待观测帧</div>
                    )}
                    <div className="image-label">
                      {obs?.device_id || "rk3588-demo"}{" "}
                      <span>
                        FRAME {obs?.frame_id.toString().padStart(6, "0") || "—"}
                      </span>
                    </div>
                  </div>
                  <div className="visual-footer">
                    <span>
                      会话 <code>{obs ? short(obs.session_id) : "—"}</code>
                    </span>
                    <span>采集 {obs ? clock(obs.captured_at) : "—"}</span>
                    <span>SIM · 原始证据可复现</span>
                  </div>
                </section>
                <section className="card task">
                  <div className="card-title">
                    <b>
                      <Activity size={17} />
                      任务与执行状态
                    </b>
                    <span className="muted">模拟器</span>
                  </div>
                  <div className="task-state">
                    <span
                      className={
                        "dot " + (obs?.robot_state.paused ? "amber" : "")
                      }
                    />
                    {obs?.robot_state.paused
                      ? "任务已模拟暂停"
                      : "巡检任务模拟运行"}
                  </div>
                  <div className="steps">
                    {["观察", "接近目标", "核验路径", "返回"].map((n, i) => (
                      <div
                        className={
                          obs?.task_step.step === i + 1 ? "current" : ""
                        }
                        key={n}
                      >
                        <span>{i + 1}</span>
                        {n}
                      </div>
                    ))}
                  </div>
                  <dl>
                    <div>
                      <dt>机器人模式</dt>
                      <dd>SIMULATION</dd>
                    </div>
                    <div>
                      <dt>模拟速度</dt>
                      <dd>
                        {obs?.robot_state.speed_mps.toFixed(2) || "—"} m/s
                      </dd>
                    </div>
                    <div>
                      <dt>候选动作目标</dt>
                      <dd>{obs?.candidate_action?.target_zone || "—"}</dd>
                    </div>
                    <div>
                      <dt>执行能力</dt>
                      <dd>pause / resume（模拟）</dd>
                    </div>
                  </dl>
                  <div className="actions">
                    <button
                      className="primary"
                      disabled={!writable || busy}
                      onClick={() => action("pause")}
                    >
                      <Pause size={15} />
                      请求模拟暂停
                    </button>
                    <button
                      disabled={!writable || busy}
                      onClick={() => action("resume")}
                    >
                      <Play size={15} />
                      申请模拟恢复
                    </button>
                  </div>
                  <p className="hint">
                    算法建议不会自动执行。恢复需算法正常且无当前建议。
                  </p>
                </section>
              </div>
              <div className="middle-grid">
                <section className="card">
                  <div className="card-title">
                    <b>
                      <Activity size={17} />
                      {live ? "风险指标 · 最近 40 秒" : "该帧算法结果"}
                    </b>
                    <span className="muted">未校准指标 ≠ 概率</span>
                  </div>
                  {live ? (
                    <div className="chart">
                      <div className="chart-labels">
                        <span>1.0</span>
                        <span>0.5</span>
                        <span>0.0</span>
                      </div>
                      <svg
                        viewBox="0 0 760 145"
                        role="img"
                        aria-label="两条独立风险曲线"
                      >
                        <path
                          d="M0 5H760 M0 72H760 M0 140H760"
                          stroke="#e5ebee"
                          fill="none"
                        />
                        {["geometry-guard", "action-consistency"].map(
                          (id, j) => (
                            <polyline
                              key={id}
                              fill="none"
                              stroke={j ? "#d99745" : "#138c87"}
                              strokeWidth="2.5"
                              points={curve
                                .map((f, i) => {
                                  const a = f.assessments.find(
                                    (a) => a.algorithm_id === id,
                                  );
                                  return a?.score !== null &&
                                    a?.score !== undefined
                                    ? `${(i * 760) / 79},${140 - a.score * 135}`
                                    : "";
                                })
                                .join(" ")}
                            />
                          ),
                        )}
                      </svg>
                    </div>
                  ) : (
                    <div className="history-note">
                      此处仅显示定位帧的评估；不会混入实时风险曲线。
                    </div>
                  )}
                  <div className="algorithm-cards">
                    {frame?.assessments.map((a, i) => (
                      <div key={a.algorithm_id}>
                        <span>
                          <i
                            style={{ background: i ? "#d99745" : "#138c87" }}
                          />
                          {names[a.algorithm_id]}
                        </span>
                        <strong>
                          {a.health === "ok" ? a.score?.toFixed(2) : "—"}{" "}
                          <small className={a.health === "ok" ? "good" : "bad"}>
                            {statusNames[a.health]}
                          </small>
                        </strong>
                        <small>
                          {a.processing_ms.toFixed(1)} ms ·{" "}
                          {a.suggested_action ? "建议暂停" : "无动作建议"}
                          {live &&
                          a.valid_until * 1000 < now + clockOffset.current
                            ? " · 已过期"
                            : ""}
                        </small>
                        <small title={a.score_meaning}>
                          {a.algorithm_id} · v{a.algorithm_version}
                        </small>
                      </div>
                    ))}
                  </div>
                </section>
                <section className="card">
                  <div className="card-title">
                    <b>
                      <AlertTriangle size={17} />
                      安全事件
                    </b>
                    <span className="muted">点击定位原帧</span>
                  </div>
                  <div className="event-list">
                    {events.length ? (
                      events.slice(0, 12).map((e) => (
                        <button
                          key={e.event_id}
                          data-event-id={e.event_id}
                          data-frame={e.frame_id}
                          onClick={() => locate(e)}
                        >
                          <span className={"event-dot " + e.level} />
                          <div>
                            <b>{e.message}</b>
                            <small>
                              {clock(e.at)} · 帧 #{e.frame_id} · {e.kind}
                            </small>
                          </div>
                          <ChevronRight size={15} />
                        </button>
                      ))
                    ) : (
                      <div className="empty">暂无事件</div>
                    )}
                  </div>
                </section>
              </div>
              <section className="card">
                <div className="card-title">
                  <b>
                    <Terminal size={17} />
                    干预请求与执行回执
                  </b>
                  <span className="muted">
                    建议 → 人工请求 → 接受 / 拒绝 → 模拟执行确认
                  </span>
                </div>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>请求 ID / 来源</th>
                        <th>关联帧</th>
                        <th>动作</th>
                        <th>状态</th>
                        <th>生命周期与结果</th>
                      </tr>
                    </thead>
                    <tbody>
                      {commands.map((c) => (
                        <tr key={c.request_id}>
                          <td>
                            <code title={c.request_id}>
                              {short(c.request_id)}
                            </code>
                            <small>{c.source}</small>
                          </td>
                          <td>#{c.frame_id}</td>
                          <td>
                            {c.action === "pause" ? "模拟暂停" : "模拟恢复"}
                          </td>
                          <td>
                            <span
                              className={
                                "pill " +
                                (c.status === "executed" ? "green" : "orange")
                              }
                            >
                              {statusNames[c.status]}
                            </span>
                          </td>
                          <td>
                            <div>
                              {c.transitions
                                .map((t) => statusNames[t.status])
                                .join(" → ")}
                            </div>
                            <small>{c.result}</small>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!commands.length && (
                    <div className="empty">
                      尚无人工干预请求。算法建议会单独记录在安全事件中。
                    </div>
                  )}
                </div>
              </section>
            </>
          )}
          {page === "sessions" && (
            <section className="card">
              <div className="card-title">
                <b>
                  <History size={17} />
                  设备会话记录
                </b>
                <button
                  onClick={() =>
                    api<Session[]>("/sessions")
                      .then(setSessions)
                      .catch((e) => setError(e.message))
                  }
                >
                  <RefreshCw size={14} />
                  刷新
                </button>
              </div>
              <p className="section-description">
                设备自动记录，10 分钟轮换；最多保留 12 个会话，磁盘配额 128
                MiB。旧会话按配额清理。
              </p>
              <table>
                <thead>
                  <tr>
                    <th>会话 ID</th>
                    <th>开始时间</th>
                    <th>状态</th>
                    <th>代码版本</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((s) => (
                    <tr key={s.session_id}>
                      <td>
                        <code>{short(s.session_id)}</code>
                      </td>
                      <td>
                        {new Date(s.started_at * 1000).toLocaleString("zh-CN")}
                      </td>
                      <td>
                        {s.status === "live"
                          ? "正在记录"
                          : s.status === "closed"
                            ? "已关闭"
                            : "上次中断"}
                      </td>
                      <td>
                        <code>{short(s.revision)}</code>
                      </td>
                      <td>
                        <button
                          onClick={() => {
                            setSelected(s.session_id);
                            setPage("replay");
                          }}
                        >
                          <History size={14} />
                          打开回放
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
          {page === "algorithms" && (
            <>
              <div className="algorithm-management">
                {Object.entries(state?.algorithm_config || {}).map(
                  ([id, c]) => (
                    <section className="card" key={id}>
                      <div className="card-title">
                        <b>
                          <Layers size={17} />
                          {names[id]}
                        </b>
                        <span className="pill green">PLUGIN</span>
                      </div>
                      <div className="section-description">
                        <h2>{id}</h2>
                        <p>
                          {id === "geometry-guard"
                            ? "路线 A：从观测中的几何间距评估接近程度。"
                            : "路线 B：联合候选动作目标与任务上下文检查限制区。"}
                        </p>
                        <code>v{c.version} / demo-v1</code>
                        <p>
                          统一 Observation → Assessment 契约；可替换 Python
                          插件，不绑定 ROS、RKNN 或特定模型。
                        </p>
                        <label>
                          模拟健康状态
                          <select
                            aria-label={id + " 模拟状态"}
                            disabled={role !== "operator"}
                            value={c.mode}
                            onChange={(e) => fault(id, e.target.value)}
                          >
                            <option value="normal">正常</option>
                            <option value="timeout">
                              注入超时（120 ms 截止）
                            </option>
                            <option value="disconnected">注入断连</option>
                          </select>
                        </label>
                      </div>
                    </section>
                  ),
                )}
              </div>
              <section className="card">
                <div className="card-title">
                  <b>
                    <AlertTriangle size={17} />
                    链路故障验证
                  </b>
                  <span className="muted">只影响模拟服务</span>
                </div>
                <div className="fault-actions">
                  <button
                    disabled={role !== "operator"}
                    onClick={() => fault("capture", "freeze")}
                  >
                    冻结采集 8 秒
                  </button>
                  <button
                    disabled={role !== "operator"}
                    onClick={() => fault("capture", "normal")}
                  >
                    恢复采集
                  </button>
                  <button
                    disabled={role !== "operator"}
                    onClick={() => fault("executor", "fail_next")}
                  >
                    下一次模拟执行失败
                  </button>
                  <button
                    disabled={role !== "operator"}
                    onClick={() => fault("executor", "normal")}
                  >
                    清除执行故障
                  </button>
                  <button onClick={() => socket.current?.close()}>
                    断开网页连接并验证重连
                  </button>
                </div>
                <p className="section-description">
                  采集冻结会使数据陈旧；恢复操作仍需人工请求。网页断连不会停止设备采集和记录。
                </p>
              </section>
            </>
          )}
          {page === "logs" && (
            <section className="card">
              <div className="card-title">
                <b>
                  <Terminal size={17} />
                  会话结构化日志
                </b>
                <input
                  aria-label="筛选日志"
                  placeholder="筛选内容、类型或请求 ID"
                  value={logFilter}
                  onChange={(e) => setLogFilter(e.target.value)}
                />
              </div>
              <div className="logs">
                {state?.events
                  .filter((e) =>
                    JSON.stringify(e)
                      .toLowerCase()
                      .includes(logFilter.toLowerCase()),
                  )
                  .map((e) => (
                    <div key={e.event_id}>
                      <time>{clock(e.at)}</time>
                      <span className={e.level === "error" ? "bad" : "muted"}>
                        {e.level.toUpperCase()}
                      </span>
                      <code>
                        #{e.frame_id} / {e.kind}
                      </code>
                      <span>
                        {e.message}
                        {e.request_id && " · " + e.request_id}
                      </span>
                      <button onClick={() => locate(e)}>定位</button>
                    </div>
                  ))}
              </div>
            </section>
          )}
          <footer>
            <span>
              <span className="dot" /> 设备记录器：
              {state?.metrics.recording_health === "ok"
                ? "正常"
                : "异常"} ·{" "}
              {((state?.metrics.recording_bytes || 0) / 1024 ** 2).toFixed(1)} /{" "}
              {state?.metrics.quota_mb || 128} MiB
            </span>
            <span>
              处理 {frame?.processing_ms.toFixed(1) || "—"} ms · 公网 RTT{" "}
              {rtt ? rtt.toFixed(0) : "—"} ms · 接收估计{" "}
              {transport?.toFixed(0) ?? "—"} ms ±
              {(clockRtt.current / 2).toFixed(0)} ms
            </span>
            <span>
              漏周期 {state?.metrics.scheduler_missed || 0} · 丢快照{" "}
              {state?.metrics.subscriber_drops || 0} · 队列{" "}
              {state?.metrics.max_queue_depth || 0} · v0.1.0 /{" "}
              {short(state?.session.revision || "development")}
            </span>
          </footer>
        </main>
      </div>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
