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

## Role boundaries

- 05 supplies only the current IP's identity anchors and confirmed quotes, stories, recent judgments or actions.
- 03 supplies confirmed current-business facts. Candidate claims stay excluded and visibly labeled as non-facts.
- An active 03 asset or a verified original-file hash does not by itself establish a current client fact. Preserve reference-only/source-only and pending-fact-check restrictions; Runtime marks these explicit metadata signals as `candidate`, so they cannot enter the confirmed 03 projection.
- 04 peer assets supply general angles, viewpoints, scene/detail functions and reasoning value; 04 method assets supply complete organization, argument, pacing and ending methods. Runtime projects the selected complete source sections and `source_metadata`; do not thin them into generic summaries or erase use boundaries. Neither role supplies the client's identity, cases or proprietary facts.
- References supply mechanisms only. Never copy the body, author identity, experience, cases, data, screenshots or recognizable wording.

## Unique Writer input

Runtime assembles exactly one `article_context_v1.json` with the Master SPEC 11.2 fields. Do not create Source Pack, Writing Packet, Markdown Context, review material or another Writer-readable file.
