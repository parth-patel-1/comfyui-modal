"use client";

import type { Engine, EngineCfg } from "@/lib/types";

export interface Params {
  width: number;
  height: number;
  steps: number;
  cfg: number;
  duration_s: number;
  turbo: boolean;
}

export function initParams(engine: Engine, eCfg: EngineCfg): Params {
  const [vw, vh] = eCfg.resolutions?.[0] ?? [864, 480];
  return {
    width: eCfg.resolution?.default ?? eCfg.default_resolution?.[0] ?? vw,
    height: eCfg.resolution?.default ?? eCfg.default_resolution?.[1] ?? vh,
    steps: eCfg.steps?.default ?? 20,
    cfg: eCfg.cfg?.default ?? 1, // video engine config has no `cfg` block
    duration_s: eCfg.duration_s?.default ?? 5,
    turbo: false,
  };
}

function Slider({
  label, value, min, max, step, onChange,
}: {
  label: string; value: number; min: number; max: number; step: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="block space-y-1">
      <span className="flex justify-between text-[11px] text-muted">
        <span>{label}</span>
        <span className="font-mono text-fg">{value}</span>
      </span>
      <input
        type="range"
        min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="gs-focus w-full accent-[var(--accent)]"
        aria-label={label}
      />
    </label>
  );
}

export default function ParamsPanel({
  engine, eCfg, params, setParams, negative, setNegative,
}: {
  engine: Engine;
  eCfg: EngineCfg;
  params: Params;
  setParams: (p: Params) => void;
  negative: string;
  setNegative: (v: string) => void;
}) {
  const set = (k: keyof Params, v: number | boolean) => setParams({ ...params, [k]: v });
  return (
    <div className="gs-fade-up grid gap-3 rounded-lg border border-line bg-surface p-3 sm:grid-cols-2">
      {engine === "image" && eCfg.resolution ? (
        <>
          <Slider label="Width" value={params.width} min={eCfg.resolution.min}
            max={eCfg.resolution.max} step={eCfg.resolution.step}
            onChange={(v) => set("width", v)} />
          <Slider label="Height" value={params.height} min={eCfg.resolution.min}
            max={eCfg.resolution.max} step={eCfg.resolution.step}
            onChange={(v) => set("height", v)} />
        </>
      ) : engine === "video" ? (
        <label className="block space-y-1">
          <span className="text-[11px] text-muted">Resolution</span>
          <select
            value={`${params.width}x${params.height}`}
            onChange={(e) => {
              const [w, h] = e.target.value.split("x").map(Number);
              setParams({ ...params, width: w, height: h });
            }}
            aria-label="Video resolution"
            className="gs-focus h-9 w-full rounded-lg border border-line bg-surface-2 px-2 text-xs text-fg"
          >
            {(eCfg.resolutions ?? [[864, 480]]).map(([w, h]) => (
              <option key={`${w}x${h}`} value={`${w}x${h}`}>{w} × {h}</option>
            ))}
          </select>
        </label>
      ) : null}
      {engine === "video" && eCfg.duration_s ? (
        <Slider label="Duration (s)" value={params.duration_s} min={eCfg.duration_s.min}
          max={eCfg.duration_s.max} step={eCfg.duration_s.step}
          onChange={(v) => set("duration_s", v)} />
      ) : null}
      <Slider label="Steps" value={params.steps} min={eCfg.steps.min}
        max={eCfg.steps.max} step={1} onChange={(v) => set("steps", v)} />
      {engine === "image" && (
        <Slider label="CFG" value={params.cfg} min={eCfg.cfg.min}
          max={eCfg.cfg.max} step={0.5} onChange={(v) => set("cfg", v)} />
      )}
      {engine === "video" && (
        <label className="flex items-center gap-2 text-xs text-muted">
          <input type="checkbox" checked={params.turbo}
            onChange={(e) => set("turbo", e.target.checked)}
            className="accent-[var(--accent)]" />
          Turbo (faster, lower fidelity)
        </label>
      )}
      <label className="block space-y-1 sm:col-span-2">
        <span className="text-[11px] text-muted">Negative prompt</span>
        <textarea
          rows={1}
          value={negative}
          onChange={(e) => setNegative(e.target.value)}
          aria-label="Negative prompt"
          className="gs-focus w-full resize-none rounded-lg bg-surface-2 border border-line px-3 py-2 text-xs text-fg placeholder:text-faint"
        />
      </label>
    </div>
  );
}
