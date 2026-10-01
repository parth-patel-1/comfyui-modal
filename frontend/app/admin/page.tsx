"use client";

import { useEffect, useState } from "react";
import { adminApi } from "@/lib/api";
import type { AdminOverview } from "@/lib/types";
import { Badge, Card, Spinner } from "@/components/ui";

function Stat({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
  return (
    <Card className="p-5">
      <p className="text-xs uppercase tracking-wide text-muted">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tracking-tight ${tone ?? ""}`}>{value}</p>
    </Card>
  );
}

export default function AdminOverviewPage() {
  const [data, setData] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    adminApi.overview().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="text-sm text-danger">{error}</p>;
  if (!data)
    return (
      <div className="grid place-items-center py-20">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    );

  return (
    <div className="space-y-6">
      {data.maintenance_mode && (
        <Card className="border-warning/40 bg-warning/5 p-4 text-sm text-warning">
          Maintenance mode is ON — new generations are blocked for all users.
        </Card>
      )}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <Stat label="Users" value={data.users} />
        <Stat label="Suspended" value={data.suspended_users} tone={data.suspended_users ? "text-warning" : ""} />
        <Stat label="Active jobs" value={data.generations_active} />
        <Stat label="Credits in circulation" value={data.credits_in_circulation} />
        <Stat label="Generations total" value={data.generations_total} />
        <Stat label="Generations today" value={data.generations_today} />
        <Stat label="Succeeded today" value={data.succeeded_today} tone="text-success" />
        <Stat label="Failed today" value={data.failed_today} tone={data.failed_today ? "text-danger" : ""} />
      </div>

      <Card className="overflow-hidden">
        <div className="border-b border-line px-4 py-3 text-sm font-medium">Last deploy</div>
        {data.last_deploy ? (
          <div className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
            <Badge
              tone={
                data.last_deploy.status === "succeeded"
                  ? "success"
                  : data.last_deploy.status === "failed"
                    ? "danger"
                    : "info"
              }
            >
              {data.last_deploy.status}
            </Badge>
            <span className="text-muted">{data.last_deploy.trigger_reason}</span>
            <span className="ml-auto text-[11px] text-faint">
              {new Date(data.last_deploy.started_at).toLocaleString()}
            </span>
          </div>
        ) : (
          <p className="px-4 py-6 text-center text-sm text-muted">No deploys recorded yet.</p>
        )}
      </Card>
    </div>
  );
}