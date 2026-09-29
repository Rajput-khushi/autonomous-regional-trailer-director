# STAGE Content Director — Validation & Audit Report

- **Overall Run Status**: `PASS_WITH_WARNINGS`
- **Mode**: `replay`
- **Scenario**: `traps`
- **Estimated Cost**: `$0.0800` / Budget `$5.00`

---

## 1. Trailer Plans Summary

| Trailer ID | Audience | Duration | Status | Violations / Warnings |
| :--- | :--- | :--- | :--- | :--- |
| `family_v1` | `family` | `34.0s` | **PASS** | All checks passed |
| `young_adult_v1` | `young_adult` | `37.0s` | **PASS_WITH_WARNINGS** | WARN: INJECTION_DETECTED, SPOILER_MEDIUM |
| `dialect_region_v1` | `dialect_region` | `32.0s` | **PASS_WITH_WARNINGS** | WARN: SPOILER_MEDIUM, NATIVE_REVIEW_PENDING, NATIVE_REVIEW_PENDING, ACCESS_LINE_TOO_LONG, ACCESS_LINE_TOO_LONG |

---

## 2. Distinctness Audit

- **Pairwise Source Second Overlap**: {'dialect_region_v1__vs__family_v1': {'overlap_seconds': 0.0, 'shorter_duration_s': 32.0, 'overlap_ratio': 0.0, 'within_target': True}, 'dialect_region_v1__vs__young_adult_v1': {'overlap_seconds': 0.0, 'shorter_duration_s': 32.0, 'overlap_ratio': 0.0, 'within_target': True}, 'family_v1__vs__young_adult_v1': {'overlap_seconds': 0.0, 'shorter_duration_s': 34.0, 'overlap_ratio': 0.0, 'within_target': True}}
- **Max Overlap Ratio**: `0.0%` (target <= 25%)
- **First Segments Unique**: `True`
- **Taglines Unique**: `True`

---

## 3. Repair & Revision Log

| Rev # | Trigger | Affected | Action | Validation |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `repair:RIGHTS_PROMO_NOT_PERMITTED,STORY_FORBIDDEN_CLAIM,STORY_RELATION_MISMATCH,STORY_RELATION_MISMATCH` | `family_v1.segment_04` | Replaced segment segment_04 (RIGHTS_PROMO_NOT_PERMITTED,STORY_FORBIDDEN_CLAIM,STORY_RELATION_MISMATCH,STORY_RELATION_MISMATCH) with valid footage from scene_01 [00:00:22.000, 00:00:26.000) preserving role stakes_conflict (attempt 1) | `PASS` |
| 1 | `repair:STORY_GENRE_MISMATCH` | `young_adult_v1.segment_03` | Replaced segment segment_03 (STORY_GENRE_MISMATCH) with valid footage from scene_01 [00:00:30.000, 00:00:34.000) preserving role escalation (attempt 1) | `PASS` |
| 1 | `repair:SPOILER_MAJOR` | `dialect_region_v1.segment_03` | Replaced segment segment_03 (SPOILER_MAJOR) with valid footage from scene_01 [00:00:09.000, 00:00:13.000) preserving role conflict (attempt 1) | `PASS` |

---

## 4. Human Review & Advisories

No blocking human review items flagged.

---

## 5. Known Limitations

- Dialect correctness is evaluated using synthetic tag alignment proxies (native speaker review pending).
- Historical high performance does not override editorial truth or spoiler reveal windows.
- Machine checks verify compliance; human editorial approval is required prior to external broadcast.
