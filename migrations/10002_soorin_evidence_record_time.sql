-- Unknown legacy link creation time stays NULL: do not fabricate historical
-- knowledge from the chunk's creation time. New links record receipt time.
ALTER TABLE fact_evidence ADD COLUMN recorded_at TIMESTAMPTZ;
ALTER TABLE fact_evidence ALTER COLUMN recorded_at SET DEFAULT now();
CREATE INDEX soorin_fact_evidence_record_time ON fact_evidence(fact_id, recorded_at);
