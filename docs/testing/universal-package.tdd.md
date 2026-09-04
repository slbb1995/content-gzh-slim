# Universal Codex and WorkBuddy package TDD evidence

## Source and user journeys

Journeys were derived from the user request on 2026-09-04.

1. A customer can use one release ZIP with either Codex or WorkBuddy.
2. The same source supports Windows and macOS without embedding a customer path.
3. A WorkBuddy upload sees a root `SKILL.md`, while Codex retains the six-Skill installed package.
4. Every ZIP file is hash-bound to one Git source revision and contains no credentials or customer data.

## RED evidence

Command:

```text
py -X utf8 -B -m unittest tests.test_universal_package -v
```

Initial result: 4 errors. The repository had no WorkBuddy root Skill, host-home resolver, universal ZIP builder, or Windows/macOS CI workflow.

The first WorkBuddy activation integration run then exposed `WinError 206` on a long Windows path. The privacy regression also exposed a JSON-key quoting gap in the first scanner expression. Both failures were preserved as regression tests before the final GREEN run.

The first final-ZIP installation attempt found a third release-only failure: the upload root contained `SKILL.md`, but the archive omitted the committed `workbuddy/SKILL.md` source path required by `release-manifest.json`. The build now retains both the WorkBuddy upload surface and its Git-tracked source mirror.

The next extracted-ZIP installation attempt found a fourth release-only failure: without a `.git` directory, the installer still invoked Git and decoded its localized Windows error as strict UTF-8. A regression now requires both the installer and package builder to read the embedded source revision without invoking Git when operating from an extracted release.

Running the complete verifier from that extracted ZIP then found two packaging-context gaps: the CI contract file was not retained, and the shared activation staging directory added enough path depth to exceed the Windows path limit. The archive now retains the CI workflow, and copy activation stages each Skill in a short leaf directly under the target `skills` directory before exposing it.

The subsequent dual-host installer run exposed the same path-budget problem one stage earlier: the package candidate used both a long temporary directory and the final package name. Candidate construction now uses one short leaf directly under `.packages`, with cleanup preserved on every exit path.

The first native GitHub Actions matrix run passed on macOS but failed Windows release verification because checkout converted `install.py` line endings and invalidated its release hash. The repository and ZIP now include `.gitattributes` with an LF checkout contract so identical Git blobs produce identical verified bytes on both runners.

The second native matrix run completed every Windows verification check, then failed only while printing the Chinese product label to a `cp1252` console. The machine-facing success message is now ASCII-safe; Skill names and Chinese content remain unchanged.

## GREEN evidence

Command:

```text
py -X utf8 -B tools\verify.py
```

Windows result: PASS, version 1.1.0, 6 Skills, 74 release-manifest files, 90 tests.

The WorkBuddy integration test builds an isolated package, activates it in copy mode, runs the active root launcher, and requires `probe` to return `ready`. The universal ZIP test verifies the WorkBuddy root surface, Codex six-Skill tree, file hashes, source revision, privacy flags, extraction, and probe.

## Test specification

| Guarantee | Evidence | Type | Result |
|---|---|---|---|
| Codex and WorkBuddy resolve separate default homes | `test_installer_resolves_codex_and_workbuddy_homes` | unit | PASS |
| WorkBuddy root frontmatter matches `VERSION` | `test_workbuddy_skill_frontmatter_matches_release_version` | contract | PASS |
| ZIP contains both host surfaces and hash-valid files | `test_universal_zip_contains_both_host_surfaces_and_verified_manifest` | integration | PASS |
| Extracted WorkBuddy package probes without Git | `test_workbuddy_activation_is_self_contained_and_probes_without_git` | integration | PASS |
| Extracted revision lookup never invokes Git | `test_extracted_package_revision_fallback_does_not_invoke_git` | regression | PASS |
| Copy activation uses short direct staging leaves | `test_copy_activation_stages_each_skill_directly_under_skills_root` | regression | PASS |
| Package candidate uses one short `.packages` leaf | `test_package_candidate_uses_one_short_leaf_under_packages` | regression | PASS |
| Windows and macOS check out hash-stable LF bytes | `test_ci_runs_universal_package_on_windows_and_macos` | CI contract | PASS |
| Verification success output is safe on ASCII consoles | `test_verify_success_message_is_ascii_console_safe` | regression | PASS |
| Embedded credential assignments fail the build | `test_universal_builder_rejects_embedded_credentials` | security | PASS |
| GitHub CI names Windows and macOS native runners | `test_ci_runs_universal_package_on_windows_and_macos` | structure | PASS |

## Coverage and remaining evidence

`coverage.py` is not installed. Python standard-library `trace` ran all 85 tests from an earlier full pass and showed most runtime modules above 80%, but subprocess-driven CLI modules are undercounted; it is not claimed as an 80% aggregate coverage result. The authoritative local evidence is the 90-test Windows release verification.

GitHub Actions run `33858137947` passed the full contract, release verification, and universal build on both `windows-latest` and `macos-latest` for source revision `36afb3632cae0d1bc4c8e9f11601846aaea43398`. WorkBuddy UI upload recognition is still pending and must not be inferred from isolated filesystem activation.

## Loop decision

- Decision: `writeback`; native Windows/macOS CI and isolated Codex/WorkBuddy activation passed.
- Writeback targets: installer host contract, WorkBuddy root Skill, deterministic package builder, release manifest, CI matrix, and this regression record.
- Next reuse key: `universal_codex_workbuddy_windows_macos_release_zip`.
