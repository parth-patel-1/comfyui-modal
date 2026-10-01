-- ============================================================
-- GenStudio initial schema
-- identity, credits, pricing, modal config, jobs, audit
-- ============================================================
create extension if not exists pgcrypto;

create or replace function public.set_updated_at() returns trigger
language plpgsql as $fn$
begin
  new.updated_at = now();
  return new;
end
$fn$;

-- ---------------------------------------------------------------- profiles
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  display_name text not null default '',
  role text not null default 'user' check (role in ('user','admin')),
  status text not null default 'active' check (status in ('active','suspended')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create trigger trg_profiles_updated before update on public.profiles
  for each row execute function public.set_updated_at();

-- ------------------------------------------------------------ app_settings
create table public.app_settings (
  id int primary key default 1 check (id = 1),
  site_name text not null default 'GenStudio',
  signup_grant_credits int not null default 0 check (signup_grant_credits >= 0),
  maintenance_mode boolean not null default false,
  max_concurrent_jobs_per_user int not null default 1 check (max_concurrent_jobs_per_user >= 1),
  daily_job_cap int not null default 200 check (daily_job_cap >= 1),
  default_negative_prompt_image text not null default 'blurry, low quality, jpeg artifacts, watermark, deformed hands, extra fingers',
  default_negative_prompt_video text not null default '',
  updated_by uuid references public.profiles(id),
  updated_at timestamptz not null default now()
);
insert into public.app_settings (id) values (1);

-- ----------------------------------------------------------- modal_settings
create table public.modal_settings (
  id int primary key default 1 check (id = 1),
  image_gpu text not null default 'L40S',
  video_gpu text not null default 'L40S',
  image_max_containers int not null default 1 check (image_max_containers between 1 and 20),
  video_max_containers int not null default 1 check (video_max_containers between 1 and 20),
  image_min_containers int not null default 0 check (image_min_containers >= 0),
  video_min_containers int not null default 0 check (video_min_containers >= 0),
  scaledown_window_s int not null default 300 check (scaledown_window_s between 10 and 7200),
  max_inputs int not null default 8 check (max_inputs between 1 and 64),
  overhead_factor numeric not null default 1.25 check (overhead_factor >= 1),
  comfyui_version text not null default 'v0.37.0',
  image_endpoint text not null default '',
  video_endpoint text not null default '',
  pending_deploy jsonb,
  updated_by uuid references public.profiles(id),
  updated_at timestamptz not null default now()
);
insert into public.modal_settings (id) values (1);

-- ------------------------------------------------------------------ credits
create table public.credit_wallets (
  user_id uuid primary key references public.profiles(id) on delete cascade,
  balance int not null default 0 check (balance >= 0),
  updated_at timestamptz not null default now()
);
create trigger trg_wallets_updated before update on public.credit_wallets
  for each row execute function public.set_updated_at();

create table public.credit_transactions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  delta int not null,
  balance_after int not null,
  kind text not null check (kind in ('signup_grant','admin_grant','admin_adjust','generation_debit','generation_refund')),
  generation_id uuid,
  note text not null default '',
  created_by uuid references public.profiles(id),
  created_at timestamptz not null default now()
);
create index idx_credit_tx_user on public.credit_transactions (user_id, created_at desc);

-- ---------------------------------------------------------------- gpu rates
create table public.gpu_rates (
  gpu_type text primary key,
  hourly_usd numeric not null check (hourly_usd > 0),
  active boolean not null default true,
  updated_at timestamptz not null default now()
);
insert into public.gpu_rates (gpu_type, hourly_usd) values
  ('T4', 0.59), ('L4', 0.80), ('A10G', 1.10), ('L40S', 1.95),
  ('A100-40GB', 2.10), ('A100-80GB', 5.24), ('H200', 4.54), ('H100', 6.79);

-- ------------------------------------------------------------ pricing rules
create table public.pricing_rules (
  id uuid primary key default gen_random_uuid(),
  engine text not null check (engine in ('image','video')),
  active boolean not null default true,
  base_credits int not null default 0 check (base_credits >= 0),
  credits_per_megapixel numeric not null default 0 check (credits_per_megapixel >= 0),
  credits_per_ref_image int not null default 0 check (credits_per_ref_image >= 0),
  credits_per_video_second numeric not null default 0 check (credits_per_video_second >= 0),
  min_credits int not null default 1 check (min_credits >= 0),
  max_credits int not null default 100000,
  valid_from timestamptz not null default now(),
  created_by uuid references public.profiles(id),
  created_at timestamptz not null default now()
);
create index idx_pricing_engine on public.pricing_rules (engine, active, valid_from desc);
insert into public.pricing_rules (engine, base_credits, credits_per_megapixel, credits_per_ref_image, credits_per_video_second) values
  ('image', 3, 2, 1, 0),
  ('video', 10, 1, 2, 4);

