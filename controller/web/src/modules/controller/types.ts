/**
 * The shapes `controller/http.py` answers with.
 *
 * Every field is optional or nullable on purpose. The controller answers from
 * whatever telemetry has arrived, and a panel that has no rows must draw an
 * empty state rather than throw. `controller/snapshot.py` is the source of
 * truth for the names.
 */

/** One row of a project's job ledger, plus the two fields the API joins on. */
export type Job = {
  job_id: string;
  purpose?: string | null;
  execution_id?: string | null;
  stage_id?: string | null;
  attempt_id?: string | null;
  exp?: string | null;
  partition?: string | null;
  status?: string | null;
  attempt?: number | null;
  submitted_utc?: string | null;
  hardware?: string | null;
  elapsed_s?: number | null;
  updated_utc?: string | null;
  /** The attached project this row came from. */
  slug?: string | null;
  campaign?: string | null;
};

export type Partition = {
  name: string;
  nodes?: number | null;
  gpu_types?: string[];
  max_walltime?: string;
  access?: string;
  gpus_total?: number | null;
  cpus_total?: number | null;
  /** Percent allocated, or null when no rollup covers this partition. */
  util?: number | null;
  wait_s_avg?: number | null;
  jobs?: number | null;
  gpu_hours?: number | null;
};

export type GpuFleetEntry = {
  gpu_type: string;
  total: number;
  allocated: number;
  pending: number;
  free: number;
  vram_gb?: number[];
};

export type LiveSample = {
  timestamp_utc?: string;
  gpu_running?: number;
  gpu_pending?: number;
  gpu_preempt_pending?: number;
  total_nodes?: number;
  free_nodes?: number;
  gpu_types_free?: string;
};

export type TrendPoint = {
  t: string;
  running: number;
  pending: number;
  preempt_pending?: number;
};

export type LiveBlock = {
  available: boolean;
  latest: LiveSample;
  trend: TrendPoint[];
  /** How old the newest sample is. Null when no sample exists. */
  age_s?: number | null;
  /** False once the newest sample is older than the live window. */
  fresh?: boolean;
  source?: string;
};

export type Fairshare = {
  available: boolean;
  factor?: number | null;
  effective_usage?: number | null;
  observed_utc?: string | null;
  account?: string;
};

export type ClusterUser = {
  user: string;
  /** Account with the most jobs. */
  account?: string;
  /** Every account this user billed, most frequent first. */
  accounts?: string[];
  jobs: number;
  /** Settled and live counts. They sum to `jobs`. */
  completed?: number;
  failed?: number;
  timeout?: number;
  oom?: number;
  preempted?: number;
  cancelled?: number;
  running?: number;
  pending?: number;
  requeued?: number;
  other?: number;
  /** Wall-clock elapsed hours. */
  hours: number;
  gpu_jobs: number;
  /** GPUs allocated × elapsed hours. */
  gpu_hours: number;
  /** CPUs allocated × elapsed hours. */
  cpu_hours?: number;
  /** Nodes allocated × elapsed hours. */
  node_hours?: number;
  /** Allocated memory × elapsed time, in GB-hours. */
  mem_gb_hours?: number;
  /** Mean CPUs held over elapsed hours. Null when no time was recorded. */
  avg_cpus?: number | null;
  /** Mean GPUs held on jobs that allocated a GPU. */
  avg_gpus?: number | null;
  /** Mean seconds from submit to start. Null when no job recorded both. */
  avg_wait_s?: number | null;
  /** Completed ÷ settled jobs, as a percent. Null when none are settled. */
  success_pct?: number | null;
  /** Newest end, else start, else submit, as UTC. */
  last_seen?: string | null;
  /** True when this row only covers part of the selected window. */
  partial?: boolean;
  /** Partition with the most jobs. */
  partition?: string;
  /** Every partition this user used, most frequent first. */
  partitions?: string[];
  /** GPU type with the most GPU jobs. Empty when none was named. */
  gpu_type?: string;
};

export type UsersBlock = {
  available: boolean;
  rows: ClusterUser[];
  source?: string | null;
  /** Null when every live job is included. */
  hours?: number | null;
  /** `recent` is the selected span ending now. It does not slide backward. */
  window?: 'all' | 'recent' | string;
  /** True when live samples do not cover the whole selected span. */
  partial?: boolean;
  covered_start_utc?: string | null;
  covered_end_utc?: string | null;
  window_start_utc?: string | null;
  window_end_utc?: string | null;
};

export type HardwareStat = {
  hardware?: string;
  partition?: string;
  runs: number;
  gpu_hours: number;
  wait_s_avg?: number | null;
};

