-- 034_operational_run_lease_null_return_fix.sql
-- Correct competing acquisition to return false instead of SQL null.
-- No collector execution, publication, or scientific data mutation.

create or replace function public.acquire_operational_run_lease(
    p_lease_name text,
    p_token uuid,
    p_holder text
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_token uuid;
begin
    if p_token is null then
        raise exception 'operational lease token is required';
    end if;

    if p_lease_name is null
       or char_length(btrim(p_lease_name)) not between 1 and 120 then
        raise exception 'invalid operational lease name';
    end if;

    if p_holder is null
       or char_length(btrim(p_holder)) not between 1 and 120 then
        raise exception 'invalid operational lease holder';
    end if;

    if exists (
        select 1
        from raw.pipeline_runs
        where status = 'running'
    ) then
        return false;
    end if;

    insert into raw.operational_run_leases (
        lease_name,
        token,
        holder
    )
    values (
        p_lease_name,
        p_token,
        p_holder
    )
    on conflict (lease_name) do update
       set lease_name = excluded.lease_name
     where raw.operational_run_leases.token = excluded.token
    returning token into v_token;

    return coalesce(v_token = p_token, false);
end;
$$;

revoke all on function public.acquire_operational_run_lease(text, uuid, text)
    from public, anon, authenticated;

grant execute on function public.acquire_operational_run_lease(text, uuid, text)
    to service_role;

comment on function public.acquire_operational_run_lease(text, uuid, text) is
    'Atomically acquires or idempotently confirms an operational lease; returns false on competing ownership or while any pipeline run is marked running.';
