# -*- coding: utf-8 -*-
"""
Triage Rules Engine
====================
Shared validation and scoring logic used by both the web app (app.py)
and the robot (game_engine.py / ros2_node.py).

Imports design_patients for patient data and core rule derivations.
Neither Flask nor ROS 2 are imported here — this is pure Python.
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from design_patients import (
    PATIENTS_A, PATIENTS_B,
    derive_risk, derive_processes, derive_destination, sort_key
)

# ─── PATIENT DATABASE ─────────────────────────────────────────────────────────
def _build_db():
    pid_to_patient = {}
    groups = {"A": {}, "B": {}}
    for set_label, patients in [("A", PATIENTS_A), ("B", PATIENTS_B)]:
        by_group = {}
        for p in patients:
            pid_to_patient[(set_label, p["pid"])] = p
            by_group.setdefault(p["group"], []).append(p)
        for grp, pts in by_group.items():
            groups[set_label][grp] = [p["pid"] for p in sorted(pts, key=sort_key)]
    return pid_to_patient, groups

PID_TO_PATIENT, CORRECT_ORDERS = _build_db()

# ─── CORRECT ANSWER HELPERS ───────────────────────────────────────────────────
def correct_order(set_label: str, group: int) -> list:
    """Return list of PIDs in correct selection order for a group."""
    return CORRECT_ORDERS[set_label][group]

def correct_processes_for(set_label: str, pid: str) -> list:
    """Return correct list of process names for a patient."""
    p = PID_TO_PATIENT[(set_label, pid)]
    r = derive_risk(p)
    return derive_processes(p, r)

def correct_destination_for(set_label: str, pid: str) -> str:
    """Return correct destination string for a patient."""
    p = PID_TO_PATIENT[(set_label, pid)]
    r = derive_risk(p)
    return derive_destination(p, r)

def get_group_patients(set_label: str, group: int) -> list:
    """Return ordered list of patient dicts for a group."""
    pids = CORRECT_ORDERS[set_label][group]
    return [PID_TO_PATIENT[(set_label, pid)] for pid in pids]

def patient_risk(set_label: str, pid: str) -> str:
    """Return risk level string for a patient."""
    return derive_risk(PID_TO_PATIENT[(set_label, pid)])

# ─── SCORING ──────────────────────────────────────────────────────────────────
def kendall_tau(placed_order: list, correct_order_: list) -> float:
    """
    Kendall's Tau for a ranked list. Returns value in [0, 1].
    1.0 = perfect order, 0.0 = fully reversed.
    placed_order:   list of PIDs in participant's order (slot 1 → slot 5)
    correct_order_: list of PIDs in correct order
    """
    n = len(correct_order_)
    if n <= 1:
        return 1.0
    correct_rank = {pid: i for i, pid in enumerate(correct_order_)}
    placed_rank  = {}
    for slot, pid in enumerate(placed_order):
        if pid and pid in correct_rank:
            placed_rank[pid] = slot

    pids = [p for p in correct_order_ if p in placed_rank]
    if len(pids) < 2:
        return 0.0

    concordant = discordant = 0
    for i in range(len(pids)):
        for j in range(i + 1, len(pids)):
            c_diff = correct_rank[pids[i]] - correct_rank[pids[j]]
            p_diff = placed_rank[pids[i]]  - placed_rank[pids[j]]
            if c_diff * p_diff > 0:
                concordant += 1
            elif c_diff * p_diff < 0:
                discordant += 1

    total_pairs = len(pids) * (len(pids) - 1) / 2
    tau = (concordant - discordant) / total_pairs
    return round((tau + 1) / 2, 4)

def phase_based_score(set_label: str, group: int, placed: dict) -> dict:
    """
    Hierarchical scoring (max 9 points):
      2 pts — all Critical patients before all Moderate
      2 pts — all Moderate patients before all Stable
      1 pt  — each patient in correct position within their risk tier (up to 5)

    placed: {str(slot): pid}  e.g. {"1": "P01", "2": "P03", ...}
    Returns dict with full breakdown.
    """
    correct = CORRECT_ORDERS[set_label][group]
    pid_to_risk = {pid: derive_risk(PID_TO_PATIENT[(set_label, pid)])
                   for pid in correct}

    placed_list = [placed.get(str(i + 1)) for i in range(5)]

    crit_pos = [i for i, pid in enumerate(placed_list) if pid and pid_to_risk.get(pid) == "Critical"]
    mod_pos  = [i for i, pid in enumerate(placed_list) if pid and pid_to_risk.get(pid) == "Moderate"]
    stab_pos = [i for i, pid in enumerate(placed_list) if pid and pid_to_risk.get(pid) == "Stable"]

    crit_before_mod  = (not crit_pos or not mod_pos  or max(crit_pos) < min(mod_pos))
    mod_before_stab  = (not mod_pos  or not stab_pos or max(mod_pos)  < min(stab_pos))

    correct_within = 0
    for risk_level in ("Critical", "Moderate", "Stable"):
        correct_tier = [p for p in correct      if pid_to_risk.get(p) == risk_level]
        placed_tier  = [p for p in placed_list  if p and pid_to_risk.get(p) == risk_level]
        for i, pid in enumerate(correct_tier):
            if i < len(placed_tier) and placed_tier[i] == pid:
                correct_within += 1

    tier_score   = (2 if crit_before_mod else 0) + (2 if mod_before_stab else 0)
    total        = tier_score + correct_within
    return {
        "tier_ordering_score": tier_score,
        "tier_ordering_max":   4,
        "within_tier_score":   correct_within,
        "within_tier_max":     5,
        "total":               total,
        "max":                 9,
        "crit_before_mod":     crit_before_mod,
        "mod_before_stab":     mod_before_stab,
    }

# ─── VALIDATION ───────────────────────────────────────────────────────────────
def validate_selection(set_label: str, group: int, placed: dict):
    """
    Validate participant's selection order.
    placed: {str(slot): pid}  e.g. {"1": "P02", "2": "P01", ...}
    Returns: (score, errors, correct_order, kendall_tau, phase_based_score)
    """
    correct = CORRECT_ORDERS[set_label][group]
    errors  = []
    score   = 0
    for i, exp_pid in enumerate(correct):
        slot       = str(i + 1)
        placed_pid = placed.get(slot)
        if placed_pid == exp_pid:
            score += 1
        else:
            p = PID_TO_PATIENT[(set_label, exp_pid)]
            errors.append({
                "slot":          i + 1,
                "placed":        placed_pid,
                "expected":      exp_pid,
                "expected_name": p["name"],
                "explanation":   p.get("explanation_en", ""),
            })
    placed_list = [placed.get(str(i + 1)) for i in range(5)]
    tau   = kendall_tau(placed_list, correct)
    phase = phase_based_score(set_label, group, placed)
    return score, errors, correct, tau, phase

def validate_processes(set_label: str, group: int, placed: dict):
    """
    Validate process card assignments.
    placed: {pid: [process_name, ...]}
    Returns: (score, errors)
    """
    pids   = CORRECT_ORDERS[set_label][group]
    errors = []
    score  = 0
    for pid in pids:
        expected = sorted(correct_processes_for(set_label, pid))
        actual   = sorted(placed.get(pid, []))
        if actual == expected:
            score += 1
        else:
            p = PID_TO_PATIENT[(set_label, pid)]
            errors.append({
                "pid":         pid,
                "name":        p["name"],
                "expected":    expected,
                "placed":      actual,
                "missing":     [x for x in expected if x not in actual],
                "extra":       [x for x in actual   if x not in expected],
                "explanation": p.get("explanation_en", ""),
            })
    return score, errors

def validate_destinations(set_label: str, group: int, placed: dict):
    """
    Validate destination assignments.
    placed: {pid: destination_string}
    Returns: (score, errors)
    """
    pids   = CORRECT_ORDERS[set_label][group]
    errors = []
    score  = 0
    for pid in pids:
        expected = correct_destination_for(set_label, pid)
        actual   = placed.get(pid, "")
        if actual == expected:
            score += 1
        else:
            p = PID_TO_PATIENT[(set_label, pid)]
            errors.append({
                "pid":         pid,
                "name":        p["name"],
                "expected":    expected,
                "placed":      actual,
                "explanation": p.get("explanation_en", ""),
            })
    return score, errors

# ─── PATIENT SERIALISATION ────────────────────────────────────────────────────
def patient_for_client(p: dict, set_label: str, include_answers: bool = False) -> dict:
    """
    Serialise a patient dict for the web frontend.
    Optionally includes correct answers (used in admin view).
    """
    r = derive_risk(p)
    d = {
        "pid":           p["pid"],
        "name":          p["name"],
        "condition":     p["condition"],
        "hr":            p["hr"],
        "bp":            p["bp"],
        "spo2":          p["spo2"],
        "rr":            p["rr"],
        "temp":          p["temp"],
        "alertness":     p["alertness"],
        "onset":         p["onset"],
        "mobility":      p["mobility"],
        "companion":     p["companion"],
        "cooperation":   p["cooperation"],
        "risk":          r,
        "explanation_en": p.get("explanation_en", ""),
        "explanation_es": p.get("explanation_es", ""),
        "exp_selection_en":  p.get("exp_selection_en",  p.get("explanation_en", "")),
        "exp_selection_es":  p.get("exp_selection_es",  p.get("explanation_es", "")),
        "exp_processes_en":  p.get("exp_processes_en",  p.get("explanation_en", "")),
        "exp_processes_es":  p.get("exp_processes_es",  p.get("explanation_es", "")),
        "exp_destination_en": p.get("exp_destination_en", p.get("explanation_en", "")),
        "exp_destination_es": p.get("exp_destination_es", p.get("explanation_es", "")),
    }
    if include_answers:
        d["correct_processes"]  = correct_processes_for(set_label, p["pid"])
        d["correct_destination"] = correct_destination_for(set_label, p["pid"])
    return d
