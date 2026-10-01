-- Owners may read their own outputs from the private 'generations' bucket
-- (service role uploads them under {user_id}/{generation_id}/...).
create policy "generations_owner_read" on storage.objects for select
  using (bucket_id = 'generations' and (storage.foldername(name))[1] = auth.uid()::text);
