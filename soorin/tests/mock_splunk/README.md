# Splunk/Agentic SOC synthetic Statements test kit

A **local-only integration test** for Utopia rc9's `statements` push source. No Splunk, Kafka, Jira or Agentic SOC service is contacted by the script.

## Files

- `fixtures/synthetic_splunk_soc.json`: 9 synthetic records: 2 ES notables, 3 fused alerts, 2 Windows 4625 event examples, 1 SOC case, 1 Jira ticket.
- `scripts/soc_mock.py`: offline validation, e/s/n rendering and authenticated push.
- `tests/test_soc_mock.py`: standard-library unit tests.

The seeded password-spray event is modeled after previously discussed **patterns**, not copied production logs. All literal hosts, users, IPs and SIDs are fictitious; `192.0.2.0/24`, `198.51.100.0/24`, and `example` are documentation-only namespaces.

## Quick start

```bash
python3 soorin/tests/mock_splunk/scripts/soc_mock.py validate
python3 -m unittest discover -s soorin/tests/mock_splunk/tests -v
python3 soorin/tests/mock_splunk/scripts/soc_mock.py render --output-dir /tmp/soorin-soc-statements
```

Then in the Utopia UI, select the **Soorin SOC Lab** knowledge base, create a **Statements** source named `Splunk SOC Synthetic Lab`, copy the source UUID and its ingest token:

```bash
export UTOPIA_SOURCE_ID='<uuid>'
# Zsh (Bash uses: read -rsp 'Source token: ' UTOPIA_INGEST_TOKEN)
read -rs 'UTOPIA_INGEST_TOKEN?Source token: '; echo
export UTOPIA_INGEST_TOKEN
python3 soorin/tests/mock_splunk/scripts/soc_mock.py push --replay
unset UTOPIA_INGEST_TOKEN
```

Expected: 9 `created` on first-ever push and 9 `unchanged` on identical replay; a prior run may make the first pass unchanged. Any HTTP failure is a failing test.

`render` creates one well-formed JSON body per event for inspection. **Do not commit operational tokens or real event data.** This lab does not assert that Utopia has completed typed graph alignment; inspect Library, Graph, Review, Ontology and logs separately.

See [the full runbook](../../../docs/soorin/local-smoke.md) and [field mapping](../../../docs/soorin/splunk-mapping.md).
