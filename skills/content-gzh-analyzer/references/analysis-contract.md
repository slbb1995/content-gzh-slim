# Analyzer output contract

## Reference analysis

Analyze each complete reference independently before comparing them. Preserve one object per source with all fields below:

1. `title_mechanism`: title mechanism and click tension.
2. `opening_hook`: first-screen hook and how it earns attention.
3. `target_reader_and_promise`: intended reader and core promise.
4. `sections`: complete ordered structure; each item states that section's function.
5. `conflict`: how tension or conflict is established.
6. `argument_and_evidence`: reasoning order and evidence placement.
7. `cases_numbers_details`: what examples, numbers, and concrete details do.
8. `transitions`: turns and paragraph-to-paragraph bridges.
9. `emotion_and_pacing`: emotional curve and pacing.
10. `ending_and_cta`: ending mechanism and CTA.
11. `transferable_mechanisms`: reusable hook, structure, argument, or pacing mechanisms.
12. `forbidden_transfers`: identity, experience, cases, proprietary facts, recognizable wording, and promises that must not transfer.

Mark `source_completeness` as `full`. Never analyze a title, abstract, or summary as if it were the full article.

For two or more references, also provide `multi_reference_synthesis` with:

- `common_mechanisms`;
- `differences`;
- `conflict_resolution`, explaining which mechanism wins for this task and why.

With no references, return an empty analysis list and `multi_reference_synthesis: null`; do not invent benchmark findings.

## From one thought to a useful article

Prioritize an explicit benchmark when supplied, but judge its fit to the client's purpose. With no benchmark, use supplied library peers for substantive value: topic motivation, general viewpoints, audience situations, reasoning and concrete detail roles. Use supplied methods to organize and strengthen that content. Neither a peer nor a method must be forced into a draft when irrelevant. Describe the selected material's specific contribution in `knowledge_materials`, and make each `structure` section explain how the argument develops and where supporting material belongs. Return one recommended direction when the thought is clear; structure comparisons belong in internal reasoning, not another customer questionnaire.

Read `source_metadata` and the complete selected sections. Respect `applicable_workflows`, use/avoid conditions and explicit local usage boundaries. Experimental labels are context for judgment, not universal exclusion; explicit prohibitions still apply. An oral-only method is not an article method. A peer can supply general content value, but cannot supply the client's personal history, customer cases or proprietary facts. When the selected material cannot support the intended claim, state the missing evidence in `fact_boundaries` and explain the gap; do not call a source-free direction library-backed.

In particular, retain and apply `audience_scope`, `usage_scope`, `maturity`, `source_verification` and `claim_scope`. Internal training or source-only material cannot silently become a public-facing client claim; unverified material stays unverified. Runtime rejects explicit prohibitions and preserves the remaining conditions for task-specific judgment.

For 03, `status: active` describes an available asset, not proof of a current client fact. `local_original_hash_verified` verifies the source file's identity only. Material marked `reference_with_fact_check`, `requires_current_fact_check`, `source_only`, candidate or reference-only cannot be selected as a confirmed business fact; report the specific verification gap. Missing-field legacy compatibility does not authorize assuming that an old asset has been checked for this task.

`writing_requirements` controls how to write. `must_keep` is only exact article content explicitly requested by the user; copy the frozen task's `must_keep` and `must_avoid` unchanged. Keep business viewpoints in `user_thoughts`; do not turn internal requests such as emphasizing professional judgment into literal draft sentences.

## Direction template

Return `mode: single` with one complete option when the topic or user thoughts provide a direction. When both are insufficient, return `mode: options` with exactly three complete options.

Every option must include:

- `option_id`, `title`, `speaker`, `target_audience`;
- `core_judgment`, `promise`, `why_now`;
- `writer_mode` (`ganhuo` or `huati`) and `writer_mode_reason`;
- ordered `structure`, with each section's purpose;
- `selected_sources` split into `business_refs`, `peer_refs`, `method_refs`, and `reference_refs`;
- `benchmark_transfer` and `forbidden_transfer`;
- `knowledge_materials`, `business_connection`, and `fact_boundaries`;
- `first_person_claims`, which must be empty for `limited`, `unused`, or `none` IP unless an explicitly confirmed supplied fragment supports it;
- `must_keep` and `must_avoid`.

`must_keep` contains only reader-visible exact content that is intended to appear verbatim in the article. Never place private production controls there, including internal source-availability notes, knowledge-base status, instructions not to invent a case, or explanations of how the article should be written. Use the frozen task's `writing_requirements` for editorial instructions, and retain relevant boundaries in `fact_boundaries`, `forbidden_transfer`, or `must_avoid`; they constrain generation and are not article copy. Reader-relevant evidence limitations, legitimate source attribution and business requirements remain allowed; do not treat a mere mention of materials or requirements as a private instruction.

Only select refs present in the supplied bounded candidates or complete reference snapshots. Treat all selections as Gate A proposals, not final selections and not Context Pack content.

## Gate A boundary

The public entry renders the direction. Do not approve it. Valid user decisions are exactly:

- `确认方向`
- `需要修改：<具体意见>`
- `不采用`

Any vague reply remains unapproved.
