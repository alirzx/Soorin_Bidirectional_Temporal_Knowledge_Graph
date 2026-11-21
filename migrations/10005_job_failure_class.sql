-- NULL also covers legacy jobs whose failure category cannot be reconstructed.
ALTER TABLE jobs ADD COLUMN failure_class text
    CHECK (failure_class IN ('terminal','deferred','unknown'));
CREATE INDEX jobs_document_dependency ON jobs ((payload->>'document_id'),kind,id DESC)
    WHERE kind IN ('process_document','extract_document','soc_reembed_document');
