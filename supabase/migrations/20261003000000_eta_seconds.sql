alter table public.generations add column if not exists eta_seconds int;

comment on column public.generations.eta_seconds is
  'Worker-measured seconds remaining (avg diffusion step time x remaining steps + VAE overhead); null = no live estimate.';