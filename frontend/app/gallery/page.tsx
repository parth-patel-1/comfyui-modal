"use client";

import { useEffect, useState } from "react";
import { api, signedUrl } from "@/lib/api";
import type { Generation } from "@/lib/types";
import { Badge, Spinner } from "@/components/ui";

export default function GalleryPage() {
  const [items, setItems] = useState<Generation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<{ url: string; prompt: string } | null>(null);

  useEffect(() => {
    api
      .listGenerations(100)
      .then((gens) => setItems(gens.filter((g) => g.status === "succeeded" && g.output_paths.length)))
      .catch((e) => setError(e.message));
  }, []);

  if (error)
    return <p className="mx-auto max-w-3xl px-4 py-16 text-sm text-danger">{error}</p>;
  if (!items)
    return <div className="grid place-items-center py-32"><Spinner className="h-6 w-6 text-accent" /></div>;
  if (!items.length)
    return (
      <div className="mx-auto max-w-3xl px-4 py-24 text-center space-y-2">
        <h1 className="text-lg font-semibold">Nothing here yet</h1>
        <p className="text-sm text-muted">Your finished generations will appear in this gallery.</p>
      </div>
    );

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 space-y-4">
      <h1 className="text-lg font-semibold tracking-tight">Gallery</h1>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {items.map((g) => (
          <GalleryCard key={g.id} gen={g} onOpen={setOpen} />
        ))}
      </div>
      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={open.prompt}
          className="fixed inset-0 z-50 grid place-items-center p-6"
          style={{ background: "var(--scrim)" }}
          onClick={() => setOpen(null)}
        >
          <figure className="max-h-full max-w-4xl space-y-2" onClick={(e) => e.stopPropagation()}>
            {open.url.endsWith(".mp4") || open.url.includes(".mp4") ? (
              <video src={open.url} controls autoPlay className="max-h-[75vh] rounded-xl border border-line" />
            ) : (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={open.url} alt={open.prompt} className="max-h-[75vh] rounded-xl border border-line" />
            )}
            <figcaption className="rounded-lg bg-surface border border-line px-4 py-2 text-xs text-muted">
              {open.prompt}
            </figcaption>
          </figure>
        </div>
      )}
    </div>
  );
}

function GalleryCard({
  gen,
  onOpen,
}: {
  gen: Generation;
  onOpen: (v: { url: string; prompt: string }) => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    signedUrl("generations", gen.output_paths[0]).then(setUrl);
  }, [gen.output_paths]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <button
      onClick={() => url && onOpen({ url, prompt: gen.prompt })}
      className="gs-focus group relative block overflow-hidden rounded-xl border border-line bg-surface-2 text-left"
      aria-label={`Open: ${gen.prompt.slice(0, 60)}`}
    >
      <div className="aspect-square w-full">
        {url ? (
          gen.engine === "video" ? (
            <video src={url} muted playsInline className="h-full w-full object-cover" />
          ) : (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={url} alt={gen.prompt.slice(0, 80)} loading="lazy" className="h-full w-full object-cover transition-transform group-hover:scale-[1.03]" />
          )
        ) : (
          <div className="h-full w-full animate-pulse" />
        )}
      </div>
      <div className="absolute inset-x-0 bottom-0 translate-y-2 bg-gradient-to-t from-black/85 to-transparent p-3 opacity-0 transition-all group-hover:translate-y-0 group-hover:opacity-100">
        <p className="line-clamp-2 text-[11px] leading-snug text-white">{gen.prompt}</p>
        <div className="mt-1.5 flex gap-1.5">
          <Badge tone="accent">{gen.engine === "video" ? "Video" : "Image"}</Badge>
          <Badge>{gen.mode}</Badge>
        </div>
      </div>
    </button>
  );
}
