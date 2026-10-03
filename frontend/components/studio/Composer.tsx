"use client";

import { useEffect, useRef, useState } from "react";
import { uploadReference } from "@/lib/api";
import type { Engine, Mode, PromptTemplate, StudioConfig } from "@/lib/types";
import { Badge, Button, ErrorText, Spinner, Textarea } from "@/components/ui";
import ParamsPanel, { initParams, type Params } from "./ParamsPanel";

const MODES: Record<Engine, { value: Mode; label: string }[]> = {
  image: [
    { value: "t2i", label: "Text -> Image" },
    { value: "edit", label: "Edit image" },
  ],
  video: [
    { value: "t2v", label: "Text -> Video" },
    { value: "i2v", label: "Image -> Video" },
  ],
};

const needsRefs = (m: Mode) => m === "edit" || m === "i2v";

/** Replace {key} tokens with the user's values (unknown keys are left intact). */
function interpolate(s: string, vals: Record<string, string>): string {
  return s.replace(/\{(\w+)\}/g, (_, k: string) =>
    vals[k] !== undefined && vals[k] !== "" ? vals[k] : `{${k}}`,
  );
}

export interface SubmitPayload {
  engine: Engine;
  mode: Mode;
  prompt: string;
  negative_prompt: string;
  params: Record<string, unknown>;
  reference_paths: string[];
}

