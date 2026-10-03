-- Queue + parallel generation:
--  - worker_parallel_slots: how many jobs the worker runs CONCURRENTLY per
--    engine (image and video each get this many slots).
--  - raise max_concurrent_jobs_per_user so a user can line up many jobs
--    (the queue tab submits any number; each still costs credits upfront).
alter table public.app_settings
  add column if not exists worker_parallel_slots int not null default 2;
alter table public.app_settings
  drop constraint if exists app_settings_worker_slots_range;
alter table public.app_settings
  add constraint app_settings_worker_slots_range
  check (worker_parallel_slots between 1 and 8);
comment on column public.app_settings.worker_parallel_slots is
  'Concurrent jobs the worker runs per engine (image and video each get this many slots).';

update public.app_settings set max_concurrent_jobs_per_user = 10 where id = 1;
