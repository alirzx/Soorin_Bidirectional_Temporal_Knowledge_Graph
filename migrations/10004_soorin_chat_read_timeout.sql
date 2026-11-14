-- Preserve the existing 300-second idle timeout; allow a workspace override.
ALTER TABLE llm_settings ADD COLUMN chat_timeout_seconds INTEGER NOT NULL DEFAULT 300
    CHECK (chat_timeout_seconds BETWEEN 1 AND 3600);
