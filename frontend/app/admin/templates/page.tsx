"use client";

import { useEffect, useState } from "react";
import { adminApi, api, uploadReference } from "@/lib/api";
import type { Engine, Mode, PromptTemplate, TemplateBody, TemplatePlaceholder } from "@/lib/types";
import { Badge, Button, Card, ErrorText, Field, Input, Spinner, Textarea } from "@/components/ui";

const MODES: Record<string, { value: string; label: string }[]> = {
  image: [
    { value: "t2i", label: "Text -> Image" },
    { value: "edit", label: "Edit / reference" },
  ],
  video: [
    { value: "t2v", label: "Text -> Video" },
    { value: "i2v", label: "Image -> Video" },
  ],
};

const EMPTY: TemplateBody = {
  title: "", category: "general", engine: "image", mode: "t2i",
  prompt: "", negative_prompt: "", placeholders: [],
  example_image_path: null, active: true, sort_order: 0,
};

function TemplateEditor({
  initial, onSaved, onCancel,
}: {
  initial: TemplateBody & { id?: string };
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [body, setBody] = useState<TemplateBody & { id?: string }>(initial);
  const [imgPreview, setImgPreview] = useState<string | null>(
    initial.id && initial.example_image_path ? api.templateImageUrl(initial.id) : null,
  );
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof TemplateBody>(k: K, v: TemplateBody[K]) =>
    setBody((b) => ({ ...b, [k]: v }));

  async function uploadImage(file: File) {
    setError(null);
    setUploading(true);
    try {
      const path = await uploadReference(file);
      set("example_image_path", path);
      setImgPreview(URL.createObjectURL(file));
    } catch (e) {
      setError(e instanceof Error ? e.message : "upload failed");
    } finally {
      setUploading(false);
    }
  }

  function setPh(i: number, patch: Partial<TemplatePlaceholder>) {
    set("placeholders", body.placeholders.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  }

  async function save() {
    setError(null);
    if (!body.title.trim() || !body.prompt.trim()) {
      setError("Title and prompt are required.");
      return;
    }
    setBusy(true);
    try {
      const { id, ...payload } = body;
      if (id) await adminApi.updateTemplate(id, payload);
      else await adminApi.createTemplate(payload);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-4 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">{body.id ? "Edit template" : "New template"}</h2>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
      {error ? <ErrorText>{error}</ErrorText> : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Title"><Input value={body.title} onChange={(e) => set("title", e.target.value)} /></Field>
        <Field label="Category"><Input value={body.category} onChange={(e) => set("category", e.target.value)} placeholder="Apparel / Jewelry / ..." /></Field>
        <Field label="Engine">
          <select value={body.engine} aria-label="Engine"
            onChange={(e) => {
              const eng = e.target.value as Engine;
              setBody((b) => ({ ...b, engine: eng, mode: eng === "image" ? "t2i" : "t2v" }));
            }}
            className="gs-focus h-10 w-full rounded-lg bg-surface-2 border border-line px-3 text-sm text-fg">
            <option value="image">Image</option>
            <option value="video">Video</option>
          </select>
        </Field>
        <Field label="Mode">
          <select value={body.mode} aria-label="Mode"
            onChange={(e) => set("mode", e.target.value as Mode)}
            className="gs-focus h-10 w-full rounded-lg bg-surface-2 border border-line px-3 text-sm text-fg">
            {MODES[body.engine].map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </Field>
      </div>

      <Field label="Prompt" hint="Use {key} tokens for fill-in fields. In edit/i2v mode refer to uploaded images as <image1>, <image2>, ...">
        <Textarea rows={4} className="rounded-lg border border-line bg-surface-2 p-3"
          value={body.prompt} onChange={(e) => set("prompt", e.target.value)} />
      </Field>
      <Field label="Negative prompt (optional)">
        <Textarea rows={2} className="rounded-lg border border-line bg-surface-2 p-3"
          value={body.negative_prompt} onChange={(e) => set("negative_prompt", e.target.value)} />
      </Field>

      {/* placeholders */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-muted">Placeholders (fill-in fields)</span>
          <Button variant="outline" className="h-8 px-2.5 text-xs"
            onClick={() => set("placeholders", [...body.placeholders, { key: "", label: "", example: "" }])}>
            + Add field
          </Button>
        </div>
        {body.placeholders.map((p, i) => (
          <div key={i} className="grid gap-2 sm:grid-cols-[1fr_1.4fr_1.4fr_auto]">
            <Input value={p.key} placeholder="key e.g. color"
              onChange={(e) => setPh(i, { key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "") })} />
            <Input value={p.label} placeholder="Label e.g. Saree color"
              onChange={(e) => setPh(i, { label: e.target.value })} />
            <Input value={p.example} placeholder="Example / default value"
              onChange={(e) => setPh(i, { example: e.target.value })} />
            <Button variant="danger" className="h-10 px-3"
              onClick={() => set("placeholders", body.placeholders.filter((_, j) => j !== i))}>
              Remove
            </Button>
          </div>
        ))}
      </div>

      {/* example image + flags */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Example image (shown on the Discover card)">
          <div className="flex items-center gap-3">
            {imgPreview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={imgPreview} alt="Example" className="h-16 w-16 rounded-lg border border-line object-cover" />
            ) : (
              <div className="grid h-16 w-16 place-items-center rounded-lg border border-dashed border-line text-[10px] text-faint">none</div>
            )}
            <div className="space-y-1">
              <Button variant="outline" className="h-8 px-2.5 text-xs" disabled={uploading}
                onClick={() => document.getElementById("tpl-img-input")?.click()}>
                {uploading ? <Spinner className="h-3.5 w-3.5" /> : null} Upload
              </Button>
              {body.example_image_path ? (
                <Button variant="ghost" className="h-8 px-2 text-xs"
                  onClick={() => { set("example_image_path", null); setImgPreview(null); }}>
                  Clear
                </Button>
              ) : null}
            </div>
          </div>
          <input id="tpl-img-input" type="file" accept="image/png,image/jpeg,image/webp" hidden
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void uploadImage(f); e.target.value = ""; }} />
        </Field>
        <Field label="Active (visible on Discover)">
          <select value={body.active ? "1" : "0"} aria-label="Active"
            onChange={(e) => set("active", e.target.value === "1")}
            className="gs-focus h-10 w-full rounded-lg bg-surface-2 border border-line px-3 text-sm text-fg">
            <option value="1">Active</option>
            <option value="0">Hidden</option>
          </select>
        </Field>
        <Field label="Sort order">
          <Input type="number" value={body.sort_order}
            onChange={(e) => set("sort_order", Number(e.target.value) || 0)} />
        </Field>
      </div>

      <div className="flex justify-end">
        <Button onClick={save} disabled={busy}>{busy ? <Spinner /> : null} Save template</Button>
      </div>
    </Card>
  );
}

function toBody(t: PromptTemplate): TemplateBody & { id?: string } {
  return {
    id: t.id,
    title: t.title,
    category: t.category,
    engine: t.engine,
    mode: t.mode,
    prompt: t.prompt,
    negative_prompt: t.negative_prompt,
    placeholders: t.placeholders ?? [],
    example_image_path: t.example_image_path,
    active: t.active,
    sort_order: t.sort_order,
  };
}

export default function AdminTemplatesPage() {
  const [templates, setTemplates] = useState<PromptTemplate[] | null>(null);
  const [editing, setEditing] = useState<(TemplateBody & { id?: string }) | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    try {
      setTemplates(await adminApi.templates());
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    }
  }

  useEffect(() => { void reload(); }, []);

  async function remove(t: PromptTemplate) {
    if (!confirm(`Delete template "${t.title}"?`)) return;
    try {
      await adminApi.deleteTemplate(t.id);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "delete failed");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted">
          Templates shown on the Discover page. Users pick one, fill in the blanks, and generate.
        </p>
        {!editing && (
          <Button onClick={() => setEditing({ ...EMPTY })}>+ New template</Button>
        )}
      </div>
      {error ? <ErrorText>{error}</ErrorText> : null}

      {editing && (
        <TemplateEditor
          initial={editing}
          onSaved={() => { setEditing(null); void reload(); }}
          onCancel={() => setEditing(null)}
        />
      )}

      {!templates ? (
        <div className="grid place-items-center py-16"><Spinner className="h-6 w-6 text-accent" /></div>
      ) : (
        <Card className="divide-y divide-line">
          {templates.length === 0 && (
            <p className="px-4 py-10 text-center text-sm text-muted">No templates yet.</p>
          )}
          {templates.map((t) => (
            <div key={t.id} className="flex items-center gap-4 px-4 py-3">
              <div className="h-12 w-12 shrink-0 overflow-hidden rounded-lg border border-line bg-surface-2">
                {t.example_image_path ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={api.templateImageUrl(t.id)} alt="" className="h-full w-full object-cover" />
                ) : null}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-medium">{t.title}</span>
                  <Badge tone="accent">{t.category}</Badge>
                  <Badge>{t.engine}/{t.mode}</Badge>
                  {!t.active && <Badge tone="warning">hidden</Badge>}
                  <span className="text-[11px] text-faint">#{t.sort_order}</span>
                </div>
                <p className="mt-0.5 line-clamp-1 text-xs text-muted">{t.prompt}</p>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button variant="outline" className="h-8 px-2.5 text-xs" onClick={() => setEditing(toBody(t))}>
                  Edit
                </Button>
                <Button variant="danger" className="h-8 px-2.5 text-xs" onClick={() => void remove(t)}>
                  Delete
                </Button>
              </div>
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}





