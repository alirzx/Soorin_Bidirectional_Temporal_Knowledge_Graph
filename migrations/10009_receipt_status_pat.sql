ALTER TABLE personal_tokens DROP CONSTRAINT personal_tokens_scope_check;
ALTER TABLE personal_tokens ADD CONSTRAINT personal_tokens_scope_check
    CHECK (scope IN ('read', 'write', 'receipt_status'));
