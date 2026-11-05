use super::*;
use serde_json::{json, Value};
use wiremock::{
    matchers::{method, path},
    Mock, MockServer, ResponseTemplate,
};

async fn scenario(fault: &str) -> anyhow::Result<()> {
    let server = MockServer::start().await;
    let tenant = "00000000-0000-0000-0000-000000000001";
    let expiry = (chrono::Utc::now() + chrono::Duration::seconds(120)).to_rfc3339();
    let payload = json!({"model":"synthetic","messages":[{"role":"user","content":"PRIVATE_SYNTHETIC"}],"stream":false});
    let mut encoded = payload.clone();
    encoded["messages"][0]["content"] = json!("[ALIAS_1]");
    let mut context = json!({"context_id":"context-1","tenant_id":tenant,"profile":"test","policy_version":"v1","expires_at":expiry});
    let mut encoding = json!({"context_id":"context-1","format":"json","policy_version":"v1","expires_at":expiry,"payload":encoded,"stats":{}});
    let mut decoding = json!({"context_id":"context-1","format":"json","stats":{"unknown_aliases":0},"payload":{"choices":[{"message":{"content":"PRIVATE_SYNTHETIC"}}]}});
    match fault {
        "tenant" => context["tenant_id"] = json!("other"),
        "profile" => context["profile"] = json!("other"),
        "missing_expiry" => {
            context.as_object_mut().unwrap().remove("expires_at");
        }
        "expired" => context["expires_at"] = json!("2000-01-01T00:00:00Z"),
        "encode_context" => encoding["context_id"] = json!("other"),
        "encode_format" => encoding["format"] = json!("messages"),
        "encode_expiry" => encoding["expires_at"] = json!("invalid"),
        "encode_policy" => encoding["policy_version"] = json!("other"),
        "missing_payload" => {
            encoding.as_object_mut().unwrap().remove("payload");
        }
        "model_changed" => encoding["payload"]["model"] = json!("attacker"),
        "role_changed" => encoding["payload"]["messages"][0]["role"] = json!("system"),
        "decode_context" => decoding["context_id"] = json!("other"),
        "decode_format" => decoding["format"] = json!("text"),
        "unknown_alias" => decoding["stats"]["unknown_aliases"] = json!(1),
        _ => {}
    }
    let mut create = ResponseTemplate::new(if fault == "gateway_500" { 500 } else { 201 })
        .set_body_json(context);
    if fault == "malformed_json" {
        create = ResponseTemplate::new(201).set_body_string("PRIVATE_SYNTHETIC");
    }
    Mock::given(method("POST"))
        .and(path("/v1/contexts"))
        .respond_with(create)
        .mount(&server)
        .await;
    let mut encode = ResponseTemplate::new(200).set_body_json(encoding);
    if fault == "encode_timeout" {
        encode = encode.set_delay(std::time::Duration::from_millis(200));
    }
    Mock::given(method("POST"))
        .and(path("/v1/encode"))
        .respond_with(encode)
        .mount(&server)
        .await;
    let mut provider = ResponseTemplate::new(match fault {
        "provider_400" => 400,
        "provider_503" => 503,
        "redirect" => 307,
        _ => 200,
    })
    .set_body_json(json!({"choices":[{"message":{"content":"[ALIAS_1]"}}]}));
    if fault == "redirect" {
        provider = provider.insert_header("location", format!("{}/leak", server.uri()));
    }
    if fault == "provider_timeout" {
        provider = provider.set_delay(std::time::Duration::from_millis(200));
    }
    Mock::given(method("POST"))
        .and(path("/provider"))
        .respond_with(provider)
        .mount(&server)
        .await;
    let mut decode = ResponseTemplate::new(200).set_body_json(decoding);
    if fault == "decode_timeout" {
        decode = decode.set_delay(std::time::Duration::from_millis(200));
    }
    Mock::given(method("POST"))
        .and(path("/v1/decode"))
        .respond_with(decode)
        .mount(&server)
        .await;
    Mock::given(method("DELETE"))
        .and(path("/v1/contexts/context-1"))
        .respond_with(ResponseTemplate::new(204))
        .mount(&server)
        .await;
    let gateway = Gateway {
        base_url: server.uri(),
        api_key: "SYNTHETIC_SECRET".into(),
        tenant_id: tenant.into(),
        profile: "test".into(),
    };
    let result = gateway
        .exchange_with(
            &payload,
            &format!("{}/provider", server.uri()),
            None,
            &server.uri(),
            std::time::Duration::from_millis(80),
        )
        .await;
    if fault == "success" {
        assert_eq!(
            result?["choices"][0]["message"]["content"],
            "PRIVATE_SYNTHETIC"
        );
    } else {
        assert!(result.is_err(), "{fault}");
    }
    let requests = server.received_requests().await.unwrap();
    let provider: Vec<_> = requests
        .iter()
        .filter(|r| r.url.path() == "/provider")
        .collect();
    for request in &provider {
        let body: Value = serde_json::from_slice(&request.body)?;
        assert_eq!(body["messages"][0]["content"], "[ALIAS_1]");
        assert!(!String::from_utf8_lossy(&request.body).contains("PRIVATE_SYNTHETIC"));
    }
    for request in requests.iter().filter(|r| r.url.path() == "/v1/decode") {
        assert_eq!(
            serde_json::from_slice::<Value>(&request.body)?["reveal_credentials"],
            false
        );
    }
    if matches!(
        fault,
        "tenant"
            | "profile"
            | "missing_expiry"
            | "expired"
            | "encode_context"
            | "encode_format"
            | "encode_expiry"
            | "encode_policy"
            | "missing_payload"
            | "model_changed"
            | "role_changed"
            | "encode_timeout"
            | "gateway_500"
            | "malformed_json"
    ) {
        assert!(provider.is_empty(), "{fault}");
    }
    assert!(!requests.iter().any(|r| r.url.path() == "/leak"));
    if !matches!(fault, "gateway_500" | "malformed_json") {
        assert!(
            requests.iter().any(|r| r.method == "DELETE"),
            "cleanup: {fault}"
        );
    }
    Ok(())
}

