"use client";

import { useEffect, useState } from "react";
import { signedUrl } from "@/lib/api";
import type { Generation } from "@/lib/types";
import { Badge, Button, Spinner } from "@/components/ui";

const ACTIVE: string[] = ["queued", "provisioning", "running", "uploading"];

// Rough wall-clock targets per engine — must mirror EXPECTED_SECONDS in
// backend/app/worker/loop.py. Used to smooth the percentage between the
// coarse progress values the worker writes.
const EXPECTED_S: Record<string, number> = { image: 60, video: 300 };

const STATUS_LABEL: Record<string, string> = {
  queued: "Queued",
  provisioning: "Starting GPU",
  running: "Generating",
  uploading: "Saving results",
  succeeded: "Done",
  failed: "Failed",
  canceled: "Canceled",
};

function useSigned(paths: string[], bucket: string) {
  const [urls, setUrls] = useState<Record<string, string>>({});
  useEffect(() => {
    let active = true;
    paths.forEach((p) => {
      signedUrl(bucket, p).then((u) => {
        if (active && u) setUrls((prev) => ({ ...prev, [p]: u }));
      });
    });
    return () => { active = false; };
  }, [paths.join("|"), bucket]); // eslint-disable-line react-hooks/exhaustive-deps
  return urls;
}

function RefThumb({ path }: { path: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    signedUrl("references", path).then(setUrl);
  }, [path]);
  if (!url)
    return <div className="h-16 w-16 rounded-lg border border-line bg-surface-2 animate-pulse" />;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={url} alt="reference" className="h-16 w-16 rounded-lg border border-line object-cover" />;
}

function Media({ gen }: { gen: Generation }) {
  const urls = useSigned(gen.output_paths, "generations");
  if (!gen.output_paths.length) return null;
  return (
    <div className={`grid gap-2 ${gen.output_paths.length > 1 ? "sm:grid-cols-2" : ""}`}>
      {gen.output_paths.map((p) => {
        const url = urls[p];
        if (!url) return <div key={p} className="aspect-square rounded-lg bg-surface-2 animate-pulse" />;
        return gen.engine === "video" ? (
          <video key={p} src={url} controls playsInline className="w-full rounded-lg border border-line" />
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={p} src={url} alt={gen.prompt.slice(0, 80)} className="w-full rounded-lg border border-line" />
        );
      })}
    </div>
  );
}

/** Re-renders every second while `active` so the progress estimate can tick. */
function useClock(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

export function ResultCard({ gen, onCancel }: { gen: Generation; onCancel: (id: string) => void }) {
  const isActive = ACTIVE.includes(gen.status);
  const failed = gen.status === "failed";
  const canceled = gen.status === "canceled";
  const took = gen.finished_at
    ? Math.max(1, Math.round((+new Date(gen.finished_at) - +new Date(gen.created_at)) / 1000))
    : null;

  const now = useClock(isActive);
  const elapsedS = Math.max(
    0, Math.round((now - +new Date(gen.started_at ?? gen.created_at)) / 1000));

  // Estimated % from wall clock, blended with the server-reported progress:
  // never below what the backend knows, never above 95 (100 only on settle).
  const estimate = Math.min(95, Math.round((elapsedS / (EXPECTED_S[gen.engine] ?? 120)) * 100));
  const shown = isActive && gen.status !== "queued"
    ? Math.min(95, Math.max(gen.progress, estimate))
    : gen.progress;
  const indeterminate = gen.status === "queued" && gen.progress === 0;

  return (
    <div className="gs-fade-up max-w-[85%] rounded-xl border border-line bg-surface p-4 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <Badge tone={gen.status === "succeeded" ? "success" : failed ? "danger" : isActive ? "accent" : "neutral"}>
          {isActive && <Spinner className="h-3 w-3" />}
          {STATUS_LABEL[gen.status] ?? gen.status}
          {gen.status === "queued"
            ? ` · ${elapsedS}s`
            : isActive ? ` ${shown}%` : ""}
        </Badge>
        <Badge>{gen.engine === "image" ? "Image" : "Video"} · {gen.mode}</Badge>
        <Badge>{gen.credits_charged} credits</Badge>
        {gen.gpu_type ? <Badge>{gen.gpu_type}</Badge> : null}
        {isActive && (
          <Button variant="danger" className="ml-auto h-7 px-2.5 text-xs" onClick={() => onCancel(gen.id)}>
            Cancel
          </Button>
        )}
      </div>

      {isActive && (
        <div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
            <div
              className={`h-full rounded-full transition-all duration-700 ${indeterminate ? "gs-shimmer w-1/3" : "gs-gradient-btn"}`}
              style={!indeterminate ? { width: `${Math.max(6, shown)}%` } : undefined}
            />
          </div>
          <p className="mt-1.5 text-[11px] text-faint">{STATUS_LABEL[gen.status]}…</p>
        </div>
      )}

      {failed && (
        <p role="alert" className="text-xs text-danger bg-danger/10 border border-danger/25 rounded-lg px-3 py-2">
          {gen.error || "Generation failed"} — credits were refunded automatically.
        </p>
      )}
      {canceled && (
        <p className="text-xs text-warning bg-warning/10 border border-warning/25 rounded-lg px-3 py-2">
          Canceled — credits were refunded automatically.
        </p>
      )}

      <Media gen={gen} />

      {gen.status === "succeeded" && (
        <p className="text-[11px] text-faint font-mono">
          {took}s · job {gen.id.slice(0, 8)}
        </p>
      )}
    </div>
  );
}

export function PromptBubble({
  prompt,
  mode,
  refs,
}: {
  prompt: string;
  mode: string;
  refs: string[];
}) {
  return (
    <div className="gs-fade-up ml-auto max-w-[85%] space-y-2">
      {refs.length > 0 && (
        <div className="flex flex-wrap gap-2 justify-end">
          {refs.map((r) => <RefThumb key={r} path={r} />)}
        </div>
      )}
      <div className="rounded-xl rounded-br-sm bg-surface-2 border border-line px-4 py-3">
        <p className="whitespace-pre-wrap text-sm text-fg">{prompt}</p>
        <p className="mt-1 text-right text-[10px] uppercase tracking-wide text-faint">{mode}</p>
      </div>
    </div>
  );
}
