-- Rollback-only integrity probes for extraction ownership and supersession
-- identity. Requires schema/000_functions.sql and schema/010_tables.sql.
\set ON_ERROR_STOP on
BEGIN;

DO $regression$
DECLARE
    v_posting_1 uuid;
    v_posting_2 uuid;
    v_extraction_1 uuid;
    v_extraction_2 uuid;
    v_line_1 uuid;
    v_line_2 uuid;
    v_old_price uuid;
    v_new_price uuid;
    v_cross_price uuid;
    v_old_resolution uuid;
    v_new_resolution uuid;
    v_cross_resolution uuid;
    v_old_category uuid;
    v_cross_category uuid;
    v_atomic_category uuid;
    v_replacement_category uuid;
    v_category_name text;
    v_offer_1 text := repeat('1', 64);
    v_offer_2 text := repeat('2', 64);
    v_rejected_line boolean := false;
    v_rejected_group boolean := false;
    v_rejected_resolution boolean := false;
    v_rejected_price_link boolean := false;
    v_rejected_resolution_link boolean := false;
    v_rejected_category_link boolean := false;
    v_accepted_price_link boolean := false;
    v_accepted_resolution_link boolean := false;
    v_accepted_category_replacement boolean := false;
BEGIN
    INSERT INTO postings (offer_key, source, url, fetched_at, checksum, payload)
    VALUES (v_offer_1, 'integrity-regression', 'https://probe.invalid/1', now(), repeat('a', 64), '{}')
    RETURNING id INTO v_posting_1;
    INSERT INTO postings (offer_key, source, url, fetched_at, checksum, payload)
    VALUES (v_offer_2, 'integrity-regression', 'https://probe.invalid/2', now(), repeat('b', 64), '{}')
    RETURNING id INTO v_posting_2;
    INSERT INTO extractions (posting_id, parser_name) VALUES (v_posting_1, 'probe') RETURNING id INTO v_extraction_1;
    INSERT INTO extractions (posting_id, parser_name) VALUES (v_posting_2, 'probe') RETURNING id INTO v_extraction_2;
    INSERT INTO lines (posting_id, extraction_id, ordinal, label)
    VALUES (v_posting_1, v_extraction_1, 1, 'line one') RETURNING id INTO v_line_1;
    INSERT INTO lines (posting_id, extraction_id, ordinal, label)
    VALUES (v_posting_2, v_extraction_2, 1, 'line two') RETURNING id INTO v_line_2;

    -- Correct ownership pairs are accepted; mixing a posting with another
    -- posting's extraction is rejected for both child tables.
    BEGIN
        INSERT INTO lines (posting_id, extraction_id, ordinal, label)
        VALUES (v_posting_1, v_extraction_2, 2, 'cross-posting line');
    EXCEPTION WHEN foreign_key_violation THEN v_rejected_line := true;
    END;
    BEGIN
        INSERT INTO sale_groups (posting_id, extraction_id, position, label)
        VALUES (v_posting_1, v_extraction_2, 1, 'cross-posting group');
    EXCEPTION WHEN foreign_key_violation THEN v_rejected_group := true;
    END;
    BEGIN
        INSERT INTO resolutions (posting_id, line_id, product_key, product_name, confidence, method)
        VALUES (v_posting_1, v_line_2, 'wrong-owner', 'Wrong owner', 0.5, 'probe');
    EXCEPTION WHEN foreign_key_violation THEN v_rejected_resolution := true;
    END;

    -- Prices in a different offer series cannot supersede this row. A later
    -- observation for the same offer and kind is a valid correction.
    INSERT INTO price_observations
        (offer_key, subject_path, posting_id, subject_kind, line_id, observed_at,
         price_kind, price_basis, amount, currency, quantity)
    VALUES (encode(sha256(convert_to(v_offer_1 || '|g0.1', 'UTF8')), 'hex'),
            'g0.1', v_posting_1, 'line', v_line_1, now() - interval '1 hour',
            'ask', 'explicit_unit', 10, 'USD', 1)
    RETURNING id INTO v_old_price;
    INSERT INTO price_observations
        (offer_key, subject_path, posting_id, subject_kind, line_id, observed_at,
         price_kind, price_basis, amount, currency, quantity)
    VALUES (encode(sha256(convert_to(v_offer_1 || '|g0.1', 'UTF8')), 'hex'),
            'g0.1', v_posting_1, 'line', v_line_1, now(),
            'ask', 'explicit_unit', 11, 'USD', 1)
    RETURNING id INTO v_new_price;
    INSERT INTO price_observations
        (offer_key, subject_path, posting_id, subject_kind, line_id, observed_at,
         price_kind, price_basis, amount, currency, quantity)
    VALUES (encode(sha256(convert_to(v_offer_2 || '|g0.1', 'UTF8')), 'hex'),
            'g0.1', v_posting_2, 'line', v_line_2, now(),
            'ask', 'explicit_unit', 20, 'USD', 1)
    RETURNING id INTO v_cross_price;
    BEGIN
        UPDATE price_observations SET superseded_by = v_cross_price WHERE id = v_old_price;
        SET CONSTRAINTS price_observations_supersede_series IMMEDIATE;
    EXCEPTION WHEN check_violation THEN v_rejected_price_link := true;
    END;
    UPDATE price_observations SET superseded_by = v_new_price WHERE id = v_old_price;
    SET CONSTRAINTS price_observations_supersede_series IMMEDIATE;
    v_accepted_price_link := true;

    -- Resolution supersession is scoped to posting and nullable line identity.
    INSERT INTO resolutions (posting_id, line_id, product_key, product_name, confidence, method)
    VALUES (v_posting_1, v_line_1, 'old-key', 'Old product', 0.5, 'probe')
    RETURNING id INTO v_old_resolution;
    INSERT INTO resolutions (posting_id, line_id, product_key, product_name, confidence, method)
    VALUES (v_posting_1, v_line_1, 'new-key', 'New product', 0.6, 'probe')
    RETURNING id INTO v_new_resolution;
    INSERT INTO resolutions (posting_id, line_id, product_key, product_name, confidence, method)
    VALUES (v_posting_2, v_line_2, 'cross-key', 'Cross product', 0.7, 'probe')
    RETURNING id INTO v_cross_resolution;
    BEGIN
        UPDATE resolutions SET superseded_by = v_cross_resolution WHERE id = v_old_resolution;
        SET CONSTRAINTS resolutions_supersede_series IMMEDIATE;
    EXCEPTION WHEN check_violation THEN v_rejected_resolution_link := true;
    END;
    UPDATE resolutions SET superseded_by = v_new_resolution WHERE id = v_old_resolution;
    SET CONSTRAINTS resolutions_supersede_series IMMEDIATE;
    v_accepted_resolution_link := true;

    -- Category identity is the name. A different name cannot hide it; the
    -- existing deferred-FK correction order still accepts a same-name row.
    INSERT INTO categories (name, spec)
    VALUES ('integrity-old-' || uuidv7()::text, '{}') RETURNING id INTO v_old_category;
    INSERT INTO categories (name, spec)
    VALUES ('integrity-cross-' || uuidv7()::text, '{}') RETURNING id INTO v_cross_category;
    BEGIN
        UPDATE categories SET superseded_by = v_cross_category WHERE id = v_old_category;
        SET CONSTRAINTS categories_supersede_series IMMEDIATE;
    EXCEPTION WHEN check_violation THEN v_rejected_category_link := true;
    END;

    INSERT INTO categories (name, spec)
    VALUES ('integrity-atomic-' || uuidv7()::text, '{}') RETURNING id, name
    INTO v_atomic_category, v_category_name;
    v_replacement_category := uuidv7();
    SET CONSTRAINTS categories_superseded_by_fk DEFERRED;
    UPDATE categories SET superseded_by = v_replacement_category WHERE id = v_atomic_category;
    INSERT INTO categories (id, name, spec)
    VALUES (v_replacement_category, v_category_name, '{"replacement":true}');
    SET CONSTRAINTS categories_superseded_by_fk, categories_supersede_series IMMEDIATE;
    v_accepted_category_replacement := EXISTS (
        SELECT 1 FROM categories newer
        JOIN categories older ON older.superseded_by = newer.id
        WHERE older.id = v_atomic_category
          AND newer.id = v_replacement_category
          AND newer.name = older.name
    );

    IF NOT (v_rejected_line AND v_rejected_group AND v_rejected_resolution AND
            v_rejected_price_link AND v_rejected_resolution_link AND v_rejected_category_link AND
            v_accepted_price_link AND v_accepted_resolution_link AND v_accepted_category_replacement) THEN
        RAISE EXCEPTION 'integrity regression failed: line %, group %, resolution %, price rejected/accepted %/%, resolution rejected/accepted %/%, category rejected/atomic %/%',
            v_rejected_line, v_rejected_group, v_rejected_resolution,
            v_rejected_price_link, v_accepted_price_link,
            v_rejected_resolution_link, v_accepted_resolution_link,
            v_rejected_category_link, v_accepted_category_replacement;
    END IF;
    RAISE NOTICE 'integrity regression passed: cross-series links rejected; valid series and atomic category correction accepted';
END
$regression$;

ROLLBACK;
