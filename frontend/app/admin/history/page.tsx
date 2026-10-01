"use client";

import { useEffect, useState } from "react";
import {
  adminApi,
  downloadGeneration,
  fetchGenerationBlob,
  generationFileName,
} from "@/lib/api";
import type { AdminHistoryRow } from "@/lib/types";
import { Badge, Button, Card, ErrorText, Input, Spinner } from "@/components/ui";

const STATUSES = ["", "succeeded", "failed", "canceled", "running", "queued"];

function fmt(d: string) {
  return new Date(d).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

/** Inline media preview — the generations bucket is private and admins can't
 *  mint signed URLs client-side, so bytes are proxied through the backend. */
function HistoryThumb({ row }: { row: AdminHistoryRow }) {
  const [url, setUrl] = useState<string | null>(null);
  const isVideo = row.engine === "video";

  useEffect(() => {
    if (!row.output_paths.length) return;
    let active = true;
    fetchGenerationBlob(row.id, 0)
      .then(({ blob }) => {
        if (active) setUrl(URL.createObjectURL(blob));
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [row.id, row.output_paths]); // eslint-disable-line react-hooks/exhaustive-deps

  const path = row.output_paths[0] ?? "";
  return (
    <div
      className="grid h-14 w-20 shrink-0 place-items-center overflow-hidden rounded-lg border border-line bg-surface-2"
      title={path ? `Server location: generations/${path}` : "no output"}
    >
      {!path ? (
        <span className="text-[10px] text-faint">—</span>
      ) : !url ? (
        <Spinner className="h-4 w-4 text-faint" />
      ) : isVideo ? (
        <video src={url} muted playsInline className="h-full w-full object-cover" />
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url} alt="" className="h-full w-full object-cover" />
      )}
    </div>
  );
}

function HistoryRow({ row }: { row: AdminHistoryRow }) {
  const [busy, setBusy] = useState(false);
  const isVideo = row.engine === "video";
  const ext = isVideo ? "mp4" : "png";

  return (
    <div className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center">
      <HistoryThumb row={row} />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">
            {row.display_name || row.email.split("@")[0]}
          </span>
          <span className="text-xs text-faint">{row.email}</span>
          <Badge tone={row.engine === "image" ? "accent" : "info"}>
            {isVideo ? "Video" : "Image"} · {row.mode}
          </Badge>
          <Badge tone={
            row.status === "succeeded" ? "success"
              : row.status === "failed" ? "danger"
                : row.status === "canceled" ? "warning" : "neutral"
          }>
            {row.status}
          </Badge>
          <span className="ml-auto text-xs text-faint">{fmt(row.created_at)}</span>
        </div>
        <p className="line-clamp-2 text-xs text-muted" title={row.prompt}>
          {row.prompt || <em className="text-faint">(empty prompt)</em>}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[11px] text-faint" title="Unique file ID — maps to the generations table and the storage path">
            {generationFileName(row.id, 0, ext)}
          </span>
          <span className="font-mono text-[11px] text-faint" title="Exact storage location of the output">
            {row.output_paths[0] ? `· generations/${row.output_paths[0]}` : ""}
          </span>
          {row.status === "failed" && row.error ? (
            <span className="text-[11px] text-danger">{row.error}</span>
          ) : null}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3 sm:flex-col sm:items-end sm:gap-1">
        <Badge tone="accent">{row.credits_charged} credits</Badge>
        {row.output_paths.length > 0 && (
          <Button
            variant="outline"
            className="h-8 px-2.5 text-xs"
            disabled={busy}
            title={`Downloads as ${generationFileName(row.id, 0, ext)}`}
            onClick={() => {
              setBusy(true);
              downloadGeneration(row.id, 0, ext).finally(() => setBusy(false));
            }}
          >
            {busy ? <Spinner className="h-3.5 w-3.5" /> : null} Download
          </Button>
        )}
      </div>
    </div>
  );
}

export default function AdminHistoryPage() {
  const [rows, setRows] = useState<AdminHistoryRow[] | null>(null);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function load(query = q, st = status) {
    try {
      setError(null);
      setRows(await adminApi.history(query, "", st, 100, 0));
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load history");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        Every generation across all users — who generated what, when, with which
        prompt, and how many credits it cost. Downloads use a unique file ID that
        maps back to the exact server location.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="Search by prompt or user email…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
          className="max-w-sm"
        />
        <select
          value={status}
          aria-label="Status filter"
          onChange={(e) => { setStatus(e.target.value); void load(q, e.target.value); }}
          className="gs-focus h-10 rounded-lg bg-surface-2 border border-line px-3 text-sm text-fg"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s === "" ? "All statuses" : s}</option>
          ))}
        </select>
        <Button variant="outline" onClick={() => load()}>Search</Button>
      </div>
      {error ? <ErrorText>{error}</ErrorText> : null}

      {!rows ? (
        <div className="grid place-items-center py-16"><Spinner className="h-6 w-6 text-accent" /></div>
      ) : (
        <Card className="divide-y divide-line">
          {rows.length === 0 && (
            <p className="px-4 py-10 text-center text-sm text-muted">No generations found.</p>
          )}
          {rows.map((r) => <HistoryRow key={r.id} row={r} />)}
        </Card>
      )}
    </div>
  );
}

