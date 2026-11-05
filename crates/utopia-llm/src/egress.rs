//! Deployment-owned model egress. Unknown/external origins fail closed.
//! Workspace users cannot promote an endpoint into the trusted set.
pub fn trusted(base: &str, origins: &str) -> bool {
    let Ok(url) = reqwest::Url::parse(base) else {
        return false;
    };
    if !matches!(url.scheme(), "http" | "https")
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
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
#[derive(Clone)]
pub struct Gateway {
    pub base_url: String,
    pub api_key: String,
    pub tenant_id: String,
    pub profile: String,
}

impl Gateway {
    pub async fn exchange(
        &self,
        payload: &serde_json::Value,
        provider_url: &str,
        provider_key: Option<&str>,
    ) -> anyhow::Result<serde_json::Value> {
        let allowed = std::env::var("UTOPIA_PRIVACY_PROVIDER_ORIGINS").unwrap_or_default();
        self.exchange_with(
            payload,
            provider_url,
            provider_key,
            &allowed,
            std::time::Duration::from_secs(30),
        )
        .await
        .map_err(|error| {
            if error.chain().any(|e| e.is::<reqwest::Error>()) {
                anyhow::anyhow!("privacy_transport_or_json_failure")
            } else {
                error
            }
        })
    }

    async fn exchange_with(
        &self,
        payload: &serde_json::Value,
        provider_url: &str,
        provider_key: Option<&str>,
        allowed: &str,
        timeout: std::time::Duration,
    ) -> anyhow::Result<serde_json::Value> {
        anyhow::ensure!(
            uuid::Uuid::parse_str(&self.tenant_id).is_ok_and(|id| id.to_string() == self.tenant_id),
            "privacy_canonical_tenant_required"
        );
        let gateway_url = reqwest::Url::parse(&self.base_url)?;
        anyhow::ensure!(
            matches!(gateway_url.scheme(), "http" | "https")
                && gateway_url.username().is_empty()
                && gateway_url.password().is_none()
                && gateway_url.query().is_none()
                && gateway_url.fragment().is_none(),
            "privacy_gateway_url_invalid"
        );
        anyhow::ensure!(
            !self.api_key.is_empty() && !self.profile.is_empty(),
            "privacy_configuration_missing"
        );
        anyhow::ensure!(
            trusted(provider_url, allowed),
            "privacy_provider_origin_not_approved"
        );
        let http = reqwest::Client::builder()
            .timeout(timeout)
            .redirect(reqwest::redirect::Policy::none())
            .build()?;
        let response = http.post(format!("{}/v1/contexts", self.base_url.trim_end_matches('/')))
            .bearer_auth(&self.api_key).json(&serde_json::json!({"tenant_id":self.tenant_id,"profile":self.profile,"ttl_seconds":120})).send().await?;
        anyhow::ensure!(
            response.status().as_u16() == 201,
            "privacy_context_rejected"
        );
        let context: serde_json::Value = response.json().await?;
        let id = context["context_id"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("privacy_context_invalid"))?;
        anyhow::ensure!(
            !id.is_empty()
                && id.len() <= 128
                && id
                    .chars()
                    .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_')),
            "privacy_context_invalid"
        );
        let mut cleanup = Cleanup {
            http: http.clone(),
            url: format!("{}/v1/contexts/{id}", self.base_url.trim_end_matches('/')),
            key: self.api_key.clone(),
        };
        let encoded = async {
            anyhow::ensure!(context["tenant_id"].as_str()==Some(self.tenant_id.as_str()) && context["profile"].as_str()==Some(self.profile.as_str()),"privacy_context_binding_invalid");
            let expires=expiry(&context)?;
            let policy=context["policy_version"].as_str().filter(|s| !s.is_empty()).ok_or_else(||anyhow::anyhow!("privacy_policy_missing"))?;
            let response = http.post(format!("{}/v1/encode", self.base_url.trim_end_matches('/'))).bearer_auth(&self.api_key)
                .json(&serde_json::json!({"tenant_id":self.tenant_id,"context_id":id,"profile":self.profile,"purpose":"llm-egress","format":"json","payload":payload,"registrations":[]})).send().await?;
            anyhow::ensure!(response.status().as_u16() == 200, "privacy_encode_rejected");
            let body: serde_json::Value = response.json().await?;
            anyhow::ensure!(body["context_id"].as_str() == Some(id) && body["format"] == "json", "privacy_encode_binding_invalid");
            anyhow::ensure!(expiry(&body)?<=expires && body["policy_version"].as_str()==Some(policy),"privacy_encode_policy_or_expiry_invalid");
            let encoded=body.get("payload").cloned().ok_or_else(|| anyhow::anyhow!("privacy_payload_missing"))?;
            anyhow::ensure!(encoded.is_object() && compatible(payload,&encoded,None),"privacy_provider_contract_changed");
            let mut provider=http.post(provider_url).json(&encoded);
            if let Some(key)=provider_key {provider=provider.bearer_auth(key);}
            let response=provider.send().await.map_err(|_|anyhow::anyhow!("protected_provider_unavailable"))?;
            anyhow::ensure!(response.status().is_success(),"protected_provider_rejected");
            let response:serde_json::Value=response.json().await.map_err(|_|anyhow::anyhow!("protected_provider_invalid_json"))?;
            let decoded=http.post(format!("{}/v1/decode",self.base_url.trim_end_matches('/'))).bearer_auth(&self.api_key)
                .json(&serde_json::json!({"context_id":id,"format":"json","payload":response,"purpose":"llm-response","reveal_credentials":false})).send().await?;
            anyhow::ensure!(decoded.status().as_u16()==200,"privacy_decode_rejected");
            let decoded:serde_json::Value=decoded.json().await?;
            anyhow::ensure!(decoded["context_id"].as_str()==Some(id) && decoded["format"]=="json" && decoded["stats"]["unknown_aliases"].as_u64()==Some(0),"privacy_decode_binding_or_alias_failure");
            decoded.get("payload").cloned().ok_or_else(||anyhow::anyhow!("privacy_decode_payload_missing"))
        }.await;
        if http
            .delete(format!(
                "{}/v1/contexts/{id}",
                self.base_url.trim_end_matches('/')
            ))
            .bearer_auth(&self.api_key)
            .send()
            .await
            .is_ok_and(|response| response.status().as_u16() == 204)
        {
            cleanup.key.clear();
        }
        encoded
    }
}

struct Cleanup {
    http: reqwest::Client,
    url: String,
    key: String,
}
impl Drop for Cleanup {
    fn drop(&mut self) {
        if self.key.is_empty() {
            return;
        }
        if let Ok(runtime) = tokio::runtime::Handle::try_current() {
            let (http, url, key) = (self.http.clone(), self.url.clone(), self.key.clone());
            runtime.spawn(async move {
                let _ = http.delete(url).bearer_auth(key).send().await;
            });
        }
    }
}

fn expiry(value: &serde_json::Value) -> anyhow::Result<chrono::DateTime<chrono::Utc>> {
    let expiry = value["expires_at"]
        .as_str()
        .and_then(|v| chrono::DateTime::parse_from_rfc3339(v).ok())
        .ok_or_else(|| anyhow::anyhow!("privacy_expiry_missing_or_invalid"))?
        .to_utc();
    anyhow::ensure!(expiry > chrono::Utc::now(), "privacy_context_expired");
    Ok(expiry)
}

fn compatible(
    original: &serde_json::Value,
    encoded: &serde_json::Value,
    key: Option<&str>,
) -> bool {
    use serde_json::Value;
    match (original, encoded) {
        (Value::Object(a), Value::Object(b)) => {
            a.len() == b.len()
                && a.iter()
                    .all(|(k, v)| b.get(k).is_some_and(|other| compatible(v, other, Some(k))))
        }
        (Value::Array(a), Value::Array(b)) => {
            a.len() == b.len() && a.iter().zip(b).all(|(a, b)| compatible(a, b, key))
        }
        (Value::String(_), Value::String(_)) => {
            !matches!(
                key,
                Some("model" | "role" | "name" | "tool_call_id" | "id" | "type")
            ) || original == encoded
        }
        _ => original == encoded,
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

#[cfg(test)]
#[path = "egress_tests.rs"]
mod gateway_tests;
