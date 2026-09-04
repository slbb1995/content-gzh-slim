# Article Context selection contract

## Preconditions

- The Run must be `direction_approved` through the dedicated Gate A interface with exact decision `确认方向`.
- `run_id`, input digest, knowledge base, IP, task input, direction artifact and retrieval receipt must agree.
- A direction with multiple options is invalid unless the Gate receipt binds one exact option. Never guess the chosen option.

## Selection output

Return one object containing:

- `selected_05_fragment_ids`: at most three confirmed fragments from the same resolved IP; empty for `none` or `unused`.
- `selected_03_refs`: at most five confirmed business refs already proposed by the approved direction.
- `selected_04_peer_refs`: exactly the approved peer refs, at most three.
- `selected_04_method_refs`: exactly the approved method refs, at most two.
- `reference_mechanisms`: one entry per approved explicit reference, containing only selected transferable mechanisms and forbidden-transfer boundaries found in its analysis.
- `missing_evidence`: concise unresolved evidence gaps that Writer must preserve.
- `save_target_preview`: a non-writable preview derived from the current knowledge base identity.

Runtime also carries the approved `voice_mode`, `professional_judgments`, `reader_situations`, and `verification_actions` into `voice_and_viewpoint`. Profile anchors are section-aware: identity facts, expression style, professional judgments, reader empathy, experience facts, and business boundaries must remain distinguishable.

## Role boundaries

- 05 supplies only the current IP's categorized identity anchors and confirmed quotes, stories, recent judgments or actions. A professional opinion may use the IP voice; a first-person experience still requires an explicitly selected confirmed experience fragment.
- 03 supplies confirmed current-business facts. Candidate claims stay excluded and visibly labeled as non-facts.
- 04 peer assets supply general content angles; 04 method assets supply hook, structure, pacing and CTA methods.
- References supply mechanisms only. Never copy the body, author identity, experience, cases, data, screenshots or recognizable wording.

## Unique Writer input

Runtime assembles exactly one `article_context_v1.json` with the Master SPEC 11.2 fields. Do not create Source Pack, Writing Packet, Markdown Context, review material or another Writer-readable file.
