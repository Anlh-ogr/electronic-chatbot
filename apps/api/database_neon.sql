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


-- ============================================================
-- MIGRATION: Add Circuit IR, Artifacts, and Composition tables
-- ============================================================

-- 10. Circuit IRs Table
-- Luu IR JSON da validate tu LLM. Tach khoi snapshots de co
-- the query, ghep, va tai su dung doc lap.
create table if not exists circuit_irs (
	ir_id           uuid primary key default uuid_generate_v4(),
	circuit_id      uuid not null references circuits(circuit_id) on delete cascade,
	session_id      uuid references sessions(session_id) on delete set null,
	message_id      uuid references messages(message_id) on delete set null,

	-- Toan bo IR JSON da validate va fix (sau khi qua CircuitIRValidator)
	ir_json         jsonb not null,

	-- Metadata tom tat de query nhanh, khong can parse jsonb
	topology_type   varchar(64),          -- 'Single-stage', 'Multi-stage', 'Hybrid'
	circuit_name    varchar(255),
	stage_count     integer default 1,
	power_rail      varchar(64),          -- 'Single (VCC-GND)', 'Symmetric (VCC-VEE)'
	probe_nodes     text[],               -- ['IN', 'OUT'] de Ngspice biet can do dau

	-- Trang thai vong doi
	status          varchar(32) not null default 'pending'
					check (status in ('pending', 'validated', 'compiled', 'failed')),
	is_kept         boolean not null default false, -- User da "Giu lai" IR nay chua?

	created_at      timestamptz not null default now(),
	embedding_vector vector(1536)
);

create index if not exists idx_circuit_irs_circuit_id
	on circuit_irs(circuit_id, created_at desc);
create index if not exists idx_circuit_irs_session_kept
	on circuit_irs(session_id, is_kept)
	where is_kept = true;
create index if not exists idx_circuit_irs_status
	on circuit_irs(status);
create index if not exists idx_circuit_irs_embedding
	on circuit_irs using hnsw(embedding_vector vector_cosine_ops);


-- 11. Circuit Artifacts Table
-- Luu duong dan file output (.kicad_sch, .kicad_pcb, .cir, .raw)
-- duoc sinh ra tu moi IR.
create table if not exists circuit_artifacts (
	artifact_id     uuid primary key default uuid_generate_v4(),
	ir_id           uuid not null references circuit_irs(ir_id) on delete cascade,
	circuit_id      uuid not null references circuits(circuit_id) on delete cascade,

	artifact_type   varchar(32) not null
					check (artifact_type in (
						'kicad_sch', 'kicad_pcb', 'netlist',
						'spice_deck', 'simulation_raw', 'simulation_png'
					)),
	file_path       text not null,          -- Duong dan tren disk hoac object storage
	download_url    text,                   -- URL public de frontend/KiCanvas fetch
	file_size_bytes bigint,
	kicad_version   varchar(16) default '8.0',

	created_at      timestamptz not null default now()
);

create index if not exists idx_artifacts_ir_id
	on circuit_artifacts(ir_id);
create index if not exists idx_artifacts_circuit_type
	on circuit_artifacts(circuit_id, artifact_type);


-- 12. Circuit Compositions Table
-- Bang trung tam cho luong "Ghep mach" (req3 trong yeu cau).
-- Mot Composition la tap hop nhieu IR da duoc "Giu lai" (is_kept=true)
-- duoc nguoi dung yeu cau ghep lai thanh mot mach lon hon.
create table if not exists circuit_compositions (
	composition_id  uuid primary key default uuid_generate_v4(),
	session_id      uuid references sessions(session_id) on delete set null,
	chat_id         uuid references chats(chat_id) on delete set null,

	-- IR tong hop cuoi cung sau khi ghep
	merged_ir_json  jsonb,
	merged_ir_id    uuid references circuit_irs(ir_id) on delete set null,

	coupling_method varchar(32) not null default 'RC Coupling'
					check (coupling_method in (
						'RC Coupling', 'Direct Coupling', 'Transformer Coupling'
					)),

	status          varchar(32) not null default 'pending'
					check (status in ('pending', 'merging', 'compiled', 'failed')),
	merge_notes     text,    -- AI giai thich ly do chon coupling method nay

	created_at      timestamptz not null default now(),
	updated_at      timestamptz not null default now()
);

-- Bang con: Danh sach cac IR thanh phan tham gia vao 1 Composition
create table if not exists composition_members (
	member_id       uuid primary key default uuid_generate_v4(),
	composition_id  uuid not null references circuit_compositions(composition_id)
					on delete cascade,
	ir_id           uuid not null references circuit_irs(ir_id) on delete cascade,
	stage_order     integer not null default 0,  -- Thu tu ghep noi (0=tang dau vao)
	unique(composition_id, ir_id)
);

create index if not exists idx_composition_members_comp
	on composition_members(composition_id, stage_order);

drop trigger if exists trg_compositions_set_updated_at on circuit_compositions;
create trigger trg_compositions_set_updated_at
	before update on circuit_compositions
	for each row
	execute function set_updated_at();


-- 13. Cap nhat bang snapshots de gan ir_id
-- (Snapshots hien tai luu circuit_data tho,
--  nay bo sung FK sang circuit_irs de truy vet)
alter table snapshots
	add column if not exists ir_id uuid
		references circuit_irs(ir_id) on delete set null;

create index if not exists idx_snapshots_ir_id
	on snapshots(ir_id);
