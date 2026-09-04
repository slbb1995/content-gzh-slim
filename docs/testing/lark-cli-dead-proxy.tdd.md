# Lark CLI dead-proxy fallback — TDD evidence

## User journey

As a content operator, I can run the installed Agent when inherited proxy variables point to the known unavailable local endpoint `127.0.0.1:9`, while valid proxy settings remain unchanged.

## Evidence

| Guarantee | Test | Result |
|---|---|---|
| The Agent removes only known unavailable local proxy values before starting `lark-cli`. | `py -X utf8 -m unittest tests.test_content_source_runtime.ContentSourceRuntimeTests.test_lark_client_drops_only_known_dead_local_proxy` | RED before implementation: `KeyError: 'env'`; GREEN after implementation: `OK`. |
| Existing content-source behaviors still work. | `py -X utf8 -m unittest tests.test_content_source_runtime` | 8 tests passed. |
| The configured Feishu source resolves using the actual runtime path. | `py -X utf8 -c "...resolve_real_source(...)..."` | Resolved `KB-7678020826465078`, `PRF-9ADFA8B3AB957868`, output node `ZvZFw2rxmirbJbk43DscWDx0neh`. |

## Scope and coverage

The unit test covers the exact proxy inheritance failure and preservation of an ordinary proxy. The runtime suite covers source resolution behavior. A project coverage tool is not installed in this environment, so no percentage is reported.
