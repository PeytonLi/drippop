-- DripPop initial schema. Applies on plain Postgres 17 and Supabase.
-- Supabase-only statements are guarded so the file is a no-op-safe elsewhere.

create table public.jobs (
    job_id text primary key check (job_id ~ '^[A-Za-z0-9_-]{16,64}$'),
    owner_uid text not null,
    status text not null check (status in ('queued','processing','succeeded','failed','canceled')),
    phase text not null check (phase in ('queued','preparing','generating','finalizing')),
    internal_state text not null check (internal_state in ('queued','ready_to_submit','submitting','polling','finalizing','succeeded','failed','submission_unknown','canceled')),
    garment_category text not null,
    request_hash text not null,
    phase_version integer not null default 0,
    provider text,
    provider_task_id text,
    provider_output_url text,
    submission_marker_at timestamptz,
    check_count integer not null default 0,
    error_code text check (error_code is null or error_code in (
        'invalid_image','unsupported_reference','analysis_unavailable','active_job_exists',
        'quota_exceeded','idempotency_conflict','provider_rejected','generation_status_unknown',
        'generation_timeout','result_expired','job_canceled','unauthenticated','not_found',
        'invalid_request','category_unavailable','service_unavailable')),
    result_object_path text,
    result_mime text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deadline_at timestamptz not null,
    expires_at timestamptz not null,
    records_expire_at timestamptz not null,
    canceled_at timestamptz,
    tombstoned_at timestamptz,
    finished_at timestamptz
);
create unique index jobs_one_active_per_owner
    on public.jobs (owner_uid) where status in ('queued','processing');
create index jobs_owner_uid_idx on public.jobs (owner_uid);

create table public.idempotency_records (
    owner_uid text not null,
    key_hash text not null,
    request_hash text not null,
    job_id text not null references public.jobs (job_id) on delete cascade,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    primary key (owner_uid, key_hash)
);

create table public.job_dispatch (
    id bigserial primary key,
    job_id text not null references public.jobs (job_id) on delete cascade,
    kind text not null check (kind in ('advance','cleanup')),
    phase_version integer not null,
    run_after timestamptz not null default now(),
    lease_token uuid,
    lease_expires_at timestamptz,
    attempts integer not null default 0,
    max_attempts integer not null,
    last_error text,
    created_at timestamptz not null default now(),
    completed_at timestamptz,
    unique (job_id, kind, phase_version)
);
create index job_dispatch_claim_idx
    on public.job_dispatch (run_after, id) where completed_at is null;

create table public.budget_days (
    day date primary key,
    paid_attempts integer not null default 0
);

create table public.budget_reservations (
    job_id text primary key references public.jobs (job_id) on delete cascade,
    day date not null,
    status text not null check (status in ('reserved','consumed','released')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table public.usage_counters (
    scope text not null,
    day date not null,
    count integer not null default 0,
    primary key (scope, day)
);

create table public.stored_objects (
    path text primary key,
    job_id text not null references public.jobs (job_id) on delete cascade,
    kind text not null check (kind in ('person','reference','result')),
    mime text not null,
    byte_size integer not null,
    sha256 text not null,
    created_at timestamptz not null default now(),
    deleted_at timestamptz
);

alter table public.jobs enable row level security;
alter table public.idempotency_records enable row level security;
alter table public.job_dispatch enable row level security;
alter table public.budget_days enable row level security;
alter table public.budget_reservations enable row level security;
alter table public.usage_counters enable row level security;
alter table public.stored_objects enable row level security;

-- Supabase-only: revoke table privileges from the API roles and create the
-- private storage bucket. Guarded so plain Postgres skips them.
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon')
       and exists (select 1 from pg_roles where rolname = 'authenticated') then
        revoke all on all tables in schema public from anon, authenticated;
        revoke all on all sequences in schema public from anon, authenticated;
        revoke all on all functions in schema public from anon, authenticated;
        alter default privileges in schema public revoke all on tables from anon, authenticated;
        alter default privileges in schema public revoke all on sequences from anon, authenticated;
        alter default privileges in schema public revoke all on functions from anon, authenticated;
    end if;
end $$;

do $$
begin
    if to_regclass('storage.buckets') is not null then
        insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
        values ('drippop-private','drippop-private', false, 15000000,
                array['image/jpeg','image/png'])
        on conflict (id) do nothing;
    end if;
end $$;
