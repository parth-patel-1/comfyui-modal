-- RLS policies call public.is_admin(); policy evaluation runs as the
-- invoking role, so every role that can read the tables needs EXECUTE
-- on it (revoking from public removed the implicit grant).
grant execute on function public.is_admin() to anon, authenticated;
