-- =====================================================================
--  Yasui Flights: base de datos en Supabase
--  Pega TODO este archivo en Supabase > SQL Editor > New query > Run.
--  Se puede correr más de una vez sin problema.
-- =====================================================================

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------
-- Suscriptores: quién se apuntó y a dónde quiere ir
-- ---------------------------------------------------------------------
create table if not exists public.suscriptores (
  user_id            uuid primary key references auth.users(id) on delete cascade,
  email              text not null,
  nombre             text,
  destinos           jsonb not null default '[]'::jsonb,
  activo             boolean not null default true,
  bienvenida_enviada boolean not null default false,
  token_baja         uuid not null default gen_random_uuid(),
  creado             timestamptz not null default now(),
  actualizado        timestamptz not null default now(),
  constraint destinos_es_lista check (jsonb_typeof(destinos) = 'array'),
  constraint maximo_destinos  check (jsonb_array_length(destinos) <= 40),
  constraint nombre_corto     check (nombre is null or char_length(nombre) <= 60)
);

alter table public.suscriptores enable row level security;

drop policy if exists "suscriptor ve lo suyo"     on public.suscriptores;
drop policy if exists "suscriptor crea lo suyo"   on public.suscriptores;
drop policy if exists "suscriptor cambia lo suyo" on public.suscriptores;

create policy "suscriptor ve lo suyo" on public.suscriptores
  for select to authenticated using (auth.uid() = user_id);
create policy "suscriptor crea lo suyo" on public.suscriptores
  for insert to authenticated with check (auth.uid() = user_id);
create policy "suscriptor cambia lo suyo" on public.suscriptores
  for update to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- El email SIEMPRE es el de la cuenta que entró con el código:
-- nadie puede poner el email de otra persona.
-- Y los campos internos (token de baja, bienvenida) no los puede tocar el usuario.
create or replace function public.suscriptores_proteger() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  new.email := coalesce((select u.email from auth.users u where u.id = new.user_id), new.email);
  new.actualizado := now();
  if tg_op = 'UPDATE' then
    new.token_baja := old.token_baja;
    new.creado := old.creado;
    if coalesce(auth.role(), '') <> 'service_role' then
      new.bienvenida_enviada := old.bienvenida_enviada;
    end if;
  elsif coalesce(auth.role(), '') <> 'service_role' then
    new.bienvenida_enviada := false;
    new.token_baja := gen_random_uuid();
  end if;
  return new;
end $$;

drop trigger if exists suscriptores_proteger on public.suscriptores;
create trigger suscriptores_proteger before insert or update on public.suscriptores
  for each row execute function public.suscriptores_proteger();

-- ---------------------------------------------------------------------
-- Darse de baja con el link del email (sin tener que entrar)
-- ---------------------------------------------------------------------
create or replace function public.darse_de_baja(p_token uuid) returns boolean
language plpgsql security definer set search_path = public as $$
declare n int;
begin
  update public.suscriptores set activo = false where token_baja = p_token;
  get diagnostics n = row_count;
  return n > 0;
end $$;

revoke all on function public.darse_de_baja(uuid) from public;
grant execute on function public.darse_de_baja(uuid) to anon, authenticated;

-- ---------------------------------------------------------------------
-- Avisos ya enviados (para no repetir la misma oferta a la misma persona)
-- Sin políticas: solo el programa (con la secret key) la puede leer/escribir.
-- ---------------------------------------------------------------------
create table if not exists public.avisos (
  user_id uuid not null references auth.users(id) on delete cascade,
  clave   text not null,
  precio  numeric not null,
  fecha   timestamptz not null default now(),
  primary key (user_id, clave)
);

alter table public.avisos enable row level security;
