-- 1. Timezone
alter database neondb set timezone to 'Asia/Ho_Chi_Minh';

-- 2. Extensions
create extension if not exists "uuid-ossp";
create extension if not exists vector;

-- 3. Sessions Table
create table if not exists sessions (
	session_id uuid primary key default uuid_generate_v4(),
	client_ip inet,
	user_agent text,
	created_at timestamptz not null default now(),
	last_active timestamptz not null default now()
);

-- 4. Chats Table
create table if not exists chats (
	chat_id uuid primary key default uuid_generate_v4(),
	session_id uuid not null references sessions(session_id) on delete cascade,
	title varchar(255) not null default 'New Chat',
	created_at timestamptz not null default now(),
	updated_at timestamptz not null default now()
);

-- 5. Chat Summaries Table
create table if not exists chat_summaries (
	summary_id uuid primary key default uuid_generate_v4(),
	chat_id uuid not null references chats(chat_id) on delete cascade,
	summary_text text not null,
	token_estimate integer not null default 0 check (token_estimate >= 0),
	source_message_count integer not null default 0 check (source_message_count >= 0),
	embedding_vector vector(1536),
	created_at timestamptz not null default now()
);
create index if not exists idx_chat_summaries_created_at
	on chat_summaries (chat_id, created_at desc);

-- 6. Messages Table
create table if not exists messages (
	message_id uuid primary key default uuid_generate_v4(),
	chat_id uuid not null references chats(chat_id) on delete cascade,
	role varchar(32) not null check (role in ('user', 'assistant', 'system', 'tool')),
	content text not null,
	status varchar(32) not null default 'created'
		check (status in ('created', 'streaming', 'completed', 'failed', 'edited', 'deleted')),
	created_at timestamptz not null default now(),
	prompt_tokens integer not null default 0 check (prompt_tokens >= 0),
	completion_tokens integer not null default 0 check (completion_tokens >= 0),
	embedding_vector vector(1536),
	total_cost numeric(12, 6) not null default 0 check (total_cost >= 0),
	model_used varchar(100)
);

-- 7. Memory Facts Table
create table if not exists memory_facts (
	memory_id uuid primary key default uuid_generate_v4(),
	session_id uuid not null references sessions(session_id) on delete cascade,
	chat_id uuid references chats(chat_id) on delete set null,
	fact_key varchar(255) not null,
	fact_value text not null,
	confidence real not null default 0.5 check (confidence >= 0 and confidence <= 1),
	is_active boolean not null default true
);
create unique index if not exists uq_memory_facts_with_chat
	on memory_facts (session_id, chat_id, fact_key)
	where chat_id is not null;
create unique index if not exists uq_memory_facts_no_chat
	on memory_facts (session_id, fact_key)
	where chat_id is null;

-- 8. Circuits Table
create table if not exists circuits (
	circuit_id uuid primary key default uuid_generate_v4(),
	session_id uuid references sessions(session_id) on delete set null,
	message_id uuid references messages(message_id) on delete set null,
	name varchar(255) not null,
	description text,
	created_at timestamptz not null default now(),
	updated_at timestamptz not null default now(),
	embedding_vector vector(1536)
);

-- 9. Snapshots Table
create table if not exists snapshots (
	snapshot_id uuid primary key default uuid_generate_v4(),
	circuit_id uuid not null references circuits(circuit_id) on delete cascade,
	message_id uuid references messages(message_id) on delete set null,
	circuit_data jsonb not null,
	created_at timestamptz not null default now()
);

create or replace function set_updated_at()
returns trigger
language plpgsql
as $$
begin
	new.updated_at = now();
	return new;
end;
$$;

drop trigger if exists trg_chats_set_updated_at on chats;
create trigger trg_chats_set_updated_at
before update on chats
for each row
execute function set_updated_at();

drop trigger if exists trg_circuits_set_updated_at on circuits;
create trigger trg_circuits_set_updated_at
before update on circuits
for each row
execute function set_updated_at();

create index if not exists idx_sessions_last_active on sessions(last_active desc);
create index if not exists idx_chats_session_id on chats(session_id);
create index if not exists idx_chats_updated_at on chats(updated_at desc);
create index if not exists idx_chat_summaries_chat_id on chat_summaries(chat_id);
create index if not exists idx_chat_summaries_embedding on chat_summaries using hnsw(embedding_vector vector_cosine_ops);
create index if not exists idx_messages_chat_id_created_at on messages(chat_id, created_at);
create index if not exists idx_messages_embedding on messages using hnsw(embedding_vector vector_cosine_ops);
create index if not exists idx_messages_status on messages(status);
create index if not exists idx_memory_facts_session_active on memory_facts(session_id, is_active);
create index if not exists idx_memory_facts_chat_active on memory_facts(chat_id, is_active);
create index if not exists idx_circuits_session_id on circuits(session_id);
create index if not exists idx_circuits_embedding on circuits using hnsw(embedding_vector vector_cosine_ops);
create index if not exists idx_snapshots_circuit_created on snapshots(circuit_id, created_at desc);