export default function Composer({
  cfg, engine, setEngine, mode, setMode, estimate, disabled = false, template,
  submitLabel = "Generate", onSubmit,
}: {
  cfg: StudioConfig;
  engine: Engine;
  setEngine: (e: Engine) => void;
  mode: Mode;
  setMode: (m: Mode) => void;
  estimate: number | null;
  disabled?: boolean;
  template?: PromptTemplate | null;
  /** Button text — "Add to queue" on the queue page, "Generate" in studio. */
  submitLabel?: string;
  onSubmit: (p: SubmitPayload) => Promise<string | null>;
}) {
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [phValues, setPhValues] = useState<Record<string, string>>({});
  const [refs, setRefs] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showParams, setShowParams] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const eCfg = cfg.engines[engine];
  const maxRefs = eCfg.max_reference_images ?? (engine === "image" ? 16 : 1);
  const [params, setParams] = useState<Params>(() => initParams(engine, eCfg));

  useEffect(() => {
    setParams(initParams(engine, cfg.engines[engine]));
    setShowParams(false);
  }, [engine, cfg]); // eslint-disable-line react-hooks/exhaustive-deps

  // Template picked on the Discover page: prefill prompt (placeholders filled
  // with their example values), negative prompt, and engine/mode.
  useEffect(() => {
    if (!template) return;
    const vals: Record<string, string> = {};
    for (const p of template.placeholders) vals[p.key] = p.example;
    setPhValues(vals);
    setPrompt(interpolate(template.prompt, vals));
    setNegative(template.negative_prompt);
    setEngine(template.engine);
    setMode(template.mode);
  }, [template]); // eslint-disable-line react-hooks/exhaustive-deps

  function setPh(key: string, value: string) {
    if (!template) return;
    const vals = { ...phValues, [key]: value };
    setPhValues(vals);
    setPrompt(interpolate(template.prompt, vals));
  }

  async function addFiles(files: File[]) {
    if (!files.length) return;
    setError(null);
    setUploading(true);
    try {
      for (const f of files) {
        if (refs.length >= maxRefs) {
          setError(`At most ${maxRefs} reference image${maxRefs > 1 ? "s" : ""}.`);
          break;
        }
        const path = await uploadReference(f);
        setRefs((prev) => [...prev, path]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "upload failed");
    } finally {
      setUploading(false);
    }
  }

  function pickFiles(files: FileList | null) {
    if (!files?.length) return;
    void addFiles(Array.from(files));
    if (fileRef.current) fileRef.current.value = "";
  }

  // Pasting a screenshot/image from the clipboard (Ctrl/Cmd+V) attaches it
  // as a reference. If the current mode does not use references, it
  // auto-switches (t2i -> edit, t2v -> i2v) so the pasted image is used.
  useEffect(() => {
    function onPaste(e: ClipboardEvent) {
      const imgs = Array.from(e.clipboardData?.items ?? []).filter((i) =>
        i.type.startsWith("image/"),
      );
      if (imgs.length === 0) return; // plain-text pastes behave normally
      e.preventDefault();
      const files = imgs
        .map((i) => i.getAsFile())
        .filter((f): f is File => f instanceof File);
      if (!files.length) return;
      if (!needsRefs(mode)) setMode(engine === "video" ? "i2v" : "edit");
      void addFiles(files);
    }
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  }, [engine, mode, maxRefs, refs]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit() {
    if (!prompt.trim()) { setError("Describe what you want to create."); return; }
    if (needsRefs(mode) && refs.length === 0) {
      setError("This mode needs at least one reference image.");
      return;
    }
    setError(null);
    setBusy(true);
    const { turbo, ...rest } = params;
    const err = await onSubmit({
      engine, mode,
      prompt: prompt.trim(),
      negative_prompt: negative,
      params: engine === "video" ? { ...rest, turbo } : rest,
      reference_paths: refs,
    });
    setBusy(false);
    if (err) { setError(err); return; }
    setPrompt("");
    setRefs([]);
  }

  return (
    <div className="sticky bottom-0 border-t border-line bg-bg/90 backdrop-blur">
      <div className="mx-auto max-w-3xl px-4 py-3 space-y-2">
        {error ? <ErrorText>{error}</ErrorText> : null}

        {refs.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {refs.map((r) => (
              <span key={r} className="inline-flex items-center gap-1.5 rounded-md border border-accent-line bg-accent-soft px-2 py-1 text-[11px] text-accent">
                ref {r.split("/").pop()?.slice(0, 10)}
                <button aria-label="Remove reference" onClick={() => setRefs((prev) => prev.filter((x) => x !== r))}
                  className="gs-focus rounded-full hover:text-fg" aria-hidden="true">x</button>
              </span>
            ))}
          </div>
        )}

        {template && template.placeholders.length > 0 && (
          <div className="rounded-lg border border-accent-line bg-accent-soft p-2.5 space-y-2">
            <div className="flex items-center gap-2">
              <Badge tone="accent">{template.title}</Badge>
              <span className="text-[11px] text-muted">fill in the blanks</span>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {template.placeholders.map((p) => (
                <label key={p.key} className="flex items-center gap-2 text-xs">
                  <span className="w-24 shrink-0 truncate text-muted" title={p.label}>{p.label}</span>
                  <input
                    value={phValues[p.key] ?? ""}
                    onChange={(e) => setPh(p.key, e.target.value)}
                    aria-label={p.label}
                    className="gs-focus h-8 w-full rounded-lg border border-line bg-surface-2 px-2 text-xs text-fg"
                  />
                </label>
              ))}
            </div>
            {needsRefs(template.mode) && (
              <p className="text-[11px] text-muted">
                This template works on a reference image — upload your own photo below (the
                Discover card shows an example only).
              </p>
            )}
          </div>
        )}

        <Textarea
          rows={2}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); }
          }}
          placeholder={engine === "video"
            ? "Describe the video - camera move, subject, mood..."
            : "Describe the image you want - subject, style, lighting..."}
          aria-label="Prompt"
        />

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-lg border border-line p-0.5" role="group" aria-label="Engine">
            {(Object.keys(MODES) as Engine[]).map((eng) => (
              <button key={eng} onClick={() => { setEngine(eng); setMode(MODES[eng][0].value); }}
                aria-pressed={engine === eng}
                className={`gs-focus rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  engine === eng ? "bg-accent-soft text-accent" : "text-muted hover:text-fg"}`}>
                {eng === "image" ? "Image" : "Video"}
              </button>
            ))}
          </div>

          <select value={mode} onChange={(e) => setMode(e.target.value as Mode)}
            aria-label="Generation mode"
            className="gs-focus h-8 rounded-lg border border-line bg-surface-2 px-2 text-xs text-fg">
            {MODES[engine].map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>

          <span className="hidden text-[11px] text-muted md:inline">
            Paste an image (Ctrl+V) to attach it
          </span>

          {needsRefs(mode) && (
            <Button variant="outline" className="h-8 px-2.5 text-xs" disabled={uploading}
              onClick={() => fileRef.current?.click()}>
              {uploading ? <Spinner className="h-3.5 w-3.5" /> : "+"} Add reference{maxRefs > 1 ? "s" : ""}
            </Button>
          )}
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" multiple hidden
            onChange={(e) => pickFiles(e.target.files)} aria-label="Upload reference images" />

          <Button variant="ghost" className="h-8 px-2.5 text-xs" aria-expanded={showParams}
            onClick={() => setShowParams((s) => !s)}>
            Settings
          </Button>

          <div className="ml-auto flex items-center gap-2">
            {estimate !== null && <Badge tone="accent">~ {estimate} credits</Badge>}
            <Button onClick={submit} disabled={busy || disabled} className="h-9 px-4">
              {busy ? <Spinner /> : submitLabel}
            </Button>
          </div>
        </div>

        {showParams && (
          <ParamsPanel engine={engine} eCfg={eCfg} params={params} setParams={setParams}
            negative={negative} setNegative={setNegative} />
        )}
      </div>
    </div>
  );
}