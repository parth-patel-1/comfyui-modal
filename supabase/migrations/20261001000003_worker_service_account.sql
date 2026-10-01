-- Worker service account: uploads finished outputs to the 'generations'
-- bucket under its own folder (service_uid/{user_id}/{job_id}/file).
alter table public.profiles drop constraint profiles_role_check;
alter table public.profiles add constraint profiles_role_check
  check (role in ('user','admin','service'));

create policy "generations_service_write" on storage.objects for insert
  with check (
    bucket_id = 'generations'
    and exists (
      select 1 from public.profiles p
      where p.id = auth.uid() and p.role = 'service'
    )
  );

create policy "generations_service_read" on storage.objects for select
  using (
    bucket_id in ('generations', 'references')
    and exists (
      select 1 from public.profiles p
      where p.id = auth.uid() and p.role = 'service'
    )
  );

create policy "references_service_read" on storage.objects for select
  using (
    bucket_id = 'references'
    and exists (
      select 1 from public.profiles p
      where p.id = auth.uid() and p.role = 'service'
    )
  );
