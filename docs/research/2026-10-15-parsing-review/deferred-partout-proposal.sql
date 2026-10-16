-- NOT REGISTERED / UNVALIDATED PROPOSAL
-- Preserved from PR4 head 8a86858d1d2d9fb4e7ced2b09381456cddf9f8a8
-- Excluded from schema/020_views.sql pending issue #16 semantic review.
-- Re-entry gates: available-only comparable selection; currency-separated comps
-- and totals; purchased quantities from sale_group_terms; explicit lot ask basis
-- normalization; and a supported DDR4 comp cohort (form factor/rank/speed plus
-- support and spread gates). Add regression SQL before registering any view.

-- Mixed DIMM lines are siblings (8×32 and 8×16), not parent/child. Sum only
-- the member lines that state both factors. A member that states a module
-- size but no count blocks the total — a partial sum would invent the rest.
CREATE VIEW v_group_ram AS
SELECT sg.id AS sale_group_id,
       sg.posting_id,
       CASE
           WHEN count(*) FILTER (
                    WHERE m.attributes ? 'ram_dimm_gb'
                      AND m.attributes->>'ram_dimm_gb' ~ '^[0-9]+(\.[0-9]+)?$'
                      AND m.stated_quantity IS NULL
                ) = 0
            AND count(*) FILTER (
                    WHERE m.attributes ? 'ram_dimm_gb'
                      AND m.attributes->>'ram_dimm_gb' ~ '^[0-9]+(\.[0-9]+)?$'
                      AND m.stated_quantity IS NOT NULL
                ) > 0
           THEN sum(m.stated_quantity * (m.attributes->>'ram_dimm_gb')::numeric)
                FILTER (
                    WHERE m.stated_quantity IS NOT NULL
                      AND m.attributes ? 'ram_dimm_gb'
                      AND m.attributes->>'ram_dimm_gb' ~ '^[0-9]+(\.[0-9]+)?$'
                )
       END AS ram_total_gb
FROM sale_groups sg
JOIN v_current_extractions c ON c.extraction_id = sg.extraction_id
JOIN sale_group_terms t ON t.sale_group_id = sg.id
JOIN lines m ON m.id = t.line_id
GROUP BY sg.id;

COMMENT ON VIEW v_group_ram IS 'Q1: RAM total across sibling member lines of one sale group (8×32 + 8×16). NULL when any DIMM line leaves its count unstated.';

-- Q3 part-out. Two numbers, kept apart:
--   exact_value  — stated quantity × cheapest standalone ask for the same product_key.
--   ram_rate_value — stated RAM gigabytes × the cheapest DDR4 $/GB from single-module comps.
-- The rate is an implication (one module size standing in for another). It is not
-- added into exact_value. A line with a total and no stick count gets a rate or nothing,
-- never a fabricated stick count. Lines with neither stay unpriced.
CREATE OR REPLACE VIEW v_ddr4_gb_rate AS
SELECT min(ca.unit_price / (ca.attributes->>'ram_dimm_gb')::numeric) AS usd_per_gb,
       count(*) AS comps,
       count(*) FILTER (WHERE ca.availability_state = 'available') AS comps_available
FROM v_cheapest_available ca
WHERE ca.unit_price IS NOT NULL
  AND ca.price_basis IN ('explicit_unit', 'homogeneous_division')
  AND (ca.member_line_count IS NULL OR ca.member_line_count = 1)
  AND ca.attributes->>'ram_dimm_gb' ~ '^[0-9]+(\.[0-9]+)?$'
  AND (ca.attributes->>'ram_dimm_gb')::numeric > 0
  AND COALESCE(ca.attributes->>'ram_type', ca.product_key, '') ILIKE '%ddr4%';

COMMENT ON VIEW v_ddr4_gb_rate IS 'Q3: cheapest observed dollars per gigabyte among standalone DDR4 modules. A rate, not a quote for a different size.';

