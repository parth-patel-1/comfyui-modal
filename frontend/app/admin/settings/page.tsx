"use client";

import { useEffect, useState } from "react";
import { adminApi } from "@/lib/api";
import type { AdminSettings, AppSettings, PricingRule } from "@/lib/types";
import { Badge, Button, Card, ErrorText, Field, Input, Spinner } from "@/components/ui";

export default function AdminSettingsPage() {
  const [data, setData] = useState<AdminSettings | null>(null);
  const [app, setApp] = useState<AppSettings | null>(null);
  const [pricing, setPricing] = useState<Record<string, Partial<PricingRule>>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    adminApi
      .settings()
      .then((d) => {
        setData(d);
        setApp(d.app);
      })
      .catch((e) => setError(e.message));
  }, []);

  if (error && !data) return <ErrorText>{error}</ErrorText>;
  if (!data || !app)
    return (
      <div className="grid place-items-center py-20">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    );

  function flash(msg: string) {
    setSaved(msg);
    setError(null);
    setTimeout(() => setSaved(null), 3000);
  }

  async function saveApp() {
    if (!app) return;
    setBusy(true);
    setError(null);
    try {
      await adminApi.updateSettings({
        site_name: app.site_name,
        signup_grant_credits: app.signup_grant_credits,
        maintenance_mode: app.maintenance_mode,
        max_concurrent_jobs_per_user: app.max_concurrent_jobs_per_user,
        daily_job_cap: app.daily_job_cap,
        default_negative_prompt_image: app.default_negative_prompt_image,
        default_negative_prompt_video: app.default_negative_prompt_video,
      });
      flash("Site settings saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  async function savePricing(engine: string) {
    const patch = pricing[engine];
    if (!patch || Object.keys(patch).length === 0) return;
    setBusy(true);
    setError(null);
    try {
      await adminApi.updatePricing(engine, patch);
      setPricing((p) => ({ ...p, [engine]: {} }));
      const d = await adminApi.settings();
      setData(d);
      flash(`${engine} pricing saved.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  async function toggleEngine(engine: string, enabled: boolean) {
    setBusy(true);
    setError(null);
    try {
      await adminApi.toggleEngine(engine, enabled);
      const d = await adminApi.settings();
      setData(d);
      flash(`${engine} engine ${enabled ? "enabled" : "disabled"}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "toggle failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      {saved && <p className="text-xs text-success">{saved}</p>}
      <ErrorText>{error}</ErrorText>

      <Card className="space-y-4 p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium">Site settings</h2>
          <Badge tone={app.maintenance_mode ? "warning" : "success"}>
            {app.maintenance_mode ? "maintenance ON" : "live"}
          </Badge>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Site name">
            <Input value={app.site_name} onChange={(e) => setApp({ ...app, site_name: e.target.value })} />
          </Field>
          <Field label="Signup grant (credits)" hint="Given to every new user">
            <Input
              type="number" min={0}
              value={app.signup_grant_credits}
              onChange={(e) => setApp({ ...app, signup_grant_credits: Number(e.target.value) })}
            />
          </Field>
          <Field label="Max concurrent jobs / user">
            <Input
              type="number" min={1}
              value={app.max_concurrent_jobs_per_user}
              onChange={(e) => setApp({ ...app, max_concurrent_jobs_per_user: Number(e.target.value) })}
            />
          </Field>
          <Field label="Daily job cap">
            <Input
              type="number" min={1}
              value={app.daily_job_cap}
              onChange={(e) => setApp({ ...app, daily_job_cap: Number(e.target.value) })}
            />
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Default negative prompt — image">
            <textarea
              className="gs-focus w-full resize-none rounded-lg bg-surface-2 border border-line px-3 py-2 text-sm text-fg placeholder:text-faint focus:border-accent-line"
              rows={2}
              value={app.default_negative_prompt_image}
              onChange={(e) => setApp({ ...app, default_negative_prompt_image: e.target.value })}
            />
          </Field>
          <Field label="Default negative prompt — video">
            <textarea
              className="gs-focus w-full resize-none rounded-lg bg-surface-2 border border-line px-3 py-2 text-sm text-fg placeholder:text-faint focus:border-accent-line"
              rows={2}
              value={app.default_negative_prompt_video}
              onChange={(e) => setApp({ ...app, default_negative_prompt_video: e.target.value })}
            />
          </Field>
        </div>
        <div className="flex items-center gap-4">
          <label className="gs-focus flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={app.maintenance_mode}
              onChange={(e) => setApp({ ...app, maintenance_mode: e.target.checked })}
              className="h-4 w-4 accent-[var(--accent)]"
            />
            Maintenance mode (blocks new generations)
          </label>
          <Button onClick={saveApp} disabled={busy} className="ml-auto">Save site settings</Button>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <div className="border-b border-line px-4 py-3 text-sm font-medium">Pricing rules</div>
        <div className="divide-y divide-[var(--line)]">
          {data.pricing.map((p) => {
            type PriceKey =
              | "base_credits"
              | "credits_per_megapixel"
              | "credits_per_ref_image"
              | "credits_per_video_second";
            const patch = pricing[p.engine] ?? {};
            const val = (k: PriceKey): number =>
              (patch[k] as number | undefined) ?? (p[k] as number | null) ?? 0;
            const set = (k: PriceKey, v: number) =>
              setPricing((prev) => ({ ...prev, [p.engine]: { ...prev[p.engine], [k]: v } }));
            return (
              <div key={p.id} className="flex flex-wrap items-end gap-4 px-4 py-4">
                <div className="w-24 pb-2">
                  <Badge tone={p.engine === "image" ? "info" : "accent"}>{p.engine}</Badge>
                  {!p.active && <Badge tone="neutral">inactive</Badge>}
                </div>
                <Field label="Base credits">
                  <Input type="number" min={0} className="w-24" value={val("base_credits")}
                    onChange={(e) => set("base_credits", Number(e.target.value))} />
                </Field>
                <Field label="Per megapixel">
                  <Input type="number" min={0} step="0.1" className="w-24" value={val("credits_per_megapixel")}
                    onChange={(e) => set("credits_per_megapixel", Number(e.target.value))} />
                </Field>
                <Field label="Per ref image">
                  <Input type="number" min={0} className="w-24" value={val("credits_per_ref_image")}
                    onChange={(e) => set("credits_per_ref_image", Number(e.target.value))} />
                </Field>
                {p.engine === "video" && (
                  <Field label="Per video second">
                    <Input type="number" min={0} step="0.1" className="w-24"
                      value={val("credits_per_video_second")}
                      onChange={(e) => set("credits_per_video_second", Number(e.target.value))} />
                  </Field>
                )}
                <Button variant="outline" className="ml-auto" disabled={busy || Object.keys(patch).length === 0}
                  onClick={() => savePricing(p.engine)}>
                  Save
                </Button>
              </div>
            );
          })}
        </div>
      </Card>

      <Card className="overflow-hidden">
        <div className="border-b border-line px-4 py-3 text-sm font-medium">Engines</div>
        <div className="divide-y divide-[var(--line)]">
          {data.engines.map((e) => (
            <div key={e.engine} className="flex items-center gap-3 px-4 py-3 text-sm">
              <span className="font-medium capitalize">{e.engine}</span>
              <Badge tone={e.enabled ? "success" : "danger"}>{e.enabled ? "enabled" : "disabled"}</Badge>
              <Button
                variant={e.enabled ? "danger" : "primary"}
                className="ml-auto h-8 px-3 text-xs"
                disabled={busy}
                onClick={() => toggleEngine(e.engine, !e.enabled)}
              >
                {e.enabled ? "Disable" : "Enable"}
              </Button>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}