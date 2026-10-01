"use client";

import { supabase } from "./supabase";
import type {
  AdminOverview,
  AdminSettings,
  AdminUser,
  AppSettings,
  AuditEntry,
  DeployRun,
  Generation,
  Me,
  ModalSettings,
  PricingRule,
  PromptTemplate,
  SpendingReport,
  StudioConfig,
  TemplateBody,
} from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "/backend";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  const resp = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  if (!resp.ok) {
    let detail = `request failed (${resp.status})`;
    try {
      const body = await resp.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* empty body */
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  studioConfig: () => request<StudioConfig>("/api/config/studio"),
  estimate: (q: string) => request<{ credits: number }>(`/api/config/estimate?${q}`),
  wallet: () => request<{ balance: number }>("/api/wallet"),
  createGeneration: (body: {
    engine: string;
    mode: string;
    prompt: string;
    negative_prompt: string;
    params: Record<string, unknown>;
    reference_paths: string[];
  }) =>
    request<Generation>("/api/generations", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listGenerations: (limit = 50) =>
    request<Generation[]>(`/api/generations?limit=${limit}`),
  getGeneration: (id: string) => request<Generation>(`/api/generations/${id}`),
  cancelGeneration: (id: string) =>
    request<{ status: string }>(`/api/generations/${id}/cancel`, {
      method: "POST",
    }),
  uploadTicket: (filename: string) =>
    request<{ bucket: string; path: string; max_bytes: number }>(
      `/api/uploads/ticket?filename=${encodeURIComponent(filename)}`,
      { method: "POST" },
    ),
  me: () => request<Me>("/api/me"),
  templates: () => request<PromptTemplate[]>("/api/templates"),
  template: (id: string) =>
    request<PromptTemplate[]>(`/api/templates`).then(
      (list) => list.find((t) => t.id === id) ?? null,
    ),
  /** URL of the template's example image (proxied by the backend). */
  templateImageUrl: (id: string) => `${API_URL}/api/templates/${id}/image`,
};

export const adminApi = {
  overview: () => request<AdminOverview>("/api/admin/overview"),
  users: (q = "", limit = 50, offset = 0) =>
    request<AdminUser[]>(
      `/api/admin/users?q=${encodeURIComponent(q)}&limit=${limit}&offset=${offset}`,
    ),
  createUser: (
    body: {
      email: string;
      password: string;
      display_name?: string;
      role?: "user" | "admin";
      grant_credits?: number;
    },
  ) =>
    request<{ id: string; email: string; role: "user" | "admin"; status: string; balance: number | null }>(
      "/api/admin/users",
      { method: "POST", body: JSON.stringify(body) },
    ),
  adjustCredits: (id: string, delta: number, note: string) =>
    request<{ balance: number }>(`/api/admin/users/${id}/credits`, {
      method: "POST",
      body: JSON.stringify({ delta, note }),
    }),
  setUserStatus: (id: string, status: "active" | "suspended") =>
    request<{ status: string }>(`/api/admin/users/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
  settings: () => request<AdminSettings>("/api/admin/settings"),
  updateSettings: (patch: Partial<AppSettings>) =>
    request<{ site_name: string; maintenance_mode: boolean }>(
      "/api/admin/settings",
      { method: "PUT", body: JSON.stringify(patch) },
    ),
  updatePricing: (engine: string, patch: Partial<PricingRule>) =>
    request<{ engine: string }>(`/api/admin/pricing/${engine}`, {
      method: "PUT",
      body: JSON.stringify(patch),
    }),
  toggleEngine: (engine: string, enabled: boolean) =>
    request<{ engine: string; enabled: boolean }>(
      `/api/admin/engines/${engine}/enabled?enabled=${enabled}`,
      { method: "PUT" },
    ),
  modal: () =>
    request<{ settings: ModalSettings; gpu_rates: Record<string, number>; deploys: DeployRun[] }>(
      "/api/admin/modal",
    ),
  updateModal: (patch: Partial<ModalSettings>) =>
    request<{ image_gpu: string; video_gpu: string; redeploy_recommended: boolean }>(
      "/api/admin/modal",
      { method: "PUT", body: JSON.stringify(patch) },
    ),
  triggerDeploy: (engines = "image,video") =>
    request<{ id: string; engines: string[] }>(
      `/api/admin/deploy?engines=${encodeURIComponent(engines)}`,
      { method: "POST" },
    ),
  deploys: (limit = 20) =>
    request<DeployRun[]>(`/api/admin/deploy?limit=${limit}`),
  deploy: (id: string) => request<DeployRun>(`/api/admin/deploy/${id}`),
  audit: (limit = 50, offset = 0) =>
    request<AuditEntry[]>(`/api/admin/audit?limit=${limit}&offset=${offset}`),
  spending: (days = 30) =>
    request<SpendingReport>(`/api/admin/spending?days=${days}`),
  templates: () => request<PromptTemplate[]>("/api/admin/templates"),
  createTemplate: (body: TemplateBody) =>
    request<PromptTemplate>("/api/admin/templates", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateTemplate: (id: string, body: TemplateBody) =>
    request<PromptTemplate>(`/api/admin/templates/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteTemplate: (id: string) =>
    request<{ deleted: string }>(`/api/admin/templates/${id}`, {
      method: "DELETE",
    }),
};

/** Upload a reference image straight to Storage with the user's own JWT. */
export async function uploadReference(file: File): Promise<string> {
  if (file.size > 25 * 1024 * 1024)
    throw new ApiError(413, "reference image must be under 25 MB");
  const ticket = await api.uploadTicket(file.name);
  const { error } = await supabase.storage
    .from(ticket.bucket)
    .upload(ticket.path, file, { upsert: false });
  if (error) throw new ApiError(400, error.message);
  return ticket.path;
}

/** Short-lived signed URL for a private storage object. */
export async function signedUrl(
  bucket: string,
  path: string,
): Promise<string | null> {
  const { data } = await supabase.storage
    .from(bucket)
    .createSignedUrl(path, 60 * 60);
  return data?.signedUrl ?? null;
}
