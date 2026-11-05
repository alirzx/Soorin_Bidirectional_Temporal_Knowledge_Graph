//! Deployment-owned model egress. Unknown/external origins fail closed.
//! Workspace users cannot promote an endpoint into the trusted set.
pub fn trusted(base: &str, origins: &str) -> bool {
    let Ok(url) = reqwest::Url::parse(base) else {
        return false;
    };
    if !matches!(url.scheme(), "http" | "https")
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return false;
    }
    origins
        .split(',')
        .filter_map(|item| reqwest::Url::parse(item.trim()).ok())
        .any(|allowed| allowed.origin() == url.origin())
}

pub fn require(base: &str) -> anyhow::Result<()> {
    let origins = std::env::var("UTOPIA_MODEL_TRUSTED_ORIGINS").unwrap_or_default();
    if trusted(base, &origins) {
        return Ok(());
    }
    // Unit tests use private loopback mock servers. Production must explicitly
    // trust even loopback endpoints; localhost is not a DLP attestation.
    if (cfg!(test) || std::env::var("UTOPIA_MODEL_TEST_MODE").as_deref() == Ok("1"))
        && reqwest::Url::parse(base)
            .ok()
            .is_some_and(|u| matches!(u.host_str(), Some("127.0.0.1" | "localhost")))
    {
        return Ok(());
    }
    anyhow::bail!(
        "model_egress_blocked: configure a trusted inference origin or a protected provider proxy"
    )
}

/// Published Privacy Gateway REST contract. It performs no local tokenization.
/// Caller must supply a trusted canonical tenant; response contents are never logged.
pub struct Gateway {
    pub base_url: String,
    pub api_key: String,
    pub tenant_id: String,
    pub profile: String,
}

impl Gateway {
    pub async fn transform(
        &self,
        payload: &serde_json::Value,
    ) -> anyhow::Result<serde_json::Value> {
        let http = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .redirect(reqwest::redirect::Policy::none())
            .build()?;
        let response = http.post(format!("{}/v1/contexts", self.base_url.trim_end_matches('/')))
            .bearer_auth(&self.api_key).json(&serde_json::json!({"tenant_id":self.tenant_id,"profile":self.profile,"ttl_seconds":120})).send().await?;
        anyhow::ensure!(
            response.status().as_u16() == 201,
            "privacy_context_rejected"
        );
        let context: serde_json::Value = response.json().await?;
        anyhow::ensure!(
            context["tenant_id"].as_str() == Some(self.tenant_id.as_str())
                && context["profile"].as_str() == Some(self.profile.as_str()),
            "privacy_context_binding_invalid"
        );
        let id = context["context_id"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("privacy_context_invalid"))?;
        anyhow::ensure!(
            id.chars()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_')),
            "privacy_context_invalid"
        );
        let encoded = async {
            let response = http.post(format!("{}/v1/encode", self.base_url.trim_end_matches('/'))).bearer_auth(&self.api_key)
                .json(&serde_json::json!({"tenant_id":self.tenant_id,"context_id":id,"profile":self.profile,"purpose":"llm-egress","format":"json","payload":payload,"registrations":[]})).send().await?;
            anyhow::ensure!(response.status().as_u16() == 200, "privacy_encode_rejected");
            let body: serde_json::Value = response.json().await?;
            anyhow::ensure!(body["context_id"].as_str() == Some(id) && body["format"] == "json", "privacy_encode_binding_invalid");
            body.get("payload").cloned().ok_or_else(|| anyhow::anyhow!("privacy_payload_missing"))
        }.await;
        // Encode-only output is suitable for approved proxy integration, not a
        // request-scoped decoded conversation. Never silently authorize inference.
        let _ = http
            .delete(format!(
                "{}/v1/contexts/{id}",
                self.base_url.trim_end_matches('/')
            ))
            .bearer_auth(&self.api_key)
            .send()
            .await;
        encoded
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn origin_trust_is_exact_not_suffix_or_path_based() {
        assert!(trusted("http://embedding:8080/v1", "http://embedding:8080"));
        assert!(!trusted(
            "http://embedding.evil:8080",
            "http://embedding:8080"
        ));
        assert!(!trusted("http://embedding:8081", "http://embedding:8080"));
        assert!(!trusted(
            "http://secret@embedding:8080",
            "http://embedding:8080"
        ));
        assert!(!trusted("https://external.test", ""));
    }
}
