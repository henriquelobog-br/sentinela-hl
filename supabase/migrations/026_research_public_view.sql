-- 026_research_public_view.sql
-- Read-only server-side contract for curator-approved ResearchWorks.

create view public.v_research_works
with (security_invoker = true)
as
select
    works.id,
    works.source,
    works.source_work_id,
    works.doi,
    works.title,
    works.work_type,
    works.publication_date,
    works.publication_year,
    works.language,
    works.primary_source_name,
    works.is_open_access,
    works.oa_status,
    authors.items as authors,
    topics.items as topics,
    citation.citation_count,
    citation.observed_at as citation_observed_at
from knowledge.research_works as works
join knowledge.research_work_publication_state as publication
  on publication.research_work_id = works.id
 and publication.publication_approved = true
left join lateral (
    select coalesce(
        jsonb_agg(
            jsonb_build_object(
                'position', author.position,
                'display_name', author.display_name,
                'openalex_author_id', author.openalex_author_id,
                'orcid', author.orcid
            )
            order by author.position
        ),
        '[]'::jsonb
    ) as items
    from knowledge.research_work_authors as author
    where author.research_work_id = works.id
) as authors on true
left join lateral (
    select coalesce(
        jsonb_agg(
            jsonb_build_object(
                'external_topic_id', topic.external_topic_id,
                'external_topic_name', topic.external_topic_name,
                'topic_rank', topic.topic_rank,
                'topic_score', topic.topic_score,
                'is_primary', topic.is_primary
            )
            order by topic.topic_rank, topic.external_topic_id
        ),
        '[]'::jsonb
    ) as items
    from knowledge.research_work_topics as topic
    where topic.research_work_id = works.id
) as topics on true
left join lateral (
    select
        observation.citation_count,
        observation.observed_at
    from knowledge.research_citation_observations as observation
    where observation.research_work_id = works.id
    order by observation.observed_at desc,
             observation.created_at desc,
             observation.id desc
    limit 1
) as citation on true;

alter view public.v_research_works owner to postgres;

revoke all on public.v_research_works
from public, anon, authenticated, service_role;

grant usage on schema knowledge to service_role;
grant select (
    id,
    source,
    source_work_id,
    doi,
    title,
    work_type,
    publication_date,
    publication_year,
    language,
    primary_source_name,
    is_open_access,
    oa_status
) on knowledge.research_works to service_role;
grant select (
    research_work_id,
    position,
    display_name,
    openalex_author_id,
    orcid
) on knowledge.research_work_authors to service_role;
grant select (
    research_work_id,
    external_topic_id,
    external_topic_name,
    topic_rank,
    topic_score,
    is_primary
) on knowledge.research_work_topics to service_role;
grant select (
    id,
    research_work_id,
    citation_count,
    observed_at,
    created_at
) on knowledge.research_citation_observations to service_role;
grant select (
    research_work_id,
    publication_approved
) on knowledge.research_work_publication_state to service_role;

grant select on public.v_research_works to service_role;

comment on view public.v_research_works is
    'Read-only server-side view of curator-approved canonical ResearchWorks.';