-- ---------------------------------------------------------- engine configs
create table public.engine_configs (
  engine text primary key check (engine in ('image','video')),
  enabled boolean not null default true,
  params jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);
create trigger trg_engine_configs_updated before update on public.engine_configs
  for each row execute function public.set_updated_at();
insert into public.engine_configs (engine, params) values
('image', '{
  "orientation_presets": {"square": [1024, 1024], "portrait": [832, 1216], "landscape": [1216, 832]},
  "resolution": {"min": 512, "max": 2048, "step": 64, "default": 1024},
  "steps": {"min": 4, "max": 50, "default": 25},
  "cfg": {"min": 1.0, "max": 10.0, "step": 0.1, "default": 1.0},
  "seed": {"allow_random": true},
  "max_reference_images": 16,
  "max_prompt_chars": 4000
}'::jsonb),
('video', '{
  "fps": 24,
  "duration_s": {"min": 5, "max": 15, "default": 5, "step": 1},
  "resolutions": [[864, 480], [1344, 768], [768, 1344], [480, 864]],
  "default_resolution": [864, 480],
  "steps": {"min": 8, "max": 30, "default": 20},
  "turbo_available": true,
  "audio": {"available": true, "default": true},
  "max_reference_images": 2,
  "max_prompt_chars": 6000
}'::jsonb);

-- -------------------------------------------------------------- generations
create table public.generations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  engine text not null check (engine in ('image','video')),
  mode text not null check (mode in ('t2i','edit','t2v','i2v')),
  status text not null default 'queued'
    check (status in ('queued','provisioning','running','uploading','succeeded','failed','canceled')),
  progress int not null default 0 check (progress between 0 and 100),
  prompt text not null,
  negative_prompt text not null default '',
  params jsonb not null default '{}'::jsonb,
  reference_paths text[] not null default '{}',
  credits_charged int not null default 0,
  gpu_type text not null default '',
  comfy_prompt_id text not null default '',
  queue_position int,
  error text not null default '',
  output_paths text[] not null default '{}',
  duration_ms int,
  cost_compute_usd numeric,
  cost_billed_est_usd numeric,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);
create index idx_generations_user on public.generations (user_id, created_at desc);
create index idx_generations_active on public.generations (status)
  where status in ('queued','provisioning','running','uploading');
create index idx_generations_engine_time on public.generations (engine, created_at desc);

