-- Verifies the DripPop schema on a Supabase local stack.
-- Run: eval "$(supabase status -o env)" && psql "$DB_URL" -v ON_ERROR_STOP=1 -f supabase/tests/verify.sql

do $$
declare
    b record;
    t record;
    pol_count int;
    priv record;
begin
    select * into b from storage.buckets where id = 'drippop-private';
    if not found then
        raise exception 'bucket drippop-private missing';
    end if;
    if b.public then
        raise exception 'bucket drippop-private must not be public';
    end if;

    for t in
        select c.relname from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relkind = 'r'
          and c.relname <> '_drippop_migrations'
    loop
        if not exists (
            select 1 from pg_class c2
            join pg_namespace n2 on n2.oid = c2.relnamespace
            where n2.nspname = 'public' and c2.relname = t.relname and c2.relrowsecurity
        ) then
            raise exception 'RLS not enabled on public.%', t.relname;
        end if;
    end loop;

    select count(*) into pol_count from pg_policies where schemaname = 'public';
    if pol_count <> 0 then
        raise exception 'expected zero RLS policies in public schema, found %', pol_count;
    end if;

    for priv in
        select grantee, table_name from information_schema.role_table_grants
        where table_schema = 'public' and grantee in ('anon','authenticated')
    loop
        raise exception 'unexpected privilege % on % for %', priv.table_name, priv.grantee, priv.table_name;
    end loop;

    for t in
        select c.relname from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relkind = 'S'
    loop
        if has_sequence_privilege('anon', 'public.' || t.relname, 'USAGE')
           or has_sequence_privilege('authenticated', 'public.' || t.relname, 'USAGE') then
            raise exception 'anon/authenticated has USAGE on sequence public.%', t.relname;
        end if;
    end loop;
end $$;
