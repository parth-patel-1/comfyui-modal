"use client";

import { useCallback, useEffect, useState } from "react";
import { adminApi } from "@/lib/api";
import type { DeployRun, ModalSettings } from "@/lib/types";
import { Badge, Button, Card, ErrorText, Field, Input, Spinner } from "@/components/ui";

export default function AdminEnginesPage() {
  const [settings, setSettings] = useState<ModalSettings | null>(null);
  const [rates, setRates] = useState<Record<string, number>>({});
  const [deploys, setDeploys] = useState<DeployRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [redeploy, setRedeploy] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await adminApi.modal();
      setSettings(d.settings);
      setRates(d.gpu_rates);
      setDeploys(d.deploys);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load");
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(() => {
      // refresh while a deploy is in flight
      setDeploys((prev) => {
        if (prev.some((d) => d.status === "running")) load();
        return prev;
      });
    }, 4000);
    return () => clearInterval(t);
  }, [load]);

  if (error && !settings) return <ErrorText>{error}</ErrorText>;
  if (!settings)
    return (
      <div className="grid place-items-center py-20">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    );

  const gpuOptions = Object.keys(rates);
  if (!gpuOptions.includes(settings.image_gpu)) gpuOptions.push(settings.image_gpu);
  if (!gpuOptions.includes(settings.video_gpu)) gpuOptions.push(settings.video_gpu);

  function flash(msg: string) {
    setSaved(msg);
    setError(null);
    setTimeout(() => setSaved(null), 3000);
  }

  async function save() {
    if (!settings) return;
    setBusy(true);
    setError(null);
    try {
      const r = await adminApi.updateModal({
        image_gpu: settings.image_gpu,
        video_gpu: settings.video_gpu,
        image_max_containers: settings.image_max_containers,
        video_max_containers: settings.video_max_containers,
        image_min_containers: settings.image_min_containers,
        video_min_containers: settings.video_min_containers,
        scaledown_window_s: settings.scaledown_window_s,
        max_inputs: settings.max_inputs,
        overhead_factor: settings.overhead_factor,
        comfyui_version: settings.comfyui_version,
      });
      setRedeploy(r.redeploy_recommended);
      flash("Modal settings saved." + (r.redeploy_recommended ? " Redeploy to apply." : ""));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  async function deploy() {
    setBusy(true);
    setError(null);
    try {
      await adminApi.triggerDeploy("image,video");
      setRedeploy(false);
      flash("Deploy started — this runs in the background and can take a few minutes.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "deploy trigger failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      {saved && <p className="text-xs text-success">{saved}</p>}
      <ErrorText>{error}</ErrorText>

      {settings.pending_deploy && (
        <Card className="border-warning/40 bg-warning/5 p-4 text-sm text-warning">
          Un-deployed changes pending: {settings.pending_deploy.fields.join(", ")}
        </Card>
      )}

      <Card className="space-y-4 p-6">
        <h2 className="text-sm font-medium">Engine infrastructure</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label={`Image GPU ($${rates[settings.image_gpu] ?? "?"}/hr)`}>
            <select
              className="gs-focus h-10 w-full rounded-lg bg-surface-2 border border-line px-3 text-sm text-fg focus:border-accent-line"
              value={settings.image_gpu}
              onChange={(e) => setSettings({ ...settings, image_gpu: e.target.value })}
            >
              {gpuOptions.map((g) => (
                <option key={g} value={g}>{g} — ${rates[g] ?? "?"}/hr</option>
              ))}
            </select>
          </Field>
          <Field label={`Video GPU ($${rates[settings.video_gpu] ?? "?"}/hr)`}>
            <select
              className="gs-focus h-10 w-full rounded-lg bg-surface-2 border border-line px-3 text-sm text-fg focus:border-accent-line"
              value={settings.video_gpu}
              onChange={(e) => setSettings({ ...settings, video_gpu: e.target.value })}
            >
              {gpuOptions.map((g) => (
                <option key={g} value={g}>{g} — ${rates[g] ?? "?"}/hr</option>
              ))}
            </select>
          </Field>
          <Field label="Image max containers">
            <Input type="number" min={1} max={20} value={settings.image_max_containers}
              onChange={(e) => setSettings({ ...settings, image_max_containers: Number(e.target.value) })} />
          </Field>
          <Field label="Video max containers">
            <Input type="number" min={1} max={20} value={settings.video_max_containers}
              onChange={(e) => setSettings({ ...settings, video_max_containers: Number(e.target.value) })} />
          </Field>
          <Field label="Image min containers" hint="Keep-warm containers">
            <Input type="number" min={0} value={settings.image_min_containers}
              onChange={(e) => setSettings({ ...settings, image_min_containers: Number(e.target.value) })} />
          </Field>
          <Field label="Video min containers" hint="Keep-warm containers">
            <Input type="number" min={0} value={settings.video_min_containers}
              onChange={(e) => setSettings({ ...settings, video_min_containers: Number(e.target.value) })} />
          </Field>
          <Field label="Scaledown window (s)">
            <Input type="number" min={10} max={7200} value={settings.scaledown_window_s}
              onChange={(e) => setSettings({ ...settings, scaledown_window_s: Number(e.target.value) })} />
          </Field>
          <Field label="ComfyUI version">
            <Input value={settings.comfyui_version}
              onChange={(e) => setSettings({ ...settings, comfyui_version: e.target.value })} />
          </Field>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-faint">
            Endpoints: {settings.image_endpoint || "not deployed"} · {settings.video_endpoint || "not deployed"}
          </span>
          <Button variant="outline" onClick={save} disabled={busy} className="ml-auto">Save</Button>
          <Button onClick={deploy} disabled={busy}>Deploy engines</Button>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <div className="border-b border-line px-4 py-3 text-sm font-medium">Deploy history</div>
        {deploys.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-muted">No deploys yet.</p>
        ) : (
          <ul className="divide-y divide-[var(--line)]">
            {deploys.map((d) => (
              <li key={d.id} className="flex items-center gap-3 px-4 py-3 text-sm">
                <Badge tone={d.status === "succeeded" ? "success" : d.status === "failed" ? "danger" : "info"}>
                  {d.status}
                </Badge>
                <span className="text-muted">{d.trigger_reason}</span>
                {d.triggered_by && <span className="text-xs text-faint">by {d.triggered_by}</span>}
                <span className="ml-auto whitespace-nowrap text-[11px] text-faint">
                  {new Date(d.started_at).toLocaleString()}
                  {d.finished_at
                    ? ` → ${new Date(d.finished_at).toLocaleTimeString()}`
                    : " — running…"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}