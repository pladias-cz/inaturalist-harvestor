CREATE TABLE IF NOT EXISTS gbif.inaturalist_taxa
(
    id bigint NOT NULL,
    name text COLLATE pg_catalog."default" NOT NULL,
    rank text COLLATE pg_catalog."default",
    col_id bigint,
    col_name text COLLATE pg_catalog."default",
    col_rank text COLLATE pg_catalog."default",
    gbif_taxon_key bigint,
    gbif_name text COLLATE pg_catalog."default",
    resolution_status   text NOT NULL DEFAULT 'pending',
    resolved_at timestamp with time zone,
    data jsonb,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT inaturalist_taxa_pkey PRIMARY KEY (id),
    CONSTRAINT taxa_resolution_status_check
        CHECK (
            resolution_status IN (
                'pending',
                'matched',
                'unmatched'
            )
        )
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS gbif.inaturalist_taxa
    OWNER to pladias;

CREATE INDEX IF NOT EXISTS taxa_unresolved_idx
    ON gbif.inaturalist_taxa USING btree
    (id ASC NULLS LAST)

    WHERE col_id IS NULL;

CREATE INDEX taxa_pending_idx
    ON gbif.inaturalist_taxa (id)
    WHERE resolution_status = 'pending';

CREATE INDEX taxa_col_id_idx
    ON gbif.inaturalist_taxa (col_id);

CREATE INDEX taxa_gbif_taxon_key_idx
    ON gbif.inaturalist_taxa (gbif_taxon_key);


-----------------------------
CREATE TABLE IF NOT EXISTS gbif.inaturalist_records
(
    id bigint NOT NULL,
    created_at timestamp with time zone,
    updated_at timestamp with time zone,
    observed_on date,
    taxon_id bigint,
    taxon_name text COLLATE pg_catalog."default",
    taxon_rank text COLLATE pg_catalog."default",
    user_id bigint,
    user_login text COLLATE pg_catalog."default",
    latitude double precision,
    longitude double precision,
    positional_accuracy double precision,
    quality_grade text COLLATE pg_catalog."default",
    species_guess text COLLATE pg_catalog."default",
    in_project boolean NOT NULL DEFAULT true,
    last_seen_in_project timestamp with time zone,
    data jsonb NOT NULL,
    imported_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT inaturalist_pkey PRIMARY KEY (id),
    CONSTRAINT inaturalist_records_taxon_fk FOREIGN KEY (taxon_id)
        REFERENCES gbif.inaturalist_taxa (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS gbif.inaturalist_records
    OWNER to pladias;

CREATE INDEX IF NOT EXISTS observations_created_at_idx
    ON gbif.inaturalist_records USING btree
    (created_at ASC NULLS LAST)
;

CREATE INDEX IF NOT EXISTS observations_in_project_idx
    ON gbif.inaturalist_records USING btree
    (in_project ASC NULLS LAST)
;

CREATE INDEX IF NOT EXISTS observations_taxon_id_idx
    ON gbif.inaturalist_records USING btree
    (taxon_id ASC NULLS LAST)
;

CREATE INDEX IF NOT EXISTS observations_updated_at_idx
    ON gbif.inaturalist_records USING btree
    (updated_at ASC NULLS LAST)
;

CREATE INDEX IF NOT EXISTS observations_user_id_idx
    ON gbif.inaturalist_records USING btree
    (user_id ASC NULLS LAST)
;
