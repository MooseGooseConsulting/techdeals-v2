-- Rollback-only reproduction for PR 4 line-offer replay finding.
-- Target used: Neon project winter-brook-99288103, branch
-- br-morning-lab-b4rc55s8 (pr-review-20261016), database
-- pr4_final_validation. No connection string or credential is stored here.
--
-- Run against a database with the TechDeals v2 schema already installed:
--   psql -v ON_ERROR_STOP=1 -f line-replay-reproduction.sql
-- The SAVEPOINT rollback removes all inserted rows and the temporary table.
\set ON_ERROR_STOP on
BEGIN;
SAVEPOINT line_replay_repro;

CREATE TEMP TABLE line_replay_repro_ids (
    posting_id uuid,
    current_line_id uuid
) ON COMMIT DROP;

DO $repro$
DECLARE
    p uuid;
    e_old uuid;
    e_new uuid;
    l_old uuid;
    l_new uuid;
    k text;
BEGIN
    INSERT INTO postings (offer_key, source, url, fetched_at, checksum, payload)
    VALUES (
        repeat('6', 64), 'smoke', 'https://smoke.invalid/line-replay-repro', now(),
        repeat('7', 64), '{"smoke":true}'
    )
    RETURNING id INTO p;

    INSERT INTO extractions (posting_id, parser_name, created_at)
    VALUES (p, 'repro-old', now() - interval '1 minute')
    RETURNING id INTO e_old;

    INSERT INTO lines (posting_id, extraction_id, ordinal, label, stated_quantity)
    VALUES (p, e_old, 1, 'same position old', 1)
    RETURNING id INTO l_old;

    k := encode(sha256(convert_to(repeat('6', 64) || '|g0.1', 'UTF8')), 'hex');
    INSERT INTO price_observations
        (offer_key, subject_path, posting_id, subject_kind, line_id,
         observed_at, price_kind, price_basis, amount, currency, quantity)
    VALUES
        (k, 'g0.1', p, 'line', l_old, now() - interval '1 minute',
         'ask', 'explicit_unit', 42, 'USD', 1);

    INSERT INTO extractions (posting_id, parser_name, created_at)
    VALUES (p, 'repro-replay', now())
    RETURNING id INTO e_new;

    INSERT INTO lines (posting_id, extraction_id, ordinal, label, stated_quantity)
    VALUES (p, e_new, 1, 'same position new UUID', 1)
    RETURNING id INTO l_new;

    INSERT INTO line_replay_repro_ids VALUES (p, l_new);
END
$repro$;

-- Before-fix result: current_read_rows = 0, read_line_id = NULL, amount = NULL.
SELECT i.posting_id,
       i.current_line_id,
       (SELECT count(*)
        FROM v_cheapest_available v
        WHERE v.posting_id = i.posting_id AND v.subject_kind = 'line') AS current_read_rows,
       (SELECT (array_agg(v.line_id))[1]
        FROM v_cheapest_available v
        WHERE v.posting_id = i.posting_id AND v.subject_kind = 'line') AS read_line_id,
       (SELECT min(v.amount)
        FROM v_cheapest_available v
        WHERE v.posting_id = i.posting_id AND v.subject_kind = 'line') AS amount
FROM line_replay_repro_ids i;

ROLLBACK TO SAVEPOINT line_replay_repro;
COMMIT;
