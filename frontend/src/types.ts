export type Observation = {
  schema_version: 1;
  device_id: string;
  session_id: string;
  stream_epoch: string;
  frame_id: number;
  captured_at: number;
  received_at: number;
  clock_source: string;
  visual_ref: string;
  robot_state: {
    mode: string;
    paused: boolean;
    clearance_m: number;
    speed_mps: number;
  };
  task_step: {
    task_id: string;
    name: string;
    step: number;
    total: number;
    label: string;
  };
  candidate_action?: { action_id: string; target_zone: string };
};
export type Assessment = {
  assessment_id: string;
  algorithm_id: string;
  algorithm_version: string;
  frame_id: number;
  score: number | null;
  score_meaning: string;
  risk_type: string;
  health: string;
  valid_until: number;
  processing_ms: number;
  suggested_action: string | null;
};
export type Frame = {
  observation: Observation;
  assessments: Assessment[];
  processing_ms: number;
};
export type Event = {
  event_id: string;
  session_id: string;
  frame_id: number;
  at: number;
  kind: string;
  level: string;
  message: string;
  request_id?: string;
  assessment_id?: string;
};
export type Command = {
  request_id: string;
  session_id: string;
  frame_id: number;
  source: string;
  action: string;
  reason: string;
  status: string;
  result: string;
  transitions: { status: string; at: number; detail: string }[];
};
export type Session = {
  session_id: string;
  started_at: number;
  status: string;
  revision: string;
  ended_at?: number;
};
export type State = {
  sequence: number;
  server_sent_at: number;
  live: Frame | null;
  session: Session;
  events: Event[];
  interventions: Command[];
  algorithm_config: Record<string, { version: string; mode: string }>;
  metrics: {
    uptime_s: number;
    data_age_ms: number;
    captured_frames: number;
    scheduler_missed: number;
    subscriber_drops: number;
    recording_health: string;
    recording_errors: number;
    recording_bytes: number;
    quota_mb: number;
    subscribers: number;
    max_queue_depth: number;
    pruned_sessions: number;
  };
};