CREATE OR REPLACE VIEW v_partout AS
WITH exact_comp AS (
    SELECT product_key,
           min(unit_price) AS unit_price,
           count(*)        AS comps,
           count(*) FILTER (WHERE availability_state = 'available') AS comps_available
    FROM v_cheapest_available
    WHERE unit_price IS NOT NULL
      AND price_basis IN ('explicit_unit', 'homogeneous_division')
      AND (member_line_count IS NULL OR member_line_count = 1)
      AND product_key IS NOT NULL
    GROUP BY product_key
),
lines AS (
    SELECT sg.id AS sale_group_id,
           sg.posting_id,
           sg.label AS lot_label,
           l.id AS line_id,
           l.label AS line_label,
           l.stated_quantity,
           l.attributes,
           r.product_key,
           c.unit_price AS exact_unit,
           c.comps AS exact_comps,
           c.comps_available AS exact_comps_available,
           CASE
               WHEN l.stated_quantity IS NOT NULL
                    AND l.attributes->>'ram_dimm_gb' ~ '^[0-9]+(\.[0-9]+)?$'
                   THEN l.stated_quantity * (l.attributes->>'ram_dimm_gb')::numeric
               WHEN l.attributes->>'ram_total_gb' ~ '^[0-9]+(\.[0-9]+)?$'
                   THEN (l.attributes->>'ram_total_gb')::numeric
           END AS ram_gb
    FROM sale_groups sg
    JOIN v_current_extractions cur ON cur.extraction_id = sg.extraction_id
    JOIN sale_group_terms t ON t.sale_group_id = sg.id
    JOIN lines l ON l.id = t.line_id
    LEFT JOIN LATERAL (
        SELECT product_key
        FROM resolutions
        WHERE line_id = l.id AND superseded_by IS NULL
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    ) r ON true
    LEFT JOIN exact_comp c ON c.product_key = r.product_key
),
priced AS (
    SELECT ln.*,
           CASE WHEN ln.exact_unit IS NOT NULL AND ln.stated_quantity IS NOT NULL
                THEN ln.exact_unit * ln.stated_quantity END AS exact_value,
           CASE WHEN ln.ram_gb IS NOT NULL
                     AND COALESCE(ln.attributes->>'ram_type', '') ILIKE '%ddr4%'
                     AND rate.usd_per_gb IS NOT NULL
                THEN ln.ram_gb * rate.usd_per_gb END AS ram_rate_value,
           rate.usd_per_gb,
           rate.comps AS ram_rate_comps
    FROM lines ln
    LEFT JOIN v_ddr4_gb_rate rate ON true
)
SELECT p.sale_group_id,
       p.posting_id,
       p.lot_label,
       ask.amount AS lot_ask,
       ask.price_basis AS lot_price_basis,
       sum(p.exact_value) AS exact_value,
       sum(p.ram_rate_value) AS ram_rate_value,
       count(*) FILTER (WHERE p.exact_value IS NOT NULL) AS lines_exact,
       count(*) FILTER (WHERE p.ram_rate_value IS NOT NULL AND p.exact_value IS NULL) AS lines_ram_rate_only,
       count(*) AS lines_total,
       count(*) FILTER (WHERE p.exact_value IS NULL AND p.ram_rate_value IS NULL) AS lines_unpriced,
       ask.amount - sum(p.exact_value) AS ask_minus_exact,
       bool_and(p.exact_value IS NULL OR p.exact_comps_available > 0) AS exact_refs_in_stock
FROM priced p
LEFT JOIN LATERAL (
    SELECT amount, price_basis
    FROM price_observations po
    WHERE po.sale_group_id = p.sale_group_id
      AND po.price_kind = 'ask'
      AND po.superseded_by IS NULL
    ORDER BY po.observed_at DESC, po.id DESC
    LIMIT 1
) ask ON true
GROUP BY p.sale_group_id, p.posting_id, p.lot_label, ask.amount, ask.price_basis;

COMMENT ON VIEW v_partout IS 'Q3: part-out of a sale group. exact_value is stated quantity times a same-key standalone ask. ram_rate_value is stated DDR4 gigabytes times v_ddr4_gb_rate and is not folded into exact_value. lines_unpriced are the gap. A complete deal verdict requires lines_unpriced = 0.';