create table public.generation_events (
  id bigint generated always as identity primary key,
  generation_id uuid not null references public.generations(id) on delete cascade,
  event text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index idx_gen_events on public.generation_events (generation_id, created_at);

create table public.admin_audit_log (
  id bigint generated always as identity primary key,
  admin_id uuid not null references public.profiles(id),
  action text not null,
  target text not null default '',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index idx_audit_time on public.admin_audit_log (created_at desc);

create table public.deploy_runs (
  id uuid primary key default gen_random_uuid(),
  triggered_by uuid references public.profiles(id),
  trigger_reason text not null default 'gpu_settings_change',
  status text not null default 'running' check (status in ('running','succeeded','failed')),
  log text not null default '',
  config_snapshot jsonb not null default '{}'::jsonb,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

-- ------------------------------------------------- new-user bootstrap trigger
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $fn$
declare
  v_grant int;
begin
  insert into public.profiles (id, email, display_name)
  values (
    new.id,
    coalesce(new.email, ''),
    coalesce(new.raw_user_meta_data ->> 'name', split_part(coalesce(new.email, 'user'), '@', 1))
  )
  on conflict (id) do nothing;

  select signup_grant_credits into v_grant from public.app_settings where id = 1;
  insert into public.credit_wallets (user_id, balance)
  values (new.id, coalesce(v_grant, 0))
  on conflict (user_id) do nothing;

  if coalesce(v_grant, 0) > 0 then
    insert into public.credit_transactions (user_id, delta, balance_after, kind, note)
    values (new.id, v_grant, v_grant, 'signup_grant', 'welcome credits');
  end if;
  return new;
end
$fn$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------- is_admin()
create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $fn$
  select exists (
    select 1 from public.profiles
    where id = auth.uid() and role = 'admin'
  )
$fn$;

-- ============================================================
-- Pricing + credit RPCs (atomic, security definer)
-- ============================================================

-- Compute credit price for a generation from the active pricing rule.
create or replace function public.compute_generation_credits(
  p_engine text,
  p_params jsonb,
  p_ref_count int default 0
)
returns int
language plpgsql
stable
security definer
set search_path = public
as $fn$
declare
  r public.pricing_rules%rowtype;
  v_w int;
  v_h int;
  v_secs numeric;
  v_c numeric;
begin
  select * into r from public.pricing_rules
    where engine = p_engine and active
    order by valid_from desc
    limit 1;
  if not found then
    raise exception 'NO_ACTIVE_PRICING_RULE:%', p_engine;
  end if;

  v_w := coalesce((p_params ->> 'width')::int,
                  case when p_engine = 'image' then 1024 else 864 end);
  v_h := coalesce((p_params ->> 'height')::int,
                  case when p_engine = 'image' then 1024 else 480 end);

  if p_engine = 'image' then
    v_c := r.base_credits
         + r.credits_per_megapixel * ((v_w::numeric * v_h) / 1000000.0)
         + r.credits_per_ref_image * coalesce(p_ref_count, 0);
  else
    v_secs := coalesce((p_params ->> 'duration_s')::numeric, 5);
    v_c := r.base_credits
         + r.credits_per_video_second * v_secs
         + r.credits_per_megapixel * ((v_w::numeric * v_h) / 1000000.0)
         + r.credits_per_ref_image * coalesce(p_ref_count, 0);
  end if;

  v_c := ceil(v_c);
  return least(greatest(v_c::int, r.min_credits), r.max_credits);
end
$fn$;

-- Validate limits, price the job, debit credits and insert the queued job
-- in ONE atomic transaction. Called by the backend (service role).
create or replace function public.request_generation(
  p_user uuid,
  p_engine text,
  p_mode text,
  p_prompt text,
  p_negative_prompt text default '',
  p_params jsonb default '{}'::jsonb,
  p_reference_paths text[] default '{}',
  p_gpu_type text default ''
)
returns table (generation_id uuid, credits_charged int)
language plpgsql
security definer
set search_path = public
as $fn$
declare
  v_credits int;
  v_balance int;
  v_id uuid;
  v_max_conc int;
  v_daily_cap int;
  v_running int;
  v_today int;
  v_maintenance boolean;
  v_status text;
  v_ref_count int;
begin
  select maintenance_mode into v_maintenance from app_settings where id = 1;
  if coalesce(v_maintenance, false) then
    raise exception 'MAINTENANCE_MODE';
  end if;

  select status into v_status from profiles where id = p_user;
  if v_status is null then
    raise exception 'PROFILE_NOT_FOUND';
  end if;
  if v_status <> 'active' then
    raise exception 'ACCOUNT_SUSPENDED';
  end if;

  select max_concurrent_jobs_per_user, daily_job_cap
    into v_max_conc, v_daily_cap
    from app_settings where id = 1;

  select count(*) into v_running from generations
    where user_id = p_user
      and status in ('queued','provisioning','running','uploading');
  if v_running >= coalesce(v_max_conc, 1) then
    raise exception 'TOO_MANY_ACTIVE_JOBS';
  end if;

  select count(*) into v_today from generations
    where user_id = p_user and created_at >= date_trunc('day', now());
  if v_today >= coalesce(v_daily_cap, 999999) then
    raise exception 'DAILY_CAP_REACHED';
  end if;

  v_ref_count := coalesce(array_length(p_reference_paths, 1), 0);
  v_credits := public.compute_generation_credits(p_engine, p_params, v_ref_count);

  select balance into v_balance from credit_wallets
    where user_id = p_user for update;
  if v_balance is null then
    raise exception 'WALLET_NOT_FOUND';
  end if;
  if v_balance < v_credits then
    raise exception 'INSUFFICIENT_CREDITS:%', v_credits;
  end if;

  update credit_wallets set balance = balance - v_credits
    where user_id = p_user
    returning balance into v_balance;

  insert into generations
    (user_id, engine, mode, prompt, negative_prompt, params,
     reference_paths, credits_charged, gpu_type, status)
  values
    (p_user, p_engine, p_mode, p_prompt, coalesce(p_negative_prompt, ''),
     coalesce(p_params, '{}'::jsonb), coalesce(p_reference_paths, '{}'::text[]),
     v_credits, coalesce(p_gpu_type, ''), 'queued')
  returning id into v_id;

  insert into credit_transactions
    (user_id, delta, balance_after, kind, generation_id, note)
  values
    (p_user, -v_credits, v_balance, 'generation_debit', v_id, p_engine);

  insert into generation_events (generation_id, event, payload)
  values (v_id, 'queued', jsonb_build_object('credits', v_credits));

  return query select v_id, v_credits;
end
$fn$;

-- Finalize a job; refunds credits on failure. Idempotent.
create or replace function public.settle_generation(
  p_generation_id uuid,
  p_success boolean,
  p_error text default '',
  p_duration_ms int default null,
  p_cost_compute_usd numeric default null,
  p_cost_billed_est_usd numeric default null,
  p_outputs text[] default '{}'
)
returns void
language plpgsql
security definer
set search_path = public
as $fn$
declare
  v_user uuid;
  v_credits int;
  v_status text;
  v_balance int;
begin
  select user_id, credits_charged, status
    into v_user, v_credits, v_status
    from generations where id = p_generation_id for update;
  if not found then
    raise exception 'GENERATION_NOT_FOUND';
  end if;
  if v_status in ('succeeded','failed','canceled') then
    return;
  end if;

  if p_success then
    update generations set
      status = 'succeeded',
      finished_at = now(),
      duration_ms = coalesce(p_duration_ms, duration_ms),
      cost_compute_usd = coalesce(p_cost_compute_usd, cost_compute_usd),
      cost_billed_est_usd = coalesce(p_cost_billed_est_usd, cost_billed_est_usd),
      output_paths = p_outputs,
      progress = 100
    where id = p_generation_id;
  else
    update generations set
      status = 'failed',
      finished_at = now(),
      error = coalesce(p_error, 'unknown'),
      duration_ms = coalesce(p_duration_ms, duration_ms),
      cost_compute_usd = coalesce(p_cost_compute_usd, cost_compute_usd),
      cost_billed_est_usd = coalesce(p_cost_billed_est_usd, cost_billed_est_usd)
    where id = p_generation_id;

    if v_credits > 0 then
      update credit_wallets set balance = balance + v_credits
        where user_id = v_user
        returning balance into v_balance;
      insert into credit_transactions
        (user_id, delta, balance_after, kind, generation_id, note)
      values
        (v_user, v_credits, v_balance, 'generation_refund', p_generation_id, 'failed generation refund');
    end if;
  end if;
end
$fn$;

-- Cancel a queued/provisioning job (owner or admin); refunds credits.
create or replace function public.cancel_generation(
  p_generation_id uuid,
  p_requester uuid
)
returns void
language plpgsql
security definer
set search_path = public
as $fn$
declare
  v_user uuid;
  v_credits int;
  v_status text;
  v_balance int;
  v_is_admin boolean;
begin
  select user_id, credits_charged, status
    into v_user, v_credits, v_status
    from generations where id = p_generation_id for update;
  if not found then
    raise exception 'GENERATION_NOT_FOUND';
  end if;

  select coalesce(role = 'admin', false) into v_is_admin
    from profiles where id = p_requester;
  if v_user <> p_requester and not coalesce(v_is_admin, false) then
    raise exception 'FORBIDDEN';
  end if;
  if v_status not in ('queued','provisioning') then
    raise exception 'JOB_ALREADY_RUNNING';
  end if;

  update generations set status = 'canceled', finished_at = now()
    where id = p_generation_id;

  if v_credits > 0 then
    update credit_wallets set balance = balance + v_credits
      where user_id = v_user
      returning balance into v_balance;
    insert into credit_transactions
      (user_id, delta, balance_after, kind, generation_id, note)
    values
      (v_user, v_credits, v_balance, 'generation_refund', p_generation_id, 'canceled before start');
  end if;
end
$fn$;

-- Admin credit grant/deduct with ledger + audit trail.
create or replace function public.admin_adjust_credits(
  p_target uuid,
  p_delta int,
  p_note text default '',
  p_admin uuid default null
)
returns int
language plpgsql
security definer
set search_path = public
as $fn$
declare
  v_balance int;
  v_admin uuid;
  v_kind text;
begin
  v_admin := coalesce(p_admin, auth.uid());
  if v_admin is null or not exists (
    select 1 from profiles where id = v_admin and role = 'admin'
  ) then
    raise exception 'FORBIDDEN';
  end if;
  if p_delta = 0 then
    raise exception 'DELTA_CANNOT_BE_ZERO';
  end if;

  select balance into v_balance from credit_wallets
    where user_id = p_target for update;
  if v_balance is null then
    raise exception 'WALLET_NOT_FOUND';
  end if;
  if v_balance + p_delta < 0 then
    raise exception 'BALANCE_WOULD_GO_NEGATIVE';
  end if;

  update credit_wallets set balance = balance + p_delta
    where user_id = p_target
    returning balance into v_balance;

  v_kind := case when p_delta > 0 then 'admin_grant' else 'admin_adjust' end;
  insert into credit_transactions
    (user_id, delta, balance_after, kind, note, created_by)
  values
    (p_target, p_delta, v_balance, v_kind, p_note, v_admin);

  insert into admin_audit_log (admin_id, action, target, payload)
  values (v_admin, 'adjust_credits', p_target::text,
          jsonb_build_object('delta', p_delta, 'note', p_note));

  return v_balance;
end
$fn$;

-- ============================================================
-- RLS, grants, storage, realtime
-- ============================================================

alter table public.profiles enable row level security;
alter table public.app_settings enable row level security;
alter table public.modal_settings enable row level security;
alter table public.credit_wallets enable row level security;
alter table public.credit_transactions enable row level security;
alter table public.gpu_rates enable row level security;
alter table public.pricing_rules enable row level security;
alter table public.engine_configs enable row level security;
alter table public.generations enable row level security;
alter table public.generation_events enable row level security;
alter table public.admin_audit_log enable row level security;
alter table public.deploy_runs enable row level security;

-- profiles: see self; admins see all; self-update limited to display_name
create policy "profiles_select" on public.profiles for select
  using (id = auth.uid() or public.is_admin());
create policy "profiles_update_self" on public.profiles for update
  using (id = auth.uid()) with check (id = auth.uid());
revoke update on public.profiles from authenticated;
grant update (display_name) on public.profiles to authenticated;

-- credits: read-only to owners (mutations only via RPCs / service role)
create policy "wallets_select" on public.credit_wallets for select
  using (user_id = auth.uid() or public.is_admin());
create policy "tx_select" on public.credit_transactions for select
  using (user_id = auth.uid() or public.is_admin());

-- jobs: read-only to owners (created/canceled via RPCs; worker uses service role)
create policy "generations_select" on public.generations for select
  using (user_id = auth.uid() or public.is_admin());
create policy "gen_events_select" on public.generation_events for select
  using (exists (
    select 1 from public.generations g
    where g.id = generation_id and (g.user_id = auth.uid() or public.is_admin())
  ));

-- admin-only config tables (users get curated config from the backend API)
create policy "app_settings_admin" on public.app_settings for select using (public.is_admin());
create policy "modal_settings_admin" on public.modal_settings for select using (public.is_admin());
create policy "gpu_rates_admin" on public.gpu_rates for select using (public.is_admin());
create policy "pricing_admin" on public.pricing_rules for select using (public.is_admin());
create policy "engine_configs_admin" on public.engine_configs for select using (public.is_admin());
create policy "deploy_runs_admin" on public.deploy_runs for select using (public.is_admin());
create policy "audit_admin" on public.admin_audit_log for select using (public.is_admin());

-- function execution: internal/admin RPCs are service-role only
revoke all on function public.handle_new_user() from public, anon, authenticated;
revoke all on function public.is_admin() from public, anon;
grant execute on function public.is_admin() to authenticated;
revoke all on function public.compute_generation_credits(text, jsonb, int) from public, anon, authenticated;
revoke all on function public.request_generation(uuid, text, text, text, text, jsonb, text[], text) from public, anon, authenticated;
revoke all on function public.settle_generation(uuid, boolean, text, int, numeric, numeric, text[]) from public, anon, authenticated;
revoke all on function public.cancel_generation(uuid, uuid) from public, anon, authenticated;
revoke all on function public.admin_adjust_credits(uuid, int, text, uuid) from public, anon, authenticated;
grant execute on function public.compute_generation_credits(text, jsonb, int) to service_role;
grant execute on function public.request_generation(uuid, text, text, text, text, jsonb, text[], text) to service_role;
grant execute on function public.settle_generation(uuid, boolean, text, int, numeric, numeric, text[]) to service_role;
grant execute on function public.cancel_generation(uuid, uuid) to service_role;
grant execute on function public.admin_adjust_credits(uuid, int, text, uuid) to service_role;

-- storage buckets (private)
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('references', 'references', false, 26214400,
        array['image/png','image/jpeg','image/webp'])
on conflict (id) do update
  set file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

insert into storage.buckets (id, name, public, file_size_limit)
values ('generations', 'generations', false, 524288000)
on conflict (id) do nothing;

-- owners manage their own reference uploads (first path segment = uid)
create policy "references_owner_rw" on storage.objects for all
  using (bucket_id = 'references' and (storage.foldername(name))[1] = auth.uid()::text)
  with check (bucket_id = 'references' and (storage.foldername(name))[1] = auth.uid()::text);
-- generations bucket: service-role write, read via signed URLs only

-- realtime: push job + wallet changes to subscribed clients
alter table public.generations replica identity default;
alter publication supabase_realtime add table public.generations;
alter publication supabase_realtime add table public.credit_wallets;