export type TaskStats = {
  available: boolean;
  runs: number;
  gpu_hours?: number | null;
  wait_s_avg?: number | null;
  wait_s_gpu_avg?: number | null;
  counts: Record<string, number>;
  by_hardware: HardwareStat[];
  by_partition: HardwareStat[];
};

export type ClusterKpis = {
  gpu_running?: number;
  gpu_pending?: number;
  free_nodes?: number;
  total_nodes?: number;
  gpu_types_free?: string;
  attached_projects?: number;
  gpus_total?: number;
  gpus_allocated?: number;
  gpus_free?: number;
  gpu_types_busy?: number;
};

export type Cluster = {
  generated_utc?: string;
  cluster?: string;
  slurm_version?: string;
  live: LiveBlock;
  partitions: Partition[];
  gpu_fleet: GpuFleetEntry[];
  fairshare: Fairshare;
  users: UsersBlock;
  stats: TaskStats;
  kpis: ClusterKpis;
  config_present?: boolean;
};

export type QueueAnswer = {
  partitions: Partition[];
  live: LiveBlock;
};

export type UsageBlock = {
  available: boolean;
  /** The x axis: one label per time slot. */
  slots: string[];
  /** GPU type to one value per slot. A null is a slot with no sample. */
  series: Record<string, (number | null)[]>;
  by_type: { gpu_type: string; avg: number; peak: number; median: number }[];
  heatmap: { dow: number; hour: number; value: number; samples?: number }[];
  /** The selected span ending now. It does not slide backward. */
  window: 'recent' | 'all' | string;
  /** True when stored samples do not cover that whole span. */
  partial?: boolean;
  /** Null when the window is every stored row. */
  hours: number | null;
  freshness_utc?: string | null;
  stale_s?: number | null;
  window_start_utc?: string | null;
  window_end_utc?: string | null;
  /** sacct counts allocated GPUs; collector samples are percentages. */
  unit?: 'gpus' | 'percent';
  source?: 'sacct' | 'samples';
  covered_hours?: number;
  gpu_hours?: number;
  avg_allocated?: number;
  peak_allocated?: number;
};

export type UsageAnswer = {
  usage: UsageBlock;
  outcomes: { available: boolean; counts: Record<string, number> };
  stats: TaskStats;
};

export type Project = {
  slug: string;
  path?: string;
  primitive?: string;
  remote_dir?: string;
  unity_host?: string;
  campaign?: string;
  overrides?: Record<string, string>;
  scaffold?: boolean;
  env_present?: boolean;
  campaigns?: string[];
  job_counts?: Record<string, number>;
  jobs?: Job[];
};

export type ControllerEvent = {
  ts?: string;
  kind?: string;
  message?: string;
  ok?: boolean;
  slug?: string;
};

export type SshStatus = {
  host?: string;
  identity?: string;
  command?: string;
  key_path?: string;
  needs_passphrase?: boolean;
  unlocked?: boolean;
  keyring_unlocked?: boolean;
  last_probe?: { ok: boolean; output?: string } | null;
};

export type Health = {
  ok: boolean;
  service?: string;
  projects?: number;
  ssh?: SshStatus;
};

export type FileFreshness = {
  present: boolean;
  mtime_utc?: string | null;
  size_bytes?: number | null;
  days?: number;
  newest_day?: string | null;
};

export type TelemetryRun = {
  status?: string;
  reason?: string;
  mode?: string;
  rc?: number | null;
  duration_s?: number | null;
  started_utc?: string;
  finished_utc?: string;
  output?: string;
};

export type Telemetry = {
  source: { configured: boolean; value?: string; origin?: string };
  running: boolean;
  in_flight?: TelemetryRun | null;
  last_run?: TelemetryRun | null;
  last_success?: TelemetryRun | null;
  schedule: {
    enabled: boolean;
    interval_minutes: number;
    next_run_utc?: string | null;
    thread_alive?: boolean;
    min_interval_minutes?: number;
    max_interval_minutes?: number;
    inactivity_timeout_s?: number;
    session?: string;
    script?: string;
    scripts?: string[];
  };
  stores: {
    summaries_db: FileFreshness;
    snapshot_csv: FileFreshness;
    telemetry: FileFreshness;
  };
  ssh: SshStatus;
  rollup: { last_rollup_utc?: string | null; current?: boolean };
  history: TelemetryRun[];
};

/** The answer every `run.sh` route gives back. */
export type CommandResult = {
  ok: boolean;
  output?: string;
  error?: string;
  rc?: number;
};
