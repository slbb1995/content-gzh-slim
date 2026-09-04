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

## Direction template

Return `mode: single` with one complete option when the topic or user thoughts provide a direction. When both are insufficient, return `mode: options` with exactly three complete options.

Every option must include:

- `option_id`, `title`, `speaker`, `target_audience`;
- `core_judgment`, `promise`, `why_now`;
- `writer_mode` (`ganhuo` or `huati`) and `writer_mode_reason`;
- `voice_mode`, which is independent from `writer_mode` and states how the selected IP or neutral speaker should sound;
- `professional_judgments`: the explicit judgment spine the article will argue, not a switch to `huati`;
- `reader_situations`: concrete situations in which the target reader recognizes the problem;
- `verification_actions`: actions the reader can execute on site or before deciding, each naming what to do and what to observe;
- ordered `structure`, with each section's purpose;
- `selected_sources` split into `business_refs`, `peer_refs`, `method_refs`, and `reference_refs`;
- `benchmark_transfer` and `forbidden_transfer`;
- `knowledge_materials`, `business_connection`, and `fact_boundaries`;
- `first_person_claims`, which must be empty for `limited`, `unused`, or `none` IP unless an explicitly confirmed supplied fragment supports it;
- `must_keep` and `must_avoid`.

Only select refs present in the supplied bounded candidates or complete reference snapshots. Treat all selections as Gate A proposals, not final selections and not Context Pack content.

For `ganhuo`, viewpoints are still required. Content mode controls the value delivered; `voice_mode` and the judgment spine control how the IP connects that value to the reader. Do not turn a practical topic into `huati` merely because the user asks for stronger personality or clearer opinions.

## Gate A boundary

The public entry renders the direction. Do not approve it. Valid user decisions are exactly:

- `确认方向`
- `需要修改：<具体意见>`
- `不采用`

Any vague reply remains unapproved.
