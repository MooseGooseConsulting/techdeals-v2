-- Focused regressions for validated PR 19 view feedback.
-- Requires the TechDeals v2 schema (including the reviewed 020_views.sql).
-- All synthetic rows and helper functions are rolled back.
\set ON_ERROR_STOP on
BEGIN;
SAVEPOINT view_feedback_regressions;
CREATE TEMP TABLE _view_feedback_test_setup (id boolean) ON COMMIT DROP;

CREATE FUNCTION pg_temp.add_group_listing(
    p_tag text,
    p_product_key text,
    p_line_quantity numeric,
    p_term_quantity numeric,
    p_amount numeric,
    p_price_quantity numeric,
    p_availability text
) RETURNS uuid
LANGUAGE plpgsql AS $helper$
DECLARE
    v_posting uuid;
    v_extraction uuid;
    v_line uuid;
    v_group uuid;
    v_posting_key text;
    v_url text := 'https://smoke.invalid/view-feedback/' || p_tag;
BEGIN
    v_posting_key := encode(sha256(convert_to('view-feedback:' || p_tag, 'UTF8')), 'hex');
    INSERT INTO postings (offer_key, source, url, fetched_at, checksum, payload)
    VALUES (v_posting_key, 'smoke', v_url, now(),
            encode(sha256(convert_to(v_url, 'UTF8')), 'hex'), '{"smoke":true}')
    RETURNING id INTO v_posting;

    INSERT INTO extractions (posting_id, parser_name)
    VALUES (v_posting, 'view-feedback-smoke') RETURNING id INTO v_extraction;
    INSERT INTO lines (posting_id, extraction_id, ordinal, label, stated_quantity)
    VALUES (v_posting, v_extraction, 1, p_tag, p_line_quantity)
    RETURNING id INTO v_line;
    INSERT INTO sale_groups (posting_id, extraction_id, position, label)
    VALUES (v_posting, v_extraction, 0, p_tag)
    RETURNING id INTO v_group;
    INSERT INTO sale_group_terms (sale_group_id, line_id, line_quantity)
    VALUES (v_group, v_line, p_term_quantity);

    IF p_product_key IS NOT NULL THEN
        INSERT INTO resolutions (posting_id, line_id, product_key, product_name, confidence, method)
        VALUES (v_posting, v_line, p_product_key, p_product_key, 1, 'smoke');
    END IF;

    IF p_amount IS NOT NULL THEN
        INSERT INTO price_observations
            (offer_key, subject_path, posting_id, subject_kind, sale_group_id,
             observed_at, price_kind, price_basis, amount, currency, quantity)
        VALUES (encode(sha256(convert_to(v_posting_key || '|g0', 'UTF8')), 'hex'),
                'g0', v_posting, 'sale_group', v_group, now(), 'ask', 'explicit_unit',
                p_amount, 'USD', p_price_quantity);
    END IF;

    IF p_availability IS NOT NULL THEN
        INSERT INTO availability_observations
            (offer_key, subject_path, posting_id, subject_kind, sale_group_id, observed_at, state)
        VALUES (encode(sha256(convert_to(v_posting_key || '|g0', 'UTF8')), 'hex'),
                'g0', v_posting, 'sale_group', v_group, now(), p_availability);
    END IF;

    RETURN v_posting;
END
$helper$;

CREATE FUNCTION pg_temp.add_posting_with_line(p_tag text) RETURNS uuid
LANGUAGE plpgsql AS $helper$
DECLARE
    v_posting uuid;
    v_extraction uuid;
    v_posting_key text;
    v_url text := 'https://smoke.invalid/view-feedback/' || p_tag;
BEGIN
    v_posting_key := encode(sha256(convert_to('view-feedback:' || p_tag, 'UTF8')), 'hex');
    INSERT INTO postings (offer_key, source, url, fetched_at, checksum, payload)
    VALUES (v_posting_key, 'smoke', v_url, now(),
            encode(sha256(convert_to(v_url, 'UTF8')), 'hex'), '{"smoke":true}')
    RETURNING id INTO v_posting;
    INSERT INTO extractions (posting_id, parser_name)
    VALUES (v_posting, 'view-feedback-smoke') RETURNING id INTO v_extraction;
    INSERT INTO lines (posting_id, extraction_id, ordinal, label)
    VALUES (v_posting, v_extraction, 1, p_tag);
    RETURN v_posting;
