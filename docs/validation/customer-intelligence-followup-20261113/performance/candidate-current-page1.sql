
    WITH matched AS (
      SELECT CASE
 WHEN b.compact #>> '{project_metadata,asset_identity,kind}' = 'us_well_api'
  AND b.compact #>> '{project_metadata,asset_identity,identity_validated}' = 'true'
  AND b.compact #>> '{project_metadata,asset_identity,value}' ~ '^[0-9]{10}([0-9]{2}){0,2}$'
 THEN 'api:' || (b.compact #>> '{project_metadata,asset_identity,value}')
 ELSE 'project:' || b.project_id::text END AS asset_key, b.project_id, b.need_id,
             coalesce((CAST(%(need_alias_map)s AS jsonb)->>b.need_id::text)::uuid, b.need_id)
               AS canonical_need_id,
             b.compact - ARRAY['customer_facts', 'customer_developments', 'customer_priority', 'contact_actions', 'contact_people']::text[] AS compact,
             (CASE WHEN jsonb_typeof(b.compact->'contact_actions')='array'
                     THEN jsonb_array_length(b.compact->'contact_actions') > 0 ELSE false END
               OR CASE WHEN jsonb_typeof(b.compact->'contact_people')='array'
                     THEN jsonb_array_length(b.compact->'contact_people') > 0 ELSE false END)
               AS has_contact_actions,
             CASE WHEN b.compact #>> '{customer_priority,score}' ~ '^[0-9]{1,3}$'
                    AND b.compact #>> '{customer_priority,confidence}' ~ '^[1-9][0-9]{0,2}$'
                  THEN least(100, (b.compact #>> '{customer_priority,score}')::integer)
                  ELSE NULL END AS commercial_score,
             b.rank_score, b.updated_at
      FROM browse_rows b WHERE b.generation_id = %(generation)s
    ), candidate_assets AS (
      SELECT asset_key, min(project_id::text) AS anchor_project_id
      FROM matched GROUP BY asset_key
    ), all_rows AS (SELECT * FROM matched), assets AS (
      SELECT a.asset_key, c.anchor_project_id,
             count(DISTINCT canonical_need_id)::integer AS need_count,
             count(DISTINCT canonical_need_id) FILTER (
               WHERE need_id = ANY(CAST(%(eligible_need_ids)s AS uuid[]))
             )::integer AS eligible_need_count,
             count(DISTINCT canonical_need_id) FILTER (
               WHERE canonical_need_id = ANY(CAST(%(pursued_need_ids)s AS uuid[]))
             )::integer AS pursued_eligible_need_count,
             max(CASE WHEN %(shortlist_enabled)s THEN
               coalesce((CAST(%(priority_map)s AS jsonb)->>need_id::text)::integer, 0)
               ELSE rank_score END)::integer AS priority_score,
             max(updated_at) AS updated_at
      FROM all_rows a JOIN candidate_assets c USING (asset_key)
      GROUP BY a.asset_key, c.anchor_project_id
    ), representatives AS (
      SELECT DISTINCT ON (asset_key) asset_key,
        compact #>> '{project_metadata,oil_gas,operator_number}' AS operator_number,
        compact #>> '{project_metadata,operator}' AS operator_name,
        compact #>> '{project_metadata,title}' AS project_title,
        compact->>'browse_title' AS browse_title,
        compact #>> '{project_metadata,sector}' AS sector
      FROM all_rows ORDER BY asset_key, rank_score DESC, updated_at DESC, need_id
    ), membership_candidates AS (
      SELECT DISTINCT r.asset_key, r.project_id,
             r.compact #>> '{project_metadata,sector}' AS sector,
             bcm.company_identity_id::text AS company_id,
             ci.rrc_operator_number, bcm.organization_name, bcm.role,
             array_position(ARRAY['owner_developer','owner_energy','owner_construction','asset_operator','project_customer']::text[], bcm.role) AS role_priority
      FROM all_rows r JOIN browse_customer_memberships bcm
        ON bcm.generation_id = %(generation)s AND bcm.project_id = r.project_id
      LEFT JOIN company_identities ci ON ci.id = bcm.company_identity_id
      WHERE bcm.role = ANY(ARRAY['owner_developer','owner_energy','owner_construction','asset_operator','project_customer']::text[])
    ), membership_role_families AS (
      SELECT mc.*,
        CASE
          WHEN mc.sector = 'oil_gas' THEN
            CASE WHEN mc.role='asset_operator' THEN 0
                 WHEN mc.role = ANY(ARRAY['owner_developer','owner_energy','owner_construction']::text[]) THEN 1
                 ELSE 99 END
          WHEN mc.sector = 'data_centers' THEN
            CASE WHEN mc.role = ANY(ARRAY['owner_developer','owner_energy','owner_construction']::text[]) THEN 0
                 WHEN mc.role='project_customer' THEN 1
                 ELSE 2 END
          ELSE 0
        END AS family_priority
      FROM membership_candidates mc
    ), membership_role_priorities AS (
      SELECT mf.*,
             min(family_priority) OVER (PARTITION BY project_id) AS preferred_family
      FROM membership_role_families mf
    ), membership_project_roles AS (
      SELECT * FROM membership_role_priorities
      WHERE family_priority=preferred_family AND family_priority < 99
    ), memberships AS (
      SELECT DISTINCT asset_key, company_id, rrc_operator_number,
             organization_name, role, role_priority
      FROM membership_project_roles
    ), membership_conflicts AS (
      SELECT asset_key, min(organization_name) AS organization_name
      FROM memberships GROUP BY asset_key HAVING count(DISTINCT company_id) > 1
    ), single_membership AS (
      SELECT asset_key, min(company_id) AS company_id,
             min(rrc_operator_number) AS rrc_operator_number,
             (array_agg(organization_name ORDER BY role_priority, lower(organization_name),
                        organization_name))[1] AS organization_name,
             (array_agg(role ORDER BY role_priority, lower(organization_name),
                        organization_name))[1] AS role
      FROM memberships GROUP BY asset_key HAVING count(DISTINCT company_id) = 1
    ), recorded_conflicts AS (
      SELECT r.asset_key, min(uc.organization_name) AS organization_name
      FROM all_rows r JOIN browse_unresolved_customers uc
        ON uc.generation_id = %(generation)s AND uc.project_id = r.project_id
      WHERE uc.role = 'conflicting_customer'
      GROUP BY r.asset_key
    ), rrc_membership_conflicts AS (
      SELECT r.asset_key, min(sm.organization_name) AS organization_name
      FROM all_rows r JOIN single_membership sm ON sm.asset_key = r.asset_key
      WHERE lower(sm.role) LIKE '%%operator%%'
        AND nullif(r.compact #>> '{project_metadata,oil_gas,operator_number}', '')
              ~ '^[0-9]+$'
        AND sm.rrc_operator_number IS NOT NULL
        AND r.compact #>> '{project_metadata,oil_gas,operator_number}'
              <> sm.rrc_operator_number
      GROUP BY r.asset_key
    ), unresolved_conflicts AS (
      SELECT asset_key, min(organization_name) AS organization_name
      FROM (
        SELECT asset_key, organization_name FROM membership_conflicts
        UNION ALL
        SELECT asset_key, organization_name FROM recorded_conflicts
        UNION ALL
        SELECT asset_key, organization_name FROM rrc_membership_conflicts
      ) conflicts GROUP BY asset_key
    ), same_name_asset_eligible AS (
      SELECT DISTINCT r.asset_key, sm.company_id, sm.organization_name, sm.role
      FROM all_rows r
      JOIN single_membership sm ON sm.asset_key = r.asset_key
      LEFT JOIN unresolved_conflicts uc ON uc.asset_key = r.asset_key
      WHERE uc.asset_key IS NULL
        AND NOT EXISTS (
          SELECT 1 FROM all_rows nr
          WHERE nr.asset_key = r.asset_key
            AND nullif(nr.compact #>> '{project_metadata,oil_gas,operator_number}', '')
                ~ '^[0-9]+$'
        )
        AND sm.role = 'owner_developer'
        AND nullif(sm.organization_name, '') IS NOT NULL
        AND r.compact #>> '{project_metadata,sector}' = 'data_centers'
        AND convert_to(
          r.compact #>> '{project_metadata,data_center,owner_developer}', 'UTF8'
        ) = convert_to(sm.organization_name, 'UTF8')
        AND r.compact #>> '{project_metadata,event,source}' = 'texas-tdlr-tabs-data-centers'
        AND CASE
          WHEN jsonb_typeof(r.compact #> '{project_metadata,event,evidence_refs}') = 'array'
          THEN jsonb_array_length(r.compact #> '{project_metadata,event,evidence_refs}') > 0
          ELSE false
        END
        -- An asset may enter a presentation bucket only when every project
        -- represented by that canonical asset meets the same strict rule.
        AND NOT EXISTS (
          SELECT 1 FROM all_rows nr
          WHERE nr.asset_key = r.asset_key AND (
            nr.compact #>> '{project_metadata,sector}' = 'data_centers'
            AND convert_to(
              nr.compact #>> '{project_metadata,data_center,owner_developer}', 'UTF8'
            ) = convert_to(sm.organization_name, 'UTF8')
            AND nr.compact #>> '{project_metadata,event,source}' = 'texas-tdlr-tabs-data-centers'
            AND CASE
              WHEN jsonb_typeof(nr.compact #> '{project_metadata,event,evidence_refs}') = 'array'
              THEN jsonb_array_length(nr.compact #> '{project_metadata,event,evidence_refs}') > 0
              ELSE false
            END
          ) IS NOT TRUE
        )
    ), same_name_eligible AS (
      -- Require every asset attached to this company UUID to be eligible.
      -- This prevents a good TDLR project from pulling unsupported siblings
      -- into the same-name display collection.
      SELECT candidate.* FROM same_name_asset_eligible candidate
      WHERE NOT EXISTS (
        SELECT 1 FROM assets ca
        JOIN single_membership csm ON csm.asset_key = ca.asset_key
        WHERE csm.company_id = candidate.company_id
          AND NOT EXISTS (
            SELECT 1 FROM same_name_asset_eligible eligible
            WHERE eligible.asset_key = ca.asset_key
              AND eligible.company_id = csm.company_id
              AND eligible.role = candidate.role
              AND convert_to(eligible.organization_name, 'UTF8') =
                  convert_to(candidate.organization_name, 'UTF8')
          )
      )
    ), same_name_bucket_defs AS (
      SELECT convert_to(organization_name, 'UTF8') AS organization_name_bytes, role,
             min(organization_name) AS organization_name,
             count(DISTINCT company_id)::integer AS identity_count
      FROM same_name_eligible
      GROUP BY convert_to(organization_name, 'UTF8'), role
      HAVING count(DISTINCT company_id) > 1
    ), same_name_bucket_assets AS (
      SELECT DISTINCT e.asset_key,
             'namebucket:' || e.role || ':' || encode(e.organization_name_bytes, 'hex')
               AS display_key,
             d.identity_count
      FROM (
        SELECT e.*, convert_to(e.organization_name, 'UTF8') AS organization_name_bytes
        FROM same_name_eligible e
      ) e
      JOIN same_name_bucket_defs d
        USING (organization_name_bytes, role)
    ), assigned AS (
      SELECT a.*, sm.company_id, sm.organization_name, sm.role AS membership_role,
             uc.organization_name AS unresolved_name,
             nb.display_key AS display_container_key, nb.identity_count,
        CASE WHEN nb.display_key IS NOT NULL THEN nb.display_key
             WHEN uc.asset_key IS NOT NULL THEN 'conflict:' || a.asset_key
             WHEN sm.rrc_operator_number IS NOT NULL
               THEN 'rrc:' || sm.rrc_operator_number
             WHEN nullif(r.operator_number, '') ~ '^[0-9]+$'
               THEN 'rrc:' || r.operator_number
             WHEN sm.company_id IS NOT NULL THEN 'company:' || sm.company_id
             ELSE 'unresolved:' || a.asset_key END AS group_key,
        CASE WHEN uc.asset_key IS NOT NULL THEN 'conflict:' || a.asset_key
             WHEN sm.rrc_operator_number IS NOT NULL
               THEN 'rrc:' || sm.rrc_operator_number
             WHEN nullif(r.operator_number, '') ~ '^[0-9]+$'
               THEN 'rrc:' || r.operator_number
             WHEN sm.company_id IS NOT NULL THEN 'company:' || sm.company_id
             ELSE 'unresolved:' || a.asset_key END AS identity_key,
        CASE WHEN uc.asset_key IS NOT NULL
             THEN coalesce(nullif(r.project_title, ''), nullif(r.browse_title, ''),
                  'Unresolved project')
             WHEN nb.display_key IS NOT NULL THEN sm.organization_name
             WHEN sm.rrc_operator_number IS NOT NULL
               THEN coalesce(nullif(r.operator_name, ''), sm.organization_name)
             WHEN nullif(r.operator_number, '') ~ '^[0-9]+$'
               THEN coalesce(nullif(r.operator_name, ''), 'RRC operator ' || r.operator_number)
             WHEN sm.company_id IS NOT NULL THEN sm.organization_name
             ELSE coalesce(nullif(r.project_title, ''), nullif(r.browse_title, ''),
                    'Unresolved project') END AS group_name,
        CASE WHEN nb.display_key IS NOT NULL THEN 'unresolved'
             WHEN uc.asset_key IS NOT NULL THEN 'unresolved'
             WHEN nullif(r.operator_number, '') ~ '^[0-9]+$' THEN 'operator'
             WHEN sm.company_id IS NOT NULL AND lower(sm.role) LIKE '%%operator%%'
             THEN 'operator' WHEN sm.company_id IS NOT NULL THEN 'customer'
             ELSE 'unresolved' END AS group_role,
        CASE WHEN nb.display_key IS NOT NULL THEN 'same_name_unconfirmed'
             WHEN uc.asset_key IS NOT NULL THEN 'unresolved'
             WHEN sm.rrc_operator_number IS NOT NULL
               OR nullif(r.operator_number, '') ~ '^[0-9]+$' OR sm.company_id IS NOT NULL
               THEN 'resolved_identity'
             ELSE 'unresolved' END AS group_kind,
        coalesce(nullif(r.sector, ''), 'unknown') AS sector
      FROM assets a JOIN representatives r USING (asset_key)
      LEFT JOIN single_membership sm USING (asset_key)
      LEFT JOIN unresolved_conflicts uc USING (asset_key)
      LEFT JOIN same_name_bucket_assets nb USING (asset_key)
    ), eligible_assets AS (
      SELECT DISTINCT asset_key FROM all_rows
      WHERE need_id = ANY(CAST(%(eligible_need_ids)s AS uuid[]))
    ), grouped_need_counts AS (
      SELECT a.group_key, count(DISTINCT ar.canonical_need_id)::integer AS need_count,
        count(DISTINCT ar.canonical_need_id) FILTER (
          WHERE ar.need_id = ANY(CAST(%(eligible_need_ids)s AS uuid[]))
        )::integer AS eligible_need_count,
        count(DISTINCT ar.canonical_need_id) FILTER (
          WHERE ar.canonical_need_id = ANY(CAST(%(pursued_need_ids)s AS uuid[]))
        )::integer AS pursued_eligible_need_count,
        bool_or(ar.has_contact_actions) AS has_contact_actions,
        max(ar.commercial_score) AS commercial_score
      FROM assigned a JOIN all_rows ar ON ar.asset_key=a.asset_key
      GROUP BY a.group_key
    ), grouped AS (
      SELECT group_key, (array_agg(group_name ORDER BY group_name))[1] AS name,
        (array_agg(group_role ORDER BY group_role))[1] AS role,
        CASE WHEN bool_or(group_kind = 'same_name_unconfirmed')
             THEN 'same_name_unconfirmed'
             WHEN bool_or(group_kind = 'resolved_identity') THEN 'resolved_identity'
             ELSE 'unresolved' END AS group_kind,
        CASE WHEN bool_or(group_kind = 'same_name_unconfirmed')
             THEN max(identity_count)
             WHEN bool_or(group_kind = 'resolved_identity') THEN 1
             ELSE NULL END AS identity_count,
        max(priority_score)::integer AS priority_score,
        count(*)::integer AS project_count,
        gnc.need_count, gnc.eligible_need_count, gnc.pursued_eligible_need_count,
        gnc.has_contact_actions, gnc.commercial_score,
        count(*) FILTER (
          WHERE asset_key IN (SELECT asset_key FROM eligible_assets)
        )::integer AS relevant_project_count,
        array_agg(DISTINCT sector ORDER BY sector) AS sectors,
        max(updated_at) AS updated_at
      FROM assigned JOIN grouped_need_counts gnc USING (group_key)
      GROUP BY group_key, gnc.need_count, gnc.eligible_need_count,
               gnc.pursued_eligible_need_count, gnc.has_contact_actions, gnc.commercial_score
               
    )
    , page_rows AS MATERIALIZED (SELECT g.*, count(*) OVER() AS total, count(*) FILTER (WHERE g.group_kind='resolved_identity') OVER() AS account_total, coalesce(sum(g.project_count) OVER(),0) AS project_total, (SELECT count(DISTINCT ar.canonical_need_id) FROM assigned na JOIN all_rows ar ON ar.asset_key=na.asset_key WHERE na.group_key IN (SELECT g2.group_key FROM grouped g2 WHERE TRUE)) AS need_total FROM grouped g WHERE TRUE ORDER BY (commercial_score IS NOT NULL) DESC, commercial_score DESC NULLS LAST, priority_score DESC NULLS LAST, name, group_key LIMIT %(limit)s OFFSET %(offset)s), page_commercial_projects AS (SELECT p.group_key, jsonb_agg(DISTINCT jsonb_build_object('project_id', ar.project_id, 'company_id', a.company_id, 'facts', coalesce(b.compact->'customer_facts', '[]'::jsonb), 'priority', b.compact->'customer_priority', 'developments', coalesce(b.compact->'customer_developments', '[]'::jsonb))) AS commercial_projects FROM page_rows p JOIN assigned a ON a.group_key=p.group_key JOIN all_rows ar ON ar.asset_key=a.asset_key JOIN browse_rows b ON b.generation_id=%(generation)s AND b.project_id=ar.project_id AND b.need_id=ar.need_id GROUP BY p.group_key) SELECT p.*, cp.commercial_projects FROM page_rows p LEFT JOIN page_commercial_projects cp USING (group_key) ORDER BY (commercial_score IS NOT NULL) DESC, commercial_score DESC NULLS LAST, priority_score DESC NULLS LAST, name, group_key
