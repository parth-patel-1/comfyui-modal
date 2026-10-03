"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Engine, Generation, Mode, StudioConfig } from "@/lib/types";
import Composer, { type SubmitPayload } from "@/components/studio/Composer";
import { ResultCard } from "@/components/studio/Thread";
import { Badge, Button, ErrorText, Spinner } from "@/components/ui";

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);

/** One job the user has lined up but not submitted yet. */
interface PendingItem {
  key: string;
  payload: SubmitPayload;
  credits: number | null;
  error: string | null;
}

interface Turn {
  prompt: string;
  mode: Mode;
  refs: string[];
  gen: Generation;
}

function estimateQuery(p: SubmitPayload): string {
  return new URLSearchParams({
    engine: p.engine,
    width: String(p.params.width ?? 1024),
    height: String(p.params.height ?? 1024),
    duration_s: String(p.params.duration_s ?? 5),
    ref_count: String(p.reference_paths.length),
  }).toString();
}

export default function QueuePage() {
  return (
    <Suspense
      fallback={<div className="grid place-items-center py-32"><Spinner className="h-6 w-6 text-accent" /></div>}
    >
      <QueueInner />
    </Suspense>
  );
}

function QueueInner() {
  const [cfg, setCfg] = useState<StudioConfig | null>(null);
  const [cfgError, setCfgError] = useState<string | null>(null);
  const [engine, setEngine] = useState<Engine>("image");
  const [mode, setMode] = useState<Mode>("t2i");
  const [pending, setPending] = useState<PendingItem[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [estimate, setEstimate] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const activeIdsRef = useRef<Set<string>>(new Set());
  const tickRef = useRef(false);
  const keyRef = useRef(0);

  useEffect(() => {
    api.studioConfig().then(setCfg).catch((e) => setCfgError(e.message));
  }, []);

  // live credit estimate for the composer (debounced) â€” same as studio
  useEffect(() => {
    if (!cfg) return;
    const t = setTimeout(() => {
      const p = cfg.engines[engine];
      const q = new URLSearchParams({
        engine,
        width: String(engine === "image" ? p.resolution?.default ?? 1024 : p.resolutions?.[0]?.[0] ?? 864),
        height: String(engine === "image" ? p.resolution?.default ?? 1024 : p.resolutions?.[0]?.[1] ?? 480),
        duration_s: String(p.duration_s?.default ?? 5),
        ref_count: String(mode === "edit" || mode === "i2v" ? 1 : 0),
      });
      api.estimate(q.toString()).then((r) => setEstimate(r.credits)).catch(() => setEstimate(null));
    }, 300);
    return () => clearTimeout(t);
  }, [cfg, engine, mode]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  const pollJob = useCallback((...ids: string[]) => {
    ids.forEach((id) => activeIdsRef.current.add(id));
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      if (tickRef.current) return;
      tickRef.current = true;
      try {
        for (const id of [...activeIdsRef.current]) {
          try {
            const gen = await api.getGeneration(id);
            setTurns((prev) => prev.map((t) => (t.gen.id === id ? { ...t, gen } : t)));
            if (TERMINAL.has(gen.status)) {
              activeIdsRef.current.delete(id);
              api.wallet().catch(() => {});
            }
          } catch { /* transient â€” keep polling */ }
        }
      } finally {
        tickRef.current = false;
      }
      if (activeIdsRef.current.size === 0) stopPolling();
    }, 2000);
  }, [stopPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  // Show generations that are already in flight (submitted earlier from this
  // page, or after a refresh) â€” the queue keeps working while the user is away.
  useEffect(() => {
    let cancelled = false;
    api.listGenerations(50)
      .then((gens) => {
        if (cancelled) return;
        const active = gens.filter((g) => !TERMINAL.has(g.status)).reverse();
        if (active.length === 0) return;
        setTurns(active.map((g) => ({ prompt: g.prompt, mode: g.mode, refs: g.reference_paths, gen: g })));
        pollJob(...active.map((g) => g.id));
      })
      .catch(() => { /* non-fatal */ });
    return () => { cancelled = true; };
  }, [pollJob]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [turns.length]);

  /** Composer "Add to queue": validate + price now, keep locally. */
  async function addToQueue(p: SubmitPayload): Promise<string | null> {
    let credits: number | null = null;
    try {
      credits = (await api.estimate(estimateQuery(p))).credits;
    } catch { /* pricing estimate is best-effort */ }
    keyRef.current += 1;
    setPending((prev) => [...prev, { key: String(keyRef.current), payload: p, credits, error: null }]);
    return null;
  }

  async function startQueue() {
    if (pending.length === 0 || starting) return;
    setStarting(true);
    setStartError(null);
    const failed: PendingItem[] = [];
    for (const item of pending) {
      try {
        const gen = await api.createGeneration({
          ...item.payload,
          params: item.payload.params as Record<string, unknown>,
        });
        setTurns((prev) => [...prev, {
          prompt: item.payload.prompt,
          mode: item.payload.mode,
          refs: item.payload.reference_paths,
          gen,
        }]);
        pollJob(gen.id);
      } catch (e) {
        failed.push({ ...item, error: e instanceof Error ? e.message : "could not queue job" });
      }
    }
    setPending(failed); // keep only the items that failed (with their error)
    setStarting(false);
    if (failed.length > 0) {
      setStartError(
        `${pending.length - failed.length} job(s) queued; ${failed.length} could not be queued â€” fix or remove them below.`);
    }
  }

  async function cancel(id: string) {
    const ok = window.confirm("Cancel this generation? Credits are refunded.");
    if (!ok) return;
    try { await api.cancelGeneration(id); } catch { /* already terminal */ }
  }

  if (cfgError) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-24 text-center space-y-3">
        <h1 className="text-lg font-semibold">Queue unavailable</h1>
        <p className="text-sm text-muted">{cfgError}</p>
      </div>
    );
  }
  if (!cfg) {
    return <div className="grid place-items-center py-32"><Spinner className="h-6 w-6 text-accent" /></div>;
  }
  if (cfg.maintenance_mode) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-24 text-center space-y-3">
        <h1 className="text-lg font-semibold">Scheduled maintenance</h1>
        <p className="text-sm text-muted">Generation is paused right now â€” please check back soon.</p>
      </div>
    );
  }

  const totalCredits = pending.reduce((s, p) => s + (p.credits ?? 0), 0);

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] flex-col">
      <div className="mx-auto w-full max-w-3xl flex-1 space-y-5 px-4 py-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Generation <span className="gs-gradient-text">queue</span></h1>
          <p className="mt-1 text-sm text-muted">
            Line up as many jobs as you want, then hit Start â€” the app runs them in the
            background (several in parallel) while you do other things. Results land in your gallery.
          </p>
        </div>

        {pending.length > 0 && (
          <div className="space-y-2">
            {pending.map((item) => (
              <div key={item.key}
                className="rounded-xl border border-line bg-surface p-3 flex items-start gap-3">
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="truncate text-sm text-fg" title={item.payload.prompt}>{item.payload.prompt}</p>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge>{item.payload.engine === "image" ? "Image" : "Video"} Â· {item.payload.mode}</Badge>
                    {item.payload.reference_paths.length > 0 && (
                      <Badge>{item.payload.reference_paths.length} ref{item.payload.reference_paths.length > 1 ? "s" : ""}</Badge>
                    )}
                    {item.credits !== null && <Badge tone="accent">~ {item.credits} credits</Badge>}
                  </div>
                  {item.error && <ErrorText>{item.error}</ErrorText>}
                </div>
                <Button variant="ghost" className="h-7 px-2 text-xs"
                  disabled={starting}
                  onClick={() => setPending((prev) => prev.filter((x) => x.key !== item.key))}>
                  Remove
                </Button>
              </div>
            ))}
            <div className="flex items-center gap-3">
              <Button onClick={startQueue} disabled={starting} className="h-9 px-4">
                {starting ? <Spinner /> : `Start queue (${pending.length})`}
              </Button>
              <span className="text-xs text-muted">
                {totalCredits > 0 ? `â‰ˆ ${totalCredits} credits total, charged as each job starts` : ""}
              </span>
            </div>
            {startError && <ErrorText>{startError}</ErrorText>}
          </div>
        )}

        {turns.length > 0 && (
          <div className="space-y-5">
            {turns.map((t) => (
              <ResultCard key={t.gen.id} gen={t.gen} onCancel={cancel} onRetry={null} />
            ))}
            <div ref={bottomRef} />
          </div>
        )}

        {pending.length === 0 && turns.length === 0 && (
          <div className="py-10 text-center text-sm text-muted">
            Nothing queued yet â€” add your first job with the composer below.
          </div>
        )}
      </div>
      <Composer
        cfg={cfg}
        engine={engine} setEngine={setEngine}
        mode={mode} setMode={setMode}
        estimate={estimate}
        submitLabel="Add to queue"
        onSubmit={addToQueue}
      />
    </div>
  );
}

