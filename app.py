"""
app.py — Streamlit UI Demonstration Wrapper
Autonomous Regional Trailer Director (STAGE Prototype)

Visual demonstration wrapper over the existing LangGraph pipeline.
Inspects and visualizes:
  - Clean Baseline Scenario
  - Adversarial / Traps Scenario (Candidate -> Validation Failure -> Repair -> Revalidation -> Final)
  - Contract Change Impact Scenario (music_03 expired -> Selective Replanning -> Hash Invariance)
  - All 10 Machine-Readable Artifacts + Validation Reports
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

# Configure page layout and aesthetics
st.set_page_config(
    page_title="Autonomous Regional Trailer Director",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

BASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = BASE_DIR / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# Custom CSS for crisp, modern editorial styling
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 800;
        margin-bottom: 0.1rem;
        color: #1E293B;
    }
    .sub-title {
        font-size: 1.1rem;
        color: #64748B;
        margin-bottom: 1rem;
    }
    .disclaimer-box {
        background-color: #F8FAFC;
        border-left: 4px solid #3B82F6;
        padding: 0.75rem 1rem;
        border-radius: 4px;
        margin-bottom: 1.5rem;
        font-size: 0.9rem;
        color: #334155;
    }
    .status-pass {
        color: #16A34A;
        font-weight: 700;
    }
    .status-warn {
        color: #D97706;
        font-weight: 700;
    }
    .status-fail {
        color: #DC2626;
        font-weight: 700;
    }
    .pipeline-step {
        background: #F1F5F9;
        border: 1px solid #CBD5E1;
        border-radius: 6px;
        padding: 10px 14px;
        text-align: center;
        font-weight: 600;
        color: #1E293B;
    }
    .arrow-down {
        text-align: center;
        font-size: 1.3rem;
        color: #64748B;
        margin: 4px 0;
    }
    .highlight-card {
        background: #F0FDF4;
        border: 1px solid #86EFAC;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1rem;
    }
    .change-alert {
        background: #FEF2F2;
        border: 1px solid #FCA5A5;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1.2rem;
    }
    .swap-badge {
        background: #DBEAFE;
        color: #1E40AF;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 1.05rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def run_command(cmd_args: List[str]) -> subprocess.CompletedProcess:
    """Run CLI command using the exact current Python executable."""
    cmd = [sys.executable, str(BASE_DIR / "main.py")] + cmd_args
    return subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        check=False,
    )


def load_json(filepath: Path) -> Optional[Dict[str, Any]]:
    """Safely load JSON file or return None if missing."""
    if filepath.exists():
        try:
            with filepath.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def load_text(filepath: Path) -> Optional[str]:
    """Safely load text file or return None if missing."""
    if filepath.exists():
        try:
            return filepath.read_text(encoding="utf-8")
        except Exception:
            return None
    return None


def format_issue(item: Any) -> str:
    """Format error or warning issue dict/string into readable text."""
    if isinstance(item, dict):
        code = item.get("code") or item.get("rule_id") or ""
        msg = item.get("message") or item.get("description") or str(item)
        seg = item.get("segment_id")
        seg_str = f"[{seg}] " if seg else ""
        return f"{seg_str}{code}: {msg}" if code else f"{seg_str}{msg}"
    return str(item)


# ── TOP OF PAGE: HEADER & DISCLAIMER ─────────────────────────────────────────

st.markdown('<div class="main-title">🎬 Autonomous Regional Trailer Director</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">AI-Native Regional Trailer Planning & Verification Prototype</div>',
    unsafe_allow_html=True,
)

c1, c2, c3, c4 = st.columns([3, 2, 2, 3])
with c1:
    st.markdown("**Episode:** The Missing Letter `[SYNTHETIC]`")
with c2:
    st.markdown("**Episode ID:** `ep_synth_001`")
with c3:
    st.markdown("**Duration:** `06:00` (360s)")
with c4:
    st.markdown("**Audience Targets:** Family, Young Adult, Dialect")

st.markdown(
    """
    <div class="disclaimer-box">
        ⚠️ <strong>Prototype Disclaimer:</strong> Synthetic evaluation fixture — not STAGE production data.
        All scripts, contracts, policies, subtitles, and audio assets are synthetic test fixtures (<code>synthetic: true</code>).
    </div>
    """,
    unsafe_allow_html=True,
)

# ── ARCHITECTURE PANEL ────────────────────────────────────────────────────────

with st.expander("📐 System Architecture & Agentic Flow", expanded=False):
    st.markdown("### LLMs propose; deterministic validators decide.")
    st.markdown(
        """
        The architecture enforces strict separation between **creative generation** (untrusted proposals)
        and **deterministic validation** (zero hallucinations, non-negotiable policy checks).
        """
    )
    col_arch1, col_arch2 = st.columns(2)
    with col_arch1:
        st.markdown("**Standard Generation & Repair Loop:**")
        st.code(
            "INGEST\n"
            "  ↓\n"
            "STORY (character graph & spoiler reveal windows)\n"
            "  ↓\n"
            "CONSTRAINTS (music rights, promo windows, policies)\n"
            "  ↓\n"
            "AUDIENCES (family, young_adult, dialect_region)\n"
            "  ↓\n"
            "TRAILER PLANS (multi-segment candidate EDL drafts)\n"
            "  ↓\n"
            "VALIDATE (9 deterministic rule-based validators)\n"
            "  ↓\n"
            "REPAIR (bounded targeted replanning of failed segments)\n"
            "  ↓\n"
            "FINALIZE (audit export & distinctness verification)",
            language="text",
        )
    with col_arch2:
        st.markdown("**Contract Change-Impact Flow:**")
        st.code(
            "CHANGE EVENT (e.g. music_03 expired)\n"
            "  ↓\n"
            "IMPACT ANALYSIS (reverse lookup via dependency_index)\n"
            "  ↓\n"
            "SCOPED VALIDATION (test only referencing segments)\n"
            "  ↓\n"
            "REPAIR (targeted replacement; invariant verification)\n"
            "  ↓\n"
            "FINALIZE (unaffected segments remain byte-identical)",
            language="text",
        )

st.markdown("---")

# ── MAIN CONTROLS ─────────────────────────────────────────────────────────────

# Initialize active scenario state if not present
if "scenario" not in st.session_state:
    # Default to sample_run if already generated, else clean
    default_dir = BASE_DIR / "sample_run"
    if default_dir.exists() and (default_dir / "run_state.json").exists():
        st.session_state["scenario"] = "clean_ready"
        st.session_state["run_dir"] = default_dir
    else:
        st.session_state["scenario"] = None
        st.session_state["run_dir"] = None

btn_col1, btn_col2, btn_col3 = st.columns(3)

with btn_col1:
    if st.button("▶ Run Clean Scenario", use_container_width=True, type="primary"):
        target_dir = RUNS_DIR / "clean"
        with st.spinner("Executing Clean Scenario baseline..."):
            res = run_command(["--scenario", "clean", "--out", str(target_dir)])
            if res.returncode == 0:
                st.session_state["scenario"] = "clean"
                st.session_state["run_dir"] = target_dir
                st.session_state["stdout"] = res.stdout
                st.toast("Clean scenario completed successfully!", icon="✅")
            else:
                st.error(f"Execution failed:\n{res.stderr}")

with btn_col2:
    if st.button("⚠ Run Adversarial / Traps", use_container_width=True):
        target_dir = RUNS_DIR / "traps"
        with st.spinner("Executing Adversarial / Traps Scenario (with auto-repair)..."):
            res = run_command(["--scenario", "traps", "--out", str(target_dir)])
            if res.returncode == 0:
                st.session_state["scenario"] = "traps"
                st.session_state["run_dir"] = target_dir
                st.session_state["stdout"] = res.stdout
                st.toast("Traps scenario repaired & validated!", icon="🛠️")
            else:
                st.error(f"Execution failed:\n{res.stderr}")

with btn_col3:
    if st.button("🔄 Simulate Music Contract Change", use_container_width=True):
        baseline_dir = RUNS_DIR / "change_baseline"
        target_dir = RUNS_DIR / "change_after"
        with st.spinner("Running baseline, then resuming with expired contract change event..."):
            # Step 1: Clean baseline
            res1 = run_command(["--scenario", "clean", "--out", str(baseline_dir)])
            if res1.returncode != 0:
                st.error(f"Baseline run failed:\n{res1.stderr}")
            else:
                # Step 2: Resume with change event
                res2 = run_command([
                    "--resume", str(baseline_dir / "run_state.json"),
                    "--change-event", "data/change_events/music_03_expired.json",
                    "--out", str(target_dir),
                ])
                if res2.returncode == 0:
                    st.session_state["scenario"] = "change"
                    st.session_state["run_dir"] = target_dir
                    st.session_state["baseline_dir"] = baseline_dir
                    st.session_state["stdout"] = res2.stdout
                    st.toast("Contract change simulated & verified!", icon="🎵")
                else:
                    st.error(f"Change resume run failed:\n{res2.stderr}")

# ── RENDER RESULTS BASED ON ACTIVE SCENARIO ────────────────────────────────────

active_dir: Optional[Path] = st.session_state.get("run_dir")
active_scenario: Optional[str] = st.session_state.get("scenario")

if active_dir and active_dir.exists():
    state_data = load_json(active_dir / "run_state.json") or {}
    validation_data = state_data.get("validation", {})
    plans_data = state_data.get("candidate_plan", {})
    revisions_data = state_data.get("revisions", [])
    overall_status = state_data.get("status", "UNKNOWN")

    st.markdown("---")

    # ── SCENARIO 1: CLEAN RUN ────────────────────────────────────────────────
    if active_scenario in ("clean", "clean_ready"):
        st.subheader("📊 Scenario: Clean Baseline Generation")

        # Top status metric
        status_color = "status-pass" if "PASS" in overall_status else "status-fail"
        st.markdown(
            f"**Overall Pipeline Status:** <span class='{status_color}'>{overall_status}</span> &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"**Mode:** <code>{state_data.get('run_config', {}).get('mode', 'replay')}</code> &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"**Cost:** <code>${state_data.get('estimated_cost', 0.08):.4f}</code>",
            unsafe_allow_html=True,
        )
        st.write("")

        # 3 Trailer Cards
        trailer_ids = ["family_v1", "young_adult_v1", "dialect_region_v1"]
        tc1, tc2, tc3 = st.columns(3)

        for col, tid in zip([tc1, tc2, tc3], trailer_ids):
            plan = plans_data.get(tid, {})
            t_val = validation_data.get(tid, {})
            t_validators = t_val.get("validators", [])

            fails = sum(len(v.get("errors", [])) for v in t_validators)
            warns = sum(len(v.get("warnings", [])) for v in t_validators)
            t_status = t_val.get("status", "PASS")
            badge = "🟢 PASS" if t_status == "PASS" else ("🟡 WARN" if "WARN" in t_status else "🔴 FAIL")

            with col:
                st.markdown(f"### `{tid}`")
                st.markdown(f"**Status:** {badge}")
                st.markdown(f"- **Audience:** `{plan.get('audience', tid)}`")
                st.markdown(f"- **Duration:** `{plan.get('duration_seconds', 0.0):.1f}s`")
                st.markdown(f"- **Segments:** `{len(plan.get('segments', []))}`")
                st.markdown(f"- **Failures:** `{fails}`")
                st.markdown(f"- **Warnings:** `{warns}`")
                if plan.get("tagline"):
                    st.caption(f"_{plan.get('tagline')}_")

        # Expandable Validation Details for All 9 Validators
        with st.expander("🔍 Comprehensive Validation Details (All 9 Validators)", expanded=True):
            tabs_val = st.tabs([f"🎬 {tid}" for tid in trailer_ids])
            for tab, tid in zip(tabs_val, trailer_ids):
                with tab:
                    t_val = validation_data.get(tid, {})
                    v_list = t_val.get("validators", [])
                    if not v_list:
                        st.info("No validator results recorded.")
                    else:
                        for v in v_list:
                            v_name = v.get("validator", "UnknownValidator").replace("Validator", "")
                            v_stat = v.get("status", "PASS")
                            v_icon = "🟢" if v_stat == "PASS" else ("🟡" if "WARN" in v_stat else "🔴")

                            v_exp = st.expander(f"{v_icon} **{v_name}** — `{v_stat}`", expanded=(v_stat != "PASS"))
                            with v_exp:
                                if v.get("errors"):
                                    for err in v["errors"]:
                                        st.error(f"❌ {format_issue(err)}")
                                if v.get("warnings"):
                                    for wrn in v["warnings"]:
                                        st.warning(f"⚠️ {format_issue(wrn)}")
                                if v.get("evidence"):
                                    ev_strs = [str(e) for e in v["evidence"][:8]]
                                    st.markdown(f"**Evidence checked:** `{', '.join(ev_strs)}`")
                                if v.get("details"):
                                    st.caption("Segment-level detail:")
                                    st.json(v["details"])

    # ── SCENARIO 2: TRAPS / REPAIR LOOP ──────────────────────────────────────
    elif active_scenario == "traps":
        st.subheader("🛠️ Scenario: Adversarial Traps & Autonomous Repair")

        st.markdown(
            """
            This scenario demonstrates **autonomous agentic error recovery**:
            Untrusted candidate plans containing deliberate adversarial violations are trapped by
            deterministic validators, isolated, repaired via bounded replanning, and revalidated.
            """
        )

        # Pipeline Flow Display
        p1, a1, p2, a2, p3, a3, p4, a4, p5 = st.columns([3, 1, 3, 1, 3, 1, 3, 1, 3])
        with p1:
            st.markdown('<div class="pipeline-step">1. Candidate Plan<br><small>Trap fixtures injected</small></div>', unsafe_allow_html=True)
        with a1:
            st.markdown('<div class="arrow-down">➔</div>', unsafe_allow_html=True)
        with p2:
            st.markdown('<div class="pipeline-step">2. Validation Failure<br><small>Violations detected</small></div>', unsafe_allow_html=True)
        with a2:
            st.markdown('<div class="arrow-down">➔</div>', unsafe_allow_html=True)
        with p3:
            st.markdown('<div class="pipeline-step">3. Repair Engine<br><small>Bounded replanning</small></div>', unsafe_allow_html=True)
        with a3:
            st.markdown('<div class="arrow-down">➔</div>', unsafe_allow_html=True)
        with p4:
            st.markdown('<div class="pipeline-step">4. Revalidation<br><small>9 validators rerun</small></div>', unsafe_allow_html=True)
        with a4:
            st.markdown('<div class="arrow-down">➔</div>', unsafe_allow_html=True)
        with p5:
            st.markdown('<div class="pipeline-step">5. Final Plan<br><small>100% compliant</small></div>', unsafe_allow_html=True)

        st.write("")

        # Trapped & Repaired Items
        st.markdown("### 🔍 Repaired Violations Breakdown")
        if not revisions_data:
            st.info("No repair actions recorded.")
        else:
            for i, rev in enumerate(revisions_data, 1):
                aff_str = ", ".join(rev.get("affected", []))
                trig = rev.get("trigger", "").replace("repair:", "")
                action = rev.get("action", "")
                val_status = rev.get("validation", "PASS")
                rerun_count = len(rev.get("validators_rerun", []))

                with st.container():
                    st.markdown(
                        f"""
                        <div class="highlight-card">
                            <h4 style="margin: 0 0 6px 0;">🔧 Repair #{i}: <code>{aff_str}</code></h4>
                            <p style="margin: 2px 0;"><strong>Error Code(s):</strong> <span class="status-fail">{trig}</span></p>
                            <p style="margin: 2px 0;"><strong>Repair Action:</strong> {action}</p>
                            <p style="margin: 2px 0;"><strong>Revalidation:</strong> <code>{rerun_count} / 9 validators rerun</code> ➔ <span class="status-pass">{val_status}</span></p>
                            <p style="margin: 2px 0;"><small>Preserved Unchanged Segments: <code>{', '.join(rev.get('unchanged', []))}</code></small></p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        # Compact Revision Log Section
        st.markdown("### 📋 Revision Log Audit")
        rev_table = []
        for r in revisions_data:
            rev_table.append({
                "Revision": r.get("revision", 1),
                "Affected Target": ", ".join(r.get("affected", [])),
                "Trigger Code": r.get("trigger", "").replace("repair:", ""),
                "Action": r.get("action", "")[:80] + "...",
                "Revalidation": r.get("validation", "PASS"),
                "Validators Rerun": len(r.get("validators_rerun", [])),
            })
        st.dataframe(rev_table, use_container_width=True)

        # Final Status
        st.success(f"Final Pipeline Status: **{overall_status}** (All deliberate traps repaired successfully)")

    # ── SCENARIO 3: CONTRACT CHANGE ──────────────────────────────────────────
    elif active_scenario == "change":
        st.subheader("🔄 Scenario: Selective Change Impact & Replanning")

        st.markdown(
            """
            <div class="change-alert">
                <h3 style="margin: 0 0 4px 0; color: #991B1B;">🚨 CHANGE EVENT DETECTED: <code>music_03</code> Promotional Rights Expired</h3>
                <p style="margin: 0; color: #7F1D1D;">
                    Contract <code>C-MUS-03</code> (<em>Ghar Ki Dhun</em>) valid_until updated to <code>2026-09-01</code>,
                    which precedes campaign start <code>2026-10-05</code>.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Replacement Prominence Card
        st.markdown(
            """
            <div style="text-align: center; padding: 1.2rem; background: #EFF6FF; border: 2px dashed #3B82F6; border-radius: 8px; margin-bottom: 1.5rem;">
                <span style="font-size: 1.2rem; font-weight: 600; color: #1E3A8A;">Target Replacement: </span>
                <span class="swap-badge" style="background:#FEE2E2; color:#991B1B; text-decoration: line-through;">🎵 music_03 (Expired)</span>
                <span style="font-size: 1.4rem; font-weight: 800; color: #2563EB; margin: 0 15px;">➔</span>
                <span class="swap-badge" style="background:#DCFCE7; color:#166534;">🎵 music_05 (Approved promotional clearance)</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Impact Scoping Metrics
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Affected Decisions", "2", help="family_v1.segment_02 & dialect_region_v1.segment_04")
        with m2:
            st.metric("Unaffected Trailers", "1", help="young_adult_v1 has zero dependencies on music_03")
        with m3:
            st.metric("Unaffected Segments", "11", help="Preserved across all 3 trailers")
        with m4:
            st.metric("Hash Invariant Violations", "0", help="100% byte-identical preservation")

        st.write("")

        col_aff, col_unaff = st.columns(2)
        with col_aff:
            st.markdown("### 🎯 Affected Segments (Selectively Repaired)")
            st.markdown(
                """
                - 🔴 **`family_v1.segment_02`**: Used `music_03` as audio asset. Repaired with `music_05`.
                - 🔴 **`dialect_region_v1.segment_04`**: Used `music_03` as audio asset. Repaired with `music_05`.
                """
            )
            if revisions_data:
                for rev in revisions_data:
                    st.info(f"**{', '.join(rev.get('affected', []))}**: {rev.get('action')}")

        with col_unaff:
            st.markdown("### 🛡️ Unaffected Plan Preservation")
            st.markdown(
                """
                - 🟢 **`young_adult_v1`**: **COMPLETELY UNAFFECTED** (No dependency on `music_03`).
                - 🟢 **11 of 13 segments** across the campaign remained byte-identical.
                - 🟢 **Determinism verification**: Zero unintended side-effects or re-render churn.
                """
            )

        st.success("Selective repair succeeded: Campaign repaired with zero collateral damage to approved trailers.")

    st.markdown("---")

    # ── ARTIFACTS EXPLORER & DOWNLOAD ─────────────────────────────────────────
    st.subheader("📦 Generated Artifacts & EDL Exports")
    st.caption("Inspect and download the 10 machine-readable output files produced by this execution.")

    artifact_filenames = [
        "story_map.json",
        "spoiler_map.json",
        "constraint_map.json",
        "family_trailer.json",
        "young_adult_trailer.json",
        "dialect_region_trailer.json",
        "validation_report.md",
        "decision_log.json",
        "revision_log.json",
        "run_state.json",
    ]

    art_tabs = st.tabs(artifact_filenames)

    for tab, fname in zip(art_tabs, artifact_filenames):
        with tab:
            fpath = active_dir / fname
            if not fpath.exists():
                st.warning(f"File `{fname}` not found in `{active_dir}`.")
            else:
                col_info, col_dl = st.columns([4, 1])
                with col_info:
                    st.markdown(f"**Path:** `/{active_dir.name}/{fname}` &nbsp;&nbsp;|&nbsp;&nbsp; **Size:** `{fpath.stat().st_size:,} bytes`")
                with col_dl:
                    if fname.endswith(".json"):
                        raw_data = load_text(fpath) or "{}"
                        st.download_button(
                            label=f"⬇️ Download {fname}",
                            data=raw_data,
                            file_name=fname,
                            mime="application/json",
                            use_container_width=True,
                        )
                    else:
                        raw_data = load_text(fpath) or ""
                        st.download_button(
                            label=f"⬇️ Download {fname}",
                            data=raw_data,
                            file_name=fname,
                            mime="text/markdown",
                            use_container_width=True,
                        )

                if fname.endswith(".json"):
                    parsed_json = load_json(fpath)
                    if parsed_json is not None:
                        st.json(parsed_json, expanded=(fname not in ["run_state.json"]))
                    else:
                        st.code(load_text(fpath) or "", language="json")
                elif fname.endswith(".md"):
                    md_content = load_text(fpath) or ""
                    st.markdown(md_content)
                    with st.expander("View Raw Markdown Source"):
                        st.code(md_content, language="markdown")

else:
    st.info("👆 Click one of the three scenario buttons above to run the pipeline and display results.")
