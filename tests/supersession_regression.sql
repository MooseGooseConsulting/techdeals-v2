-- Regression for same-key corrections under the append-only supersession
-- contract. Requires schema/000_functions.sql and schema/010_tables.sql.
-- The missing-target check must fail at SET CONSTRAINTS IMMEDIATE; the next
-- case must atomically reuse the live category name. The entire test rolls back.
\set ON_ERROR_STOP on
BEGIN;

DO $regression$
DECLARE
    v_name        text := 'supersession-regression-' || gen_random_uuid()::text;
    v_old         uuid;
    v_missing     uuid;
    v_replacement uuid;
    v_caught      boolean := false;
BEGIN
    INSERT INTO categories (name, spec)
    VALUES (v_name, '{"capacity_gb":32}'::jsonb)
    RETURNING id INTO v_old;

    -- A deferred pointer to a target that is never inserted must fail when
    -- the writer forces the FK immediate before transaction completion.
    v_missing := uuidv7();
    BEGIN
        SET CONSTRAINTS categories_superseded_by_fk DEFERRED;
        UPDATE categories SET superseded_by = v_missing WHERE id = v_old;
        SET CONSTRAINTS categories_superseded_by_fk IMMEDIATE;
    EXCEPTION WHEN foreign_key_violation THEN
        v_caught := true;
    END;
    IF NOT v_caught THEN
        RAISE EXCEPTION 'regression fail: missing replacement passed FK validation';
    END IF;

    -- Correct order: free the partial live-name index, insert the replacement
    -- with the already-generated later UUID, then validate the deferred FK.
    v_replacement := uuidv7();
    SET CONSTRAINTS categories_superseded_by_fk DEFERRED;
    UPDATE categories SET superseded_by = v_replacement WHERE id = v_old;
    INSERT INTO categories (id, name, spec)
    VALUES (v_replacement, v_name, '{"capacity_gb":32,"type":"DDR4"}'::jsonb);
    SET CONSTRAINTS categories_superseded_by_fk IMMEDIATE;

    IF NOT EXISTS (
        SELECT 1 FROM categories
        WHERE id = v_old AND superseded_by = v_replacement
    ) OR NOT EXISTS (
        SELECT 1 FROM categories
        WHERE id = v_replacement AND name = v_name AND superseded_by IS NULL
    ) THEN
        RAISE EXCEPTION 'regression fail: same-name replacement/history link missing';
    END IF;

    RAISE NOTICE 'supersession regression passed: missing target rejected; same-key correction accepted';
END
$regression$;

ROLLBACK;
