-- 0001_temporal_rebuild.sql
-- Full replacement persistence schema for durable orchestration.

begin;

create extension if not exists "uuid-ossp";

create table if not exists documents (
  doc_id uuid primary key,
  filename text not null,
  file_hash text not null unique,
  status text not null,
  progress int not null default 0 check (progress >= 0 and progress <= 100),
  message text not null default '',
  workflow_id text not null unique,
  run_id text,
  source_pdf_path text,
  output_md_path text,
  parser_backend text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_documents_status on documents(status);
create index if not exists idx_documents_updated_at on documents(updated_at desc);

create table if not exists expected_nodes (
  doc_id uuid not null references documents(doc_id) on delete cascade,
  node_id text not null,
  parent_node_id text,
  level int not null,
  topic text not null,
  content_text text not null default '',
  content_hash text not null,
  content_length int not null default 0,
  breadcrumbs text not null default '',
  created_at timestamptz not null default now(),
  primary key (doc_id, node_id)
);

create index if not exists idx_expected_nodes_doc on expected_nodes(doc_id);

create table if not exists node_results (
  doc_id uuid not null references documents(doc_id) on delete cascade,
  node_id text not null,
  status text not null,
  attempt int not null default 0,
  error_code text,
  error_message text,
  payload_json jsonb,
  payload_hash text,
  started_at timestamptz,
  finished_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (doc_id, node_id)
);

create index if not exists idx_node_results_doc_status on node_results(doc_id, status);

create table if not exists node_attempt_logs (
  doc_id uuid not null references documents(doc_id) on delete cascade,
  node_id text not null,
  attempt int not null,
  status text not null,
  error_code text,
  error_message text,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  duration_ms int,
  provider text,
  model text,
  request_id text,
  primary key (doc_id, node_id, attempt)
);

create index if not exists idx_node_attempt_logs_doc on node_attempt_logs(doc_id);

create table if not exists exports (
  doc_id uuid primary key references documents(doc_id) on delete cascade,
  integrity text not null,
  success_nodes int not null default 0,
  failed_nodes int not null default 0,
  markdown_path text,
  source_index_path text,
  exported_at timestamptz not null default now(),
  metadata_json jsonb not null default '{}'::jsonb
);

create table if not exists processing_events (
  event_id bigserial primary key,
  doc_id uuid not null references documents(doc_id) on delete cascade,
  event_type text not null,
  event_level text not null default 'info',
  payload_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_processing_events_doc_time on processing_events(doc_id, created_at desc);

create or replace function touch_updated_at() returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_documents_touch_updated_at on documents;
create trigger trg_documents_touch_updated_at
before update on documents
for each row
execute function touch_updated_at();

commit;
