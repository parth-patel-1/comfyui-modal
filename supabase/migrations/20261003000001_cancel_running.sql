-- Cancel a queued/provisioning/running job (owner or admin); refunds credits.
-- For a running job the worker notices the status change, aborts the ComfyUI
-- prompt (/interrupt) and skips settling, so the refund is final.
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
  if v_status not in ('queued','provisioning','running') then
    raise exception 'JOB_ALREADY_FINISHED';
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
      (v_user, v_credits, v_balance, 'generation_refund', p_generation_id,
       case when v_status = 'running' then 'canceled while running'
            else 'canceled before start' end);
  end if;
end
$fn$;
