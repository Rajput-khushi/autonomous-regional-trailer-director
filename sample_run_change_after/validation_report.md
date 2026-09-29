# STAGE Content Director — Validation & Audit Report

- **Overall Run Status**: `PASS_WITH_WARNINGS`
- **Mode**: `replay`
- **Scenario**: `clean`
- **Estimated Cost**: `$0.0800` / Budget `$2.00`

---

## 1. Trailer Plans Summary

| Trailer ID | Audience | Duration | Status | Violations / Warnings |
| :--- | :--- | :--- | :--- | :--- |
| `dialect_region_v1` | `dialect_region` | `38.0s` | **PASS_WITH_WARNINGS** | WARN: SPOILER_MEDIUM, NATIVE_REVIEW_PENDING, NATIVE_REVIEW_PENDING, ACCESS_LINE_TOO_LONG |
| `family_v1` | `family` | `38.0s` | **PASS** | All checks passed |
| `young_adult_v1` | `young_adult` | `41.0s` | **PASS_WITH_WARNINGS** | WARN: INJECTION_DETECTED, SPOILER_MEDIUM |

---

## 2. Distinctness Audit

- **Pairwise Source Second Overlap**: {'dialect_region_v1__vs__family_v1': {'overlap_seconds': 0.0, 'shorter_duration_s': 38.0, 'overlap_ratio': 0.0, 'within_target': True}, 'dialect_region_v1__vs__young_adult_v1': {'overlap_seconds': 0.0, 'shorter_duration_s': 38.0, 'overlap_ratio': 0.0, 'within_target': True}, 'family_v1__vs__young_adult_v1': {'overlap_seconds': 0.0, 'shorter_duration_s': 38.0, 'overlap_ratio': 0.0, 'within_target': True}}
- **Max Overlap Ratio**: `0.0%` (target <= 25%)
- **First Segments Unique**: `True`
- **Taglines Unique**: `True`

---

## 3. Repair & Revision Log

| Rev # | Trigger | Affected | Action | Validation |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `repair:RIGHTS_EXPIRED` | `dialect_region_v1.segment_04` | Swapped music asset to compatible music_05 on segment_04 (attempt 1) | `PASS` |
| 1 | `repair:RIGHTS_EXPIRED` | `family_v1.segment_02` | Swapped music asset to compatible music_05 on segment_02 (attempt 1) | `PASS` |

---

## 4. Human Review & Advisories

No blocking human review items flagged.

---

## 5. Known Limitations

- Dialect correctness is evaluated using synthetic tag alignment proxies (native speaker review pending).
- Historical high performance does not override editorial truth or spoiler reveal windows.
- Machine checks verify compliance; human editorial approval is required prior to external broadcast.