END
$helper$;

DO $smoke$
DECLARE
    v_posting uuid;
    v_old_extraction uuid;
    v_current_extraction uuid;
    v_old_line uuid;
    v_current_line uuid;
    v_old_group uuid;
    v_current_group uuid;
    v_key text;
    v_price numeric;
    v_count integer;
    v_incomplete boolean;
    v_component_value numeric;
    v_lot_ask numeric;
    v_lot_ask_total numeric;
    v_ask_delta numeric;
    v_posting_quarantined uuid;
    v_posting_released uuid;
    v_state text;
    v_reason text;
    v_line_quarantined_count integer;
BEGIN
    -- Available comps only: unavailable, unknown and unchecked offers must
    -- not lower the helper's current-market unit reference.
    PERFORM pg_temp.add_group_listing('available-ref', 'feedback.available-ref', 1, 1, 12, 1, 'available');
    PERFORM pg_temp.add_group_listing('unavailable-ref', 'feedback.available-ref', 1, 1, 1, 1, 'unavailable');
    PERFORM pg_temp.add_group_listing('unknown-ref', 'feedback.available-ref', 1, 1, 2, 1, 'unknown');
    PERFORM pg_temp.add_group_listing('unchecked-ref', 'feedback.available-ref', 1, 1, 3, 1, NULL);
    SELECT ref_unit_price, comparable_count INTO v_price, v_count
    FROM v_product_reference_price WHERE product_key = 'feedback.available-ref';
    IF v_price <> 12 OR v_count <> 1 THEN
        RAISE EXCEPTION 'smoke fail: availability reference was %, count %; expected 12 and 1', v_price, v_count;
    END IF;

    -- A single-line lot cannot use its own available ask as its sole comparable.
    v_posting := pg_temp.add_group_listing('self-comparable', 'feedback.self-only', 1, 1, 8, 1, 'available');
    SELECT lines_valued, valuation_incomplete, component_value
      INTO v_count, v_incomplete, v_component_value
    FROM v_lot_worth WHERE posting_id = v_posting;
    IF v_count <> 0 OR NOT v_incomplete OR v_component_value IS NOT NULL THEN
        RAISE EXCEPTION 'smoke fail: self-comparable valued its own lot (count %, incomplete %, value %)',
            v_count, v_incomplete, v_component_value;
    END IF;

    -- A reference without a stated member quantity does not make the lot complete.
    PERFORM pg_temp.add_group_listing('unknown-quantity-comp', 'feedback.unknown-quantity', 1, 1, 20, 1, 'available');
    v_posting := pg_temp.add_group_listing('unknown-quantity-lot', 'feedback.unknown-quantity', NULL, NULL, NULL, NULL, NULL);
    SELECT lines_valued, valuation_incomplete, component_value
      INTO v_count, v_incomplete, v_component_value
    FROM v_lot_worth WHERE posting_id = v_posting;
    IF v_count <> 0 OR NOT v_incomplete OR v_component_value IS NOT NULL THEN
        RAISE EXCEPTION 'smoke fail: unknown member quantity appeared valued (count %, incomplete %, value %)',
            v_count, v_incomplete, v_component_value;
    END IF;

    -- For one homogeneous line, an explicit per-unit ask is normalized to the
    -- quantity included in one purchase. The raw observation remains intact.
    PERFORM pg_temp.add_group_listing('unit-price-comp', 'feedback.unit-price', 1, 1, 12, 1, 'available');
    v_posting := pg_temp.add_group_listing('unit-price-lot', 'feedback.unit-price', 10, 10, 5, 1, 'unavailable');
    SELECT lot_ask, lot_ask_comparable_total, component_value, ask_minus_component_value
      INTO v_lot_ask, v_lot_ask_total, v_component_value, v_ask_delta
    FROM v_lot_worth WHERE posting_id = v_posting;
    IF v_lot_ask <> 5 OR v_lot_ask_total <> 50 OR v_component_value <> 120 OR v_ask_delta <> -70 THEN
        RAISE EXCEPTION 'smoke fail: per-unit lot ask raw %, comparable total %, component %, delta %',
            v_lot_ask, v_lot_ask_total, v_component_value, v_ask_delta;
    END IF;

    -- Group ask replay: old group UUID, new extraction/group UUID, same recorded
    -- position. The lot view must recover the live ask by the stable group key.
    v_posting := pg_temp.add_group_listing('group-replay-seed', NULL, 1, 1, NULL, NULL, NULL);
    SELECT offer_key INTO v_key FROM postings WHERE id = v_posting;
    SELECT extraction_id INTO v_old_extraction FROM v_current_extractions WHERE posting_id = v_posting;
    SELECT id INTO v_old_line FROM lines WHERE extraction_id = v_old_extraction;
    SELECT id INTO v_old_group FROM sale_groups WHERE extraction_id = v_old_extraction;
    INSERT INTO price_observations
        (offer_key, subject_path, posting_id, subject_kind, sale_group_id,
         observed_at, price_kind, price_basis, amount, currency, quantity)
    VALUES (encode(sha256(convert_to(v_key || '|g0', 'UTF8')), 'hex'),
            'g0', v_posting, 'sale_group', v_old_group, now() - interval '1 minute',
            'ask', 'explicit_unit', 31, 'USD', 1);
    INSERT INTO extractions (posting_id, parser_name, created_at)
    VALUES (v_posting, 'view-feedback-replay', now()) RETURNING id INTO v_current_extraction;
    INSERT INTO lines (posting_id, extraction_id, ordinal, label, stated_quantity)
    VALUES (v_posting, v_current_extraction, 1, 'group-replay-seed', 1)
    RETURNING id INTO v_current_line;
    INSERT INTO sale_groups (posting_id, extraction_id, position, label)
    VALUES (v_posting, v_current_extraction, 0, 'group-replay-seed')
    RETURNING id INTO v_current_group;
    INSERT INTO sale_group_terms (sale_group_id, line_id, line_quantity)
    VALUES (v_current_group, v_current_line, 1);
    SELECT lot_ask INTO v_lot_ask FROM v_lot_worth WHERE posting_id = v_posting;
    IF v_lot_ask <> 31 THEN
        RAISE EXCEPTION 'smoke fail: replayed group ask was %, expected 31', v_lot_ask;
    END IF;

    -- Posting-level quarantine is independent from later line-level release or
    -- quarantine events; line-level state remains in its own count.
    v_posting_quarantined := pg_temp.add_posting_with_line('posting-quarantined');
    INSERT INTO quarantine_events (posting_id, state, reason, created_at)
    VALUES (v_posting_quarantined, 'quarantined', 'posting_reason', now() - interval '2 minutes');
    INSERT INTO quarantine_events (posting_id, line_id, state, reason, created_at)
    SELECT v_posting_quarantined, l.id, 'released', 'line_release', now() - interval '1 minute'
    FROM lines l WHERE l.posting_id = v_posting_quarantined;

    v_posting_released := pg_temp.add_posting_with_line('posting-released');
    INSERT INTO quarantine_events (posting_id, state, reason, created_at)
    VALUES (v_posting_released, 'released', 'posting_release', now() - interval '2 minutes');
    INSERT INTO quarantine_events (posting_id, line_id, state, reason, created_at)
    SELECT v_posting_released, l.id, 'quarantined', 'line_quarantine', now() - interval '1 minute'
    FROM lines l WHERE l.posting_id = v_posting_released;

    SELECT quarantine_state, quarantine_reason INTO v_state, v_reason
    FROM v_accounting WHERE posting_id = v_posting_quarantined;
    IF v_state <> 'quarantined' OR v_reason <> 'posting_reason' THEN
        RAISE EXCEPTION 'smoke fail: later line event replaced posting quarantine: %, %', v_state, v_reason;
    END IF;
    SELECT quarantine_state, quarantined_line_count INTO v_state, v_line_quarantined_count
    FROM v_accounting WHERE posting_id = v_posting_released;
    IF v_state <> 'released' OR v_line_quarantined_count <> 1 THEN
        RAISE EXCEPTION 'smoke fail: line quarantine replaced posting release or was not counted: %, %',
            v_state, v_line_quarantined_count;
    END IF;
END
$smoke$;

ROLLBACK TO SAVEPOINT view_feedback_regressions;
COMMIT;
