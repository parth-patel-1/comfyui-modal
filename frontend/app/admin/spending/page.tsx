"use client";

import { useCallback, useEffect, useState } from "react";
import { adminApi } from "@/lib/api";
import type { SpendingReport } from "@/lib/types";
import { Badge, Button, Card, ErrorText, Spinner } from "@/components/ui";

const RANGES = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
  { days: 0, label: "All time" },
];

const usd = (v: number) =>
  `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const usd4 = (v: number) =>
  `$${v.toLocaleString("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`;
const hrs = (s: number) => `${(s / 3600).toFixed(2)} h`;

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card className="p-5">
      <p className="text-xs uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight">{value}</p>
      {sub && <p className="mt-0.5 text-[11px] text-faint">{sub}</p>}
    </Card>
  );
}

export default function AdminSpendingPage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<SpendingReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (d: number) => {
    setError(null);
    try {
      setData(await adminApi.spending(d));
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load spending");
    }
  }, []);

  useEffect(() => {
    load(days);
  }, [days, load]);

  if (error) return <ErrorText>{error}</ErrorText>;
  if (!data)
    return (
      <div className="grid place-items-center py-20">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    );

  const t = data.totals;
  const maxDayCompute = Math.max(...data.by_day.map((d) => d.compute_usd), 0);
  const avgPerJob = t.jobs > 0 ? t.compute_usd / t.jobs : 0;
  const billedPerCredit =
    t.credits_charged > 0 ? t.billed_est_usd / t.credits_charged : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-1.5">
        {RANGES.map((r) => (
          <Button
            key={r.days}
            variant={days === r.days ? "primary" : "outline"}
            className="h-8 px-3 text-xs"
            onClick={() => setDays(r.days)}
          >
            {r.label}
          </Button>
        ))}
        <Button variant="ghost" className="ml-auto h-8 px-2 text-xs" onClick={() => load(days)}>
          Refresh
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <Stat label="Compute cost" value={usd(t.compute_usd)} sub="Modal GPU time, succeeded jobs" />
        <Stat
          label="Billed est."
          value={usd(t.billed_est_usd)}
          sub={`compute × overhead (${(t.billed_est_usd / (t.compute_usd || 1)).toFixed(2)})`}
        />
        <Stat label="GPU time" value={hrs(t.gpu_seconds)} sub={`${t.jobs} succeeded jobs`} />
        <Stat label="Avg per job" value={usd4(avgPerJob)} sub={`${t.failed_jobs} failed (no charge)`} />
        <Stat
          label="Credits charged"
          value={t.credits_charged.toLocaleString("en-US")}
          sub={billedPerCredit ? `${usd4(billedPerCredit)} compute per credit` : undefined}
        />
      </div>

      <Card className="overflow-hidden">
        <div className="border-b border-line px-4 py-3 text-sm font-medium">Spend by GPU type</div>
        {data.by_gpu.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-muted">No spending in this period.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs text-muted">
              <tr className="border-b border-line">
                <th className="px-4 py-2 text-left font-medium">GPU</th>
                <th className="px-4 py-2 text-right font-medium">Jobs</th>
                <th className="px-4 py-2 text-right font-medium">GPU time</th>
                <th className="px-4 py-2 text-right font-medium">Rate</th>
                <th className="px-4 py-2 text-right font-medium">Compute</th>
                <th className="px-4 py-2 text-right font-medium">Billed est.</th>
                <th className="px-4 py-2 text-right font-medium">Share</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--line)]">
              {data.by_gpu.map((g) => (
                <tr key={g.gpu}>
                  <td className="px-4 py-2.5 font-medium">{g.gpu}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-muted">{g.jobs}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-muted">{hrs(g.gpu_seconds)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-muted">
                    {g.hourly_usd ? `$${g.hourly_usd}/h` : "—"}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono">{usd(g.compute_usd)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-muted">{usd(g.billed_usd)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-muted">
                    {t.compute_usd > 0 ? `${((g.compute_usd / t.compute_usd) * 100).toFixed(1)}%` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="overflow-hidden">
          <div className="border-b border-line px-4 py-3 text-sm font-medium">Spend by engine</div>
          {data.by_engine.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-muted">No spending in this period.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 text-left font-medium">Engine</th>
                  <th className="px-4 py-2 text-right font-medium">Jobs</th>
                  <th className="px-4 py-2 text-right font-medium">GPU time</th>
                  <th className="px-4 py-2 text-right font-medium">Compute</th>
                  <th className="px-4 py-2 text-right font-medium">Billed est.</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--line)]">
                {data.by_engine.map((e) => (
                  <tr key={e.engine}>
                    <td className="px-4 py-2.5 font-medium capitalize">{e.engine}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-muted">{e.jobs}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-muted">{hrs(e.gpu_seconds)}</td>
                    <td className="px-4 py-2.5 text-right font-mono">{usd(e.compute_usd)}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-muted">{usd(e.billed_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card className="overflow-hidden">
          <div className="border-b border-line px-4 py-3 text-sm font-medium">Spend by day</div>
          {data.by_day.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-muted">No spending in this period.</p>
          ) : (
            <div className="max-h-80 overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-surface text-xs text-muted">
                  <tr className="border-b border-line">
                    <th className="px-4 py-2 text-left font-medium">Day</th>
                    <th className="px-4 py-2 text-right font-medium">Jobs</th>
                    <th className="px-4 py-2 text-right font-medium">Compute</th>
                    <th className="px-4 py-2 text-right font-medium">Billed est.</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--line)]">
                  {data.by_day.map((d) => (
                    <tr key={d.day}>
                      <td className="whitespace-nowrap px-4 py-2.5 text-muted">
                        {new Date(d.day).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-muted">{d.jobs}</td>
                      <td className="px-4 py-2.5 text-right">
                        <span className="font-mono">{usd(d.compute_usd)}</span>
                        {maxDayCompute > 0 && (
                          <span className="mt-1 block h-1 rounded bg-accent/30">
                            <span
                              className="block h-1 rounded bg-accent"
                              style={{ width: `${(d.compute_usd / maxDayCompute) * 100}%` }}
                            />
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-muted">{usd(d.billed_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <span className="text-sm font-medium">Spend by user</span>
          <Badge tone="info">top {data.by_user.length}</Badge>
        </div>
        {data.by_user.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-muted">No spending in this period.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 text-left font-medium">User</th>
                  <th className="px-4 py-2 text-right font-medium">Jobs</th>
                  <th className="px-4 py-2 text-right font-medium">GPU time</th>
                  <th className="px-4 py-2 text-right font-medium">Compute</th>
                  <th className="px-4 py-2 text-right font-medium">Billed est.</th>
                  <th className="px-4 py-2 text-right font-medium">Credits charged</th>
                  <th className="px-4 py-2 text-right font-medium">Share</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--line)]">
                {data.by_user.map((u) => (
                  <tr key={u.user_id}>
                    <td className="px-4 py-2.5">
                      <div className="font-medium">{u.display_name || u.email.split("@")[0]}</div>
                      <div className="text-xs text-faint">{u.email}</div>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-muted">{u.jobs}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-muted">{hrs(u.gpu_seconds)}</td>
                    <td className="px-4 py-2.5 text-right font-mono">{usd(u.compute_usd)}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-muted">{usd(u.billed_usd)}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-muted">{u.credits_charged}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-muted">
                      {t.compute_usd > 0 ? `${((u.compute_usd / t.compute_usd) * 100).toFixed(1)}%` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
