# P9 ganhuo persona TDD evidence

Source plan: user-authorized `EXECUTE_PHASE: P9`, limited to approved items 2—6.

## User journeys

1. As a content owner, I can keep a practical topic in `ganhuo` while still freezing the IP voice and professional judgment spine.
2. As a reader, I receive recognizable situations, explicit judgments, professional explanations, and actions I can execute to verify a claim.
3. As a Profile owner, my identity facts, expression style, judgments, reader empathy, experience facts, and business boundaries remain distinguishable.
4. As a Feishu knowledge-base user, content assets one folder below the04 root are discoverable without traversing beyond two levels or expanding the03 boundary.

## RED and GREEN evidence

The valid RED command was:

```text
py -X utf8 -m unittest tests.test_p3_runtime.P3RuntimeTests.test_context_has_only_spec_fields_and_role_budgets tests.test_p3_runtime.P3RuntimeTests.test_gate_a_rejects_direction_without_viewpoint_spine tests.test_content_source_runtime.ContentSourceRuntimeTests.test_default_binding_resolves_primary_and_reads_real_obsidian tests.test_content_source_runtime.ContentSourceRuntimeTests.test_feishu_content_root_recurses_two_levels_but_not_three tests.test_content_source_runtime.ContentSourceRuntimeTests.test_ganhuo_guide_requires_persona_judgment_and_executable_verification
```

It produced one missing `voice_and_viewpoint` error and seven intended assertion failures. Earlier sandboxed attempts were excluded because Windows denied writes to temporary directories.

The same command after implementation ran five test methods and passed. The full suite command `py -X utf8 -m unittest discover -s tests -p "test_*.py"` ran 79 tests and passed.

| # | Guarantee | Test | Type | Result |
|---|---|---|---|---|
| 1 | Article Context separates content mode from voice and viewpoint. | `test_context_has_only_spec_fields_and_role_budgets` | Integration | PASS |
| 2 | Gate A rejects a direction missing voice, judgments, reader situations, or verification actions. | `test_gate_a_rejects_direction_without_viewpoint_spine` | Integration | PASS |
| 3 | Profile sections retain distinct semantic fragment types and anchors. | `test_default_binding_resolves_primary_and_reads_real_obsidian` | Integration | PASS |
| 4 | Feishu04 reaches depth two and excludes depth three. | `test_feishu_content_root_recurses_two_levels_but_not_three` | Unit | PASS |
| 5 | `ganhuo` Writer contract includes the approved four-part reasoning loop without mechanical repetition. | `test_ganhuo_guide_requires_persona_judgment_and_executable_verification` | Contract | PASS |
| 6 | Existing runtime behavior remains compatible. | full unittest discovery | Regression | PASS, 79 tests |

## Coverage and known gaps

`py -X utf8 -m coverage ...` could not run because the optional `coverage` package is not installed. No dependency was installed. The repository release verifier also remains intentionally blocked until a separately authorized build regenerates release integrity metadata.

## Merge evidence

- RED checkpoint: `ef73308`
- GREEN checkpoint: `6a99d7a`
- At the TDD checkpoint no build or installation had occurred. A later explicit user authorization produced and installed local package `content-gzh-slim-1.0.1` from source revision `2abc24fef9774fcd2f10612087e3130cbc7bb190`; no tag, external Release, external save, or content publication occurred.
