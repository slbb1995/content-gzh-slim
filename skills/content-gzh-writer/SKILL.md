---
name: content-gzh-writer
description: Write or revise the content-gzh-slim WeChat article body from its single approved Article Context Pack. Internal only; does not search sources, choose direction, write titles, review, save, distribute, or publish.
---

# Content GZH Writer

For a first draft, read only `article_context_v1.json`. For a revision, additionally read only the current `draft_vN.md` and one concrete user feedback item. Never use a Vault, Feishu, retriever, original source path, old workflow, or second packet.

Use the frozen `writer_mode` and load exactly one matching mode guide:

- `ganhuo`: read [references/ganhuo.md](references/ganhuo.md).
- `huati`: read [references/huati.md](references/huati.md).

Follow `must_keep`, `must_avoid`, approved facts, missing evidence, IP status, and forbidden reference transfers. Return only the complete article body. Do not include a title, analysis, status, source list, save note, tags, or distribution copy. Do not call a Reviewer, AI-flavor check, or automatic polishing pass.

Treat source availability, missing evidence, fact boundaries, candidate status, knowledge-base state, save previews, and writing instructions as private production controls. They must shape what is omitted, qualified, or supported, but they must not be quoted or paraphrased to the reader. Never explain that the article is avoiding customer stories, using only stored materials, lacking a case, following a writing requirement, or substituting one source type for another. Write the supported judgment directly. `must_keep` is reserved for reader-visible exact content; if it contains an apparent private production control, stop instead of exposing it.
