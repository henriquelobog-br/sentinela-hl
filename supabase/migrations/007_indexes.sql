-- 007_indexes.sql — Sentinela HL — todos os indices.

-- raw
create index if not exists idx_sources_active on raw.sources(active) where active;
create index if not exists idx_fetch_runs_source on raw.fetch_runs(source_id);
create index if not exists idx_fetch_runs_started on raw.fetch_runs(started_at desc);
create unique index if not exists uq_items_source_external
  on raw.items(source_id, external_id) where external_id is not null;
create index if not exists idx_items_content_hash on raw.items(content_hash);
create index if not exists idx_items_status on raw.items(pipeline_status);
create index if not exists idx_items_collected on raw.items(collected_at desc);

-- knowledge.claims
create index if not exists idx_claims_raw_item on knowledge.claims(raw_item_id);
create index if not exists idx_claims_status on knowledge.claims(pipeline_status);
create index if not exists idx_claims_epistemic on knowledge.claims(epistemic_status);
create index if not exists idx_claims_review on knowledge.claims(requires_human_review)
  where requires_human_review;

-- knowledge.classifications
create unique index if not exists uq_classification_claim_filter
  on knowledge.classifications(claim_id, filter);
create index if not exists idx_classifications_result on knowledge.classifications(result);

-- knowledge.events
create index if not exists idx_events_epistemic on knowledge.events(epistemic_status);
create index if not exists idx_events_occurred on knowledge.events(occurred_at desc);
create index if not exists idx_events_review on knowledge.events(review_decision);
create index if not exists idx_events_category on knowledge.events(category);

-- knowledge.contradictions
create index if not exists idx_contradictions_claim on knowledge.contradictions(claim_id);
create index if not exists idx_contradictions_event on knowledge.contradictions(conflicting_event_id);
create index if not exists idx_contradictions_unresolved on knowledge.contradictions(resolved)
  where not resolved;

-- knowledge.bulletins
create index if not exists idx_bulletins_status on knowledge.bulletins(status);
create index if not exists idx_bulletin_events_event on knowledge.bulletin_events(event_id);
