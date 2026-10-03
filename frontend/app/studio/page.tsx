"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import type { Engine, Generation, Mode, PromptTemplate, StudioConfig } from "@/lib/types";
import Composer, { type SubmitPayload } from "@/components/studio/Composer";
import { PromptBubble, ResultCard } from "@/components/studio/Thread";
import { Spinner } from "@/components/ui";

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);

interface Turn {
  prompt: string;
  mode: Mode;
  refs: string[];
  gen: Generation;
}

export default function StudioPage() {
  return (
    <Suspense
      fallback={<div className="grid place-items-center py-32"><Spinner className="h-6 w-6 text-accent" /></div>}
    >
      <StudioInner />
    </Suspense>
  );
}

function StudioInner() {
  const searchParams = useSearchParams();
  const templateId = searchParams.get("template");
  const [cfg, setCfg] = useState<StudioConfig | null>(null);
  const [cfgError, setCfgError] = useState<string | null>(null);
  const [engine, setEngine] = useState<Engine>("image");
  const [mode, setMode] = useState<Mode>("t2i");
  const [template, setTemplate] = useState<PromptTemplate | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [estimate, setEstimate] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const activeIdsRef = useRef<Set<string>>(new Set());
  const tickRef = useRef(false);

  useEffect(() => {
    api.studioConfig().then(setCfg).catch((e) => setCfgError(e.message));
  }, []);

  // "Use in Studio" from the Discover page (?template=<id>): fetch it once.
  useEffect(() => {
    if (!templateId) return;
    setTemplate(null);
    api
      .template(templateId)
      .then(setTemplate)
      .catch(() => setTemplate(null)); // bad/stale link — studio stays usable
  }, [templateId]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [turns.length]);

  // live credit estimate (debounced)
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

  // One interval polls every in-flight generation (new ones can be added later
  // via pollJob; the tick guard prevents overlapping requests).
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
              api.wallet().catch(() => {}); // refresh balance in the nav
            }
          } catch { /* transient — keep polling */ }
        }
      } finally {
        tickRef.current = false;
      }
      if (activeIdsRef.current.size === 0) stopPolling();
    }, 2000);
  }, [stopPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  // Restore in-flight generations after a page refresh so the user keeps
  // seeing their queued/running session instead of an empty studio.
  useEffect(() => {
    let cancelled = false;
    api.listGenerations(20)
      .then((gens) => {
        if (cancelled) return;
        const active = gens.filter((g) => !TERMINAL.has(g.status)).reverse(); // oldest first
        if (active.length === 0) return;
        setTurns(active.map((g) => ({ prompt: g.prompt, mode: g.mode, refs: g.reference_paths, gen: g })));
        pollJob(...active.map((g) => g.id));
      })
      .catch(() => { /* non-fatal — studio still usable */ });
    return () => { cancelled = true; };
  }, [pollJob]);

  async function submit(p: SubmitPayload): Promise<string | null> {
    try {
      const gen = await api.createGeneration({
        ...p,
        params: p.params as Record<string, unknown>,
      });
      setTurns((prev) => [...prev, { prompt: p.prompt, mode: p.mode, refs: p.reference_paths, gen }]);
      pollJob(gen.id);
      return null;
    } catch (e) {
      return e instanceof Error ? e.message : "could not start generation";
    }
  }

  async function cancel(id: string) {
    const ok = window.confirm(
      "Cancel this generation? It keeps running even if you close the browser — cancel only if you really don't want it. Credits are refunded.");
    if (!ok) return;
    try { await api.cancelGeneration(id); } catch { /* already terminal */ }
  }

  /** Re-queue a failed/canceled generation; adds the new job to the thread. */
  async function retry(id: string): Promise<string | null> {
    try {
      const gen = await api.retryGeneration(id);
      setTurns((prev) => [...prev, {
        prompt: gen.prompt, mode: gen.mode,
        refs: gen.reference_paths, gen,
      }]);
      pollJob(gen.id);
      return null;
    } catch (e) {
      return e instanceof Error ? e.message : "could not retry generation";
    }
  }

  if (cfgError) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-24 text-center space-y-3">
        <h1 className="text-lg font-semibold">Studio unavailable</h1>
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
        <p className="text-sm text-muted">Generation is paused right now — please check back soon.</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] flex-col">
      <div className="mx-auto w-full max-w-3xl flex-1 space-y-5 px-4 py-6">
        {turns.length === 0 && (
          <div className="py-16 text-center space-y-2">
            <h1 className="text-2xl font-semibold tracking-tight">
              What will you <span className="gs-gradient-text">create</span> today?
            </h1>
            <p className="text-sm text-muted">
              Describe an image or video. Switch engine and mode below — reference images unlock
              editing and image-to-video.
            </p>
          </div>
        )}
        {turns.map((t) => (
          <div key={t.gen.id} className="space-y-2">
            <PromptBubble prompt={t.prompt} mode={t.mode} refs={t.refs} />
            <div className="flex"><ResultCard gen={t.gen} onCancel={cancel} onRetry={retry} /></div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <Composer
        cfg={cfg}
        engine={engine} setEngine={setEngine}
        mode={mode} setMode={setMode}
        estimate={estimate}
        template={template}
        onSubmit={submit}
      />
    </div>
  );
}