#[tokio::test]
async fn gateway_lifecycle_fails_closed_and_preserves_provider_contract() -> anyhow::Result<()> {
    for fault in [
        "success",
        "tenant",
        "profile",
        "missing_expiry",
        "expired",
        "encode_context",
        "encode_format",
        "encode_expiry",
        "encode_policy",
        "missing_payload",
        "model_changed",
        "role_changed",
        "decode_context",
        "decode_format",
        "unknown_alias",
        "encode_timeout",
        "decode_timeout",
        "provider_timeout",
        "provider_400",
        "provider_503",
        "gateway_500",
        "malformed_json",
        "redirect",
    ] {
        scenario(fault).await?;
    }
    Ok(())
}

#[tokio::test]
async fn cancellation_drops_the_context_without_sending_private_provider_data() -> anyhow::Result<()>
{
    let server = MockServer::start().await;
    let gateway = Gateway {
        base_url: server.uri(),
        api_key: "synthetic".into(),
        tenant_id: "00000000-0000-0000-0000-000000000001".into(),
        profile: "test".into(),
    };
    Mock::given(method("POST")).and(path("/v1/contexts")).respond_with(ResponseTemplate::new(201).set_body_json(json!({"context_id":"cancelled","tenant_id":gateway.tenant_id,"profile":"test","policy_version":"v1","expires_at":(chrono::Utc::now()+chrono::Duration::seconds(120)).to_rfc3339()}))).mount(&server).await;
    Mock::given(method("POST"))
        .and(path("/v1/encode"))
        .respond_with(ResponseTemplate::new(200).set_delay(std::time::Duration::from_secs(10)))
        .mount(&server)
        .await;
    Mock::given(method("DELETE"))
        .and(path("/v1/contexts/cancelled"))
        .respond_with(ResponseTemplate::new(204))
        .mount(&server)
        .await;
    let base = server.uri();
    let task = tokio::spawn(async move {
        gateway
            .exchange_with(
                &json!({"model":"synthetic"}),
                &format!("{base}/provider"),
                None,
                &base,
                std::time::Duration::from_secs(20),
            )
            .await
    });
    for _ in 0..100 {
        if server
            .received_requests()
            .await
            .unwrap()
            .iter()
            .any(|r| r.url.path() == "/v1/encode")
        {
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }
    task.abort();
    let _ = task.await;
    for _ in 0..100 {
        if server
            .received_requests()
            .await
            .unwrap()
            .iter()
            .any(|r| r.method == "DELETE")
        {
            return Ok(());
        }
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }
    anyhow::bail!("cancelled context was not cleaned up")
}
