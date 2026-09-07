# Installed runtime commands

Resolve the candidate root as the directory three levels above this Skill folder, then use its single launcher:

```text
<candidate-root>/bin/content-gzh-slim
```

The Host owns all backend access and AI outputs. `--store` is optional and defaults to the current host's persistent Content 公众号 Slim Runs directory.

1. Optional first-time binding: run `configure --knowledge-base ...`; show the zero-write preview, then rerun with its exact `--confirmation`.
2. `discover-sources --input ... [--registry ...]` returns only bounded same-library metadata and creates no Run. Select by semantic fit, then `preview-sources --input ... --retrieval-plan ...` reads the selected sources without creating a Run. Evaluate the complete content before freezing. Save exactly the returned `retrieval_plan` containing `selection_snapshot`; use that pinned plan in `start --input ... --retrieval-plan ... [--registry ...] [--store ...]`. Raw reference-only plans are accepted by preview only. `--catalog` is only for repository tests.
3. `prepare-gate-a --input ... --retrieval-plan ... --analysis ... --direction ... [--store ...]`; reuse exactly the start input and retrieval plan.
4. Stop and show Gate A. After an explicit option and exact approval, use `approve-gate-a`.
5. `build-context --run-id ... --selection ... [--store ...]`; Runtime uses the frozen source catalog and revalidates hashes.
6. Invoke Writer with only `article_context_v1.json`, then Headline with that Context and the current draft.
7. `prepare-gate-b --run-id ... --draft-output ... --headline-output ... [--store ...]`
8. Stop and show Gate B. Only after an exact approval, use `approve-gate-b`.
9. Real Runs use `save --run-id ...`; the adapter and target come only from the frozen Manifest. Legacy fixture save commands remain test compatibility paths.
10. `generate-distribution` is optional and requires the exact request `生成分发包` after save. `status` reports the real Run state. No draft-box or publish command exists.

Run `probe` before the first task. It verifies the package manifest, six Skill files, checksums, and the absence of copied credentials or a V1 replacement claim.

The initial internal selection request is not a new customer form or Writer packet:

```json
{
  "knowledge_base_id": "<returned knowledge_base_id>",
  "business_refs": ["<03 object_ref>"],
  "peer_refs": ["<04 peer object_ref>"],
  "method_refs": ["<04 article-method object_ref>"],
  "query_terms": ["optional semantic expansion"],
  "rationale": "Why these viewpoints, scenes and organization serve this audience and thought."
}
```

Use the exact `object_ref` from discovery: vault-relative paths or Feishu document tokens. Runtime verifies containment and source role/workflow; do not relabel an oral-only method to make it pass. Budgets are 5 business, 3 peer, 2 method. `query_terms` can assist legacy ranking but does not replace semantic reasoning. Obsidian discovery supplies metadata, headings and a visibly partial 500-character preview. Feishu discovery supplies titles/node references only; `preview-sources` is essential before asserting suitability. Selected 04 content is complete up to 24000 characters per asset; an oversized source reports a gap instead of silently losing later sections. Discovery caps each root at 200 entries and Feishu at 6 child levels; if a limit is reached, report it.

Preview returns the same plan plus `selection_snapshot`: knowledge-base identity, Manifest/Registry/Profile-index hashes, concrete selected IP, normalized task hash and selected object hashes. Do not hand-author or remove this snapshot. Both start and Gate A preparation compare the live material with the preview; changes require a fresh preview and fresh analysis. This uses the existing source snapshot and adds no human Gate or Writer packet.

Scope fields (`audience_scope`, `usage_scope`, `maturity`, `source_verification`, `claim_scope`) remain attached to selected material through the Context. Explicit `blocked`, `do_not_use` or `forbidden` prohibitions stop selection. Experimental/reference-only or unverified labels remain visible for semantic judgment and must not become confirmed client facts. Legacy Feishu discovery may read more documents to determine their roles before filling the separate peer/method budgets; the receipt reports actual reads. Explicit semantic plans read only their selected objects.

`writing_requirements` in the existing input object is an optional string list of editorial instructions. The frozen task carries it inside the sole Context; it is never a second packet and never a verbatim `must_keep` requirement. Existing inputs without this field retain their prior normalized identity.
