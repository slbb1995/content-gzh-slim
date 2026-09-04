---
name: content-gzh-slim
description: Start, resume, configure, or inspect one Content 公众号 Slim Run from an explicit or confirmed-default Obsidian/Feishu knowledge base and any active IP or none; coordinate bounded 05→03→04 retrieval, two human Gates, verified save, and optional distribution. Never publish.
---

# Content GZH Slim

Use this as the only public entry. It orchestrates one deterministic Run and delegates analysis, Context selection, body writing, headline generation, and optional distribution to the five internal Skills.

## Input and default resolution

- A request may explicitly provide `knowledge_base` and `ip`, or omit either so the Runtime can use a human-confirmed `content-source-v1` default.
- IP resolution is explicit request → workflow default → primary → sole active → ask. Any active Profile may be selected; primary is only a default.
- `none` / `无IP` must be explicit in the request or in confirmed configuration.
- The request shape is `schemas/task_request.schema.json`; the resolved Run still freezes a complete `schemas/task_input.schema.json`.

## Installed workflow

1. Run the bundled `probe` described in [references/runtime-commands.md](references/runtime-commands.md).
2. Resolve exactly one binding from the explicit request or `~/.codex/.content-workflows/knowledge-base-registry.json`. Without Registry, accept an explicit compatible Obsidian path or Feishu space URL. Do not scan the computer.
3. Use the real Obsidian or Feishu source adapter to read the Manifest, Profile index, then bounded 05→03→04 assets. FixtureAdapter is test-only.
4. With an IP, read bounded 05 first, then up to 5 relevant 03 candidates, then up to 3 peer and 2 method candidates from 04. A Feishu 04 root may be traversed at most two levels inside its Manifest-bound subtree; 03 remains direct-child only. Without an IP, skip 05. Record counts and characters.
5. Prepare full snapshots for 0–5 explicit benchmarks. Never call an abstract or snippet a full article.
6. Invoke `content-gzh-analyzer`, validate its deep analysis, and prepare Gate A with a content mode plus an independent voice, professional judgment spine, reader situations, and executable verification actions; show it and stop.
7. After the user selects an option when needed and replies exactly `确认方向`, record the approval and invoke `content-gzh-context-retriever` once. Runtime creates exactly one `article_context_v1.json`.
8. Invoke `content-gzh-writer` with only that Context, then `content-gzh-headline` with the same Context and current draft. Show Gate B and stop.
9. Before P3 and save, re-read Registry, Manifest, Profile index, selected source objects and explicit references. Any hash change stops while preserving artifacts. Only after Gate B save to the Manifest-derived target and verify readback.
10. End the main chain at `saved`. Only an exact later request `生成分发包` may invoke `content-gzh-distribution-pack`; it still does not publish.

The Run freezes one knowledge base, one selected IP or `none`, the task input, source hashes, Manifest revision and reference set. Changing the selected IP creates a different Run even when both Profiles belong to the same knowledge base.

## Gate boundary

The state machine contains exactly two human waiting states: `waiting_direction` and `waiting_final`. Never bypass either. Ambiguous replies do not approve, generate downstream work, or save. Gate A accepts exact `确认方向`; Gate B accepts exact `确认正文和标题` or `使用标题：<明确标题>`.

## Hard boundaries

- Keep source snapshots, Run artifacts, and client idempotency state outside this Git repository.
- The Writer reads one Context Pack and performs zero knowledge-base searches. Do not call a Reviewer, quality checker, old Writer, or title arbitration chain.
- Limited or unavailable IP material never blocks the Run, but must be disclosed; do not invent personal facts, cases, outcomes, or numbers.
- Save is create-only and must pass remote or local readback. Saved never means draft box or published.
- Do not call ZSK at runtime. ZSK may produce the shared file contract; this Skill only reads it.
- Do not copy credentials into the candidate, replace `shu-gongzhonghao-v1`, enter a draft box, or publish.
