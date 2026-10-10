-- 033_operational_run_lease.sql
-- Server-side fail-closed lease for the degraded real-signal operational runner.
-- No collector execution, editorial publication, or scientific data mutation.

create table raw.operational_run_leases (
    lease_name text primary key,
    token uuid not null unique,
    holder text not null,
    acquired_at timestamptz not null default now(),

    constraint operational_run_leases_name_check
        check (char_length(btrim(lease_name)) between 1 and 120),
    constraint operational_run_leases_holder_check
        check (char_length(btrim(holder)) between 1 and 120)
);

alter table raw.operational_run_leases enable row level security;

revoke all on table raw.operational_run_leases
    from public, anon, authenticated, service_role;

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

    return v_token = p_token;
end;
$$;

create or replace function public.release_operational_run_lease(
    p_lease_name text,
    p_token uuid
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

    select token
      into v_token
      from raw.operational_run_leases
     where lease_name = p_lease_name
     for update;

    if not found then
        return true;
    end if;

    if v_token <> p_token then
        return false;
    end if;

    delete from raw.operational_run_leases
     where lease_name = p_lease_name
       and token = p_token;

    return true;
end;
$$;

revoke all on function public.acquire_operational_run_lease(text, uuid, text)
    from public, anon, authenticated;
revoke all on function public.release_operational_run_lease(text, uuid)
    from public, anon, authenticated;

grant execute on function public.acquire_operational_run_lease(text, uuid, text)
    to service_role;
grant execute on function public.release_operational_run_lease(text, uuid)
    to service_role;

comment on table raw.operational_run_leases is
    'Fail-closed singleton leases for scheduled operational workers; no automatic expiry or takeover.';

comment on function public.acquire_operational_run_lease(text, uuid, text) is
    'Atomically acquires or idempotently confirms an operational lease; refuses while any pipeline run is marked running.';

comment on function public.release_operational_run_lease(text, uuid) is
    'Idempotently releases an operational lease only for its owning token.';
