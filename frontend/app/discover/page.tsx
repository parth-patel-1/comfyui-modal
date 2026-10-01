"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { PromptTemplate } from "@/lib/types";
import { Badge, Button, Card, ErrorText, Spinner } from "@/components/ui";

export default function DiscoverPage() {
  const router = useRouter();
  const [templates, setTemplates] = useState<PromptTemplate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState<string>("all");

  useEffect(() => {
    api.templates().then(setTemplates).catch((e) => setError(e.message));
  }, []);

  const categories = useMemo(() => {
    if (!templates) return [];
    return ["all", ...Array.from(new Set(templates.map((t) => t.category)))];
  }, [templates]);

  const shown = useMemo(() => {
    if (!templates) return [];
    return category === "all" ? templates : templates.filter((t) => t.category === category);
  }, [templates, category]);

  if (error) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16">
        <ErrorText>{error}</ErrorText>
      </div>
    );
  }
  if (!templates) {
    return (
      <div className="grid place-items-center py-32">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          Discover <span className="gs-gradient-text">templates</span>
        </h1>
        <p className="mt-1 text-sm text-muted">
          Ready-made prompts for e-commerce shoots — saree drapes, jewelry try-ons, product
          backgrounds. Pick one, fill in the blanks, and generate in the Studio.
        </p>
      </div>

      <div className="mb-6 flex flex-wrap gap-2" role="group" aria-label="Filter by category">
        {categories.map((c) => (
          <button
            key={c}
            onClick={() => setCategory(c)}
            aria-pressed={category === c}
            className={`gs-focus rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
              category === c
                ? "border-accent-line bg-accent-soft text-accent"
                : "border-line text-muted hover:text-fg hover:bg-surface-2"
            }`}
          >
            {c === "all" ? "All" : c}
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <Card className="px-4 py-16 text-center text-sm text-muted">
          No templates in this category yet.
        </Card>
      ) : (
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {shown.map((t) => (
            <Card key={t.id} className="flex flex-col overflow-hidden">
              <div className="relative h-44 bg-surface-2">
                {t.example_image_path ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={api.templateImageUrl(t.id)}
                    alt={t.title}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <div className="grid h-full place-items-center text-3xl font-semibold text-faint">
                    <span className="gs-gradient-text">{t.category.slice(0, 2).toUpperCase()}</span>
                  </div>
                )}
                <span className="absolute left-3 top-3">
                  <Badge tone="accent">{t.category}</Badge>
                </span>
                {t.mode !== "t2i" && (
                  <span className="absolute right-3 top-3">
                    <Badge>{t.mode === "edit" ? "Reference edit" : t.mode.toUpperCase()}</Badge>
                  </span>
                )}
              </div>
              <div className="flex flex-1 flex-col gap-3 p-4">
                <h2 className="text-sm font-semibold">{t.title}</h2>
                <p className="line-clamp-3 flex-1 text-xs leading-relaxed text-muted">{t.prompt}</p>
                {t.placeholders.length > 0 && (
                  <p className="text-[11px] text-faint">
                    {t.placeholders.length} field{t.placeholders.length > 1 ? "s" : ""} to fill in
                  </p>
                )}
                <Button
                  className="w-full"
                  onClick={() => router.push(`/studio?template=${t.id}`)}
                >
                  Use in Studio
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
