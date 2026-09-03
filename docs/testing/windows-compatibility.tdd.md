# Windows compatibility TDD evidence

Source plan: user-authorized `content-source-v1-release` Windows compatibility repair.

## User journeys

1. As a Windows user, I can verify a release containing Chinese output without a locale-dependent decode failure.
2. As a Windows user, persisted UTF-8 artifacts and profile fixtures have hashes derived from their actual bytes.
3. As an operator, unsafe POSIX, drive-letter, UNC, NUL, traversal, and protected save targets are rejected on every host.
4. As an installer, I can activate all six skills without symlink permission, and a partial activation is rolled back.

## RED and GREEN evidence

The initial RED run was `py -X utf8 -B -m unittest tests.test_windows_compat -v`.
It executed the new test target and demonstrated the missing `_run_utf8` helper, unsafe path forms accepted by `validate_target_preview`, and absent activation fallback/rollback behavior. The sandbox also denied its system temporary directory; reruns used an isolated repository temporary directory.

| # | Guarantee | Test / command | Type | Result |
|---|---|---|---|---|
| 1 | Verification subprocesses use strict UTF-8 decoding. | `tests.test_windows_compat.WindowsCompatibilityTests.test_verify_subprocesses_request_utf8_text_decoding` | Unit | PASS |
| 2 | Persisted artifact bytes are stable UTF-8 and match the digest input. | `tests.test_windows_compat.WindowsCompatibilityTests.test_artifact_text_hash_is_calculated_from_persisted_utf8_bytes` | Unit | PASS |
| 3 | Cross-platform absolute, separator, traversal, protected, and NUL save references are rejected. | `tests.test_windows_compat.WindowsCompatibilityTests.test_save_target_rejects_all_host_absolute_and_escape_forms` | Unit | PASS |
| 4 | Copy-mode activation rolls back every newly-created skill after a failure. | `tests.test_windows_compat.WindowsCompatibilityTests.test_activation_falls_back_to_copy_and_rolls_back_partial_new_entries` | Integration | PASS |
| 5 | A Windows candidate bundle can use the Python launcher and a copy fallback. | `tests.test_p7_runtime` | Integration | PASS |
| 6 | Release integrity, full suite, and CLI smoke pass. | `py -X utf8 -B tools\\verify.py` | Release | PASS: 70 files, 6 skills |
| 7 | A clean temporary CODEX_HOME can install and activate all six skills. | `py -X utf8 -B install.py --codex-home <temporary> --activate` | Install | PASS: `activation mode: copy`, 6 skills |

## Coverage and known gaps

The project has no configured coverage runner and `py -X utf8 -m coverage --version` reported that the optional `coverage` module is not installed. No dependency was installed for this repair. The complete unittest suite and release verifier passed on Windows. WSL discovery was attempted but denied by the host (`Wsl/EnumerateDistros/Service/E_ACCESSDENIED`), so no WSL run was possible.
