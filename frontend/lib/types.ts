export type Engine = "image" | "video";
export type Mode = "t2i" | "edit" | "t2v" | "i2v";
export type Status = "queued" | "provisioning" | "running" | "uploading" | "succeeded" | "failed" | "canceled";

export interface Generation {
  id: string;
  engine: Engine;
  mode: Mode;
  status: Status;
  progress: number;
  prompt: string;
  negative_prompt?: string;
  params: Record<string, number | string | boolean>;
  reference_paths: string[];
  credits_charged: number;
  error: string | null;
  output_paths: string[];
  created_at: string;
  started_at?: string | null;
  finished_at: string | null;
  gpu_type?: string | null;
}

export interface EngineCfg {
  resolution?: { min: number; max: number; default: number; step: number };
  resolutions?: [number, number][];
  steps: { min: number; max: number; default: number };
  cfg: { min: number; max: number; default: number };
  duration_s?: { min: number; max: number; default: number; step: number };
  default_resolution?: [number, number];
  max_reference_images?: number;
  gpu?: string;
}

export interface Pricing {
  base_credits: number;
  per_megapixel: number;
  per_ref_image: number;
  per_video_second: number;
}

export interface StudioConfig {
  site_name: string;
  maintenance_mode: boolean;
  default_negative_prompts: { image: string; video: string };
  engines: Record<Engine, EngineCfg>;
  pricing: Record<Engine, Pricing>;
}

export interface Transaction {
  id: string;
  delta: number;
  balance_after: number;
  kind: string;
  note: string | null;
  created_at: string;
}

/* ------------------------------------------------------------------ admin */

export interface Me {
  id: string;
  email: string;
  role: "user" | "admin";
}

export interface AdminOverview {
  users: number;
  suspended_users: number;
  generations_total: number;
  generations_active: number;
  generations_today: number;
  succeeded_today: number;
  failed_today: number;
  credits_in_circulation: number;
  maintenance_mode: boolean;
  site_name: string;
  last_deploy: DeployRun | null;
}

export interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  role: "user" | "admin";
  status: "active" | "suspended";
  created_at: string;
  balance: number;
  generations: number;
  credits_spent: number;
}

export interface AppSettings {
  site_name: string;
  signup_grant_credits: number;
  maintenance_mode: boolean;
  max_concurrent_jobs_per_user: number;
  daily_job_cap: number;
  default_negative_prompt_image: string;
  default_negative_prompt_video: string;
  updated_at: string;
}

export interface PricingRule {
  id: string;
  engine: Engine;
  base_credits: number;
  credits_per_megapixel: number;
  credits_per_ref_image: number;
  credits_per_video_second: number | null;
  active: boolean;
}

export interface EngineConfigRow {
  engine: Engine;
  enabled: boolean;
  params: Record<string, unknown>;
}

export interface AdminSettings {
  app: AppSettings;
  pricing: PricingRule[];
  engines: EngineConfigRow[];
}

export interface ModalSettings {
  image_gpu: string;
  video_gpu: string;
  image_max_containers: number;
  video_max_containers: number;
  image_min_containers: number;
  video_min_containers: number;
  scaledown_window_s: number;
  max_inputs: number;
  overhead_factor: number;
  comfyui_version: string;
  image_endpoint: string;
  video_endpoint: string;
  pending_deploy: { fields: string[]; at: string } | null;
  updated_at: string;
}

export interface DeployRun {
  id: string;
  trigger_reason: string;
  status: "running" | "succeeded" | "failed";
  started_at: string;
  finished_at: string | null;
  triggered_by?: string | null;
  log?: string;
  config_snapshot?: Record<string, unknown>;
}

export interface AuditEntry {
  id: number;
  action: string;
  target: string;
  payload: Record<string, unknown>;
  created_at: string;
  admin_email: string | null;
}
