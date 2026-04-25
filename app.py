# -*- coding: utf-8 -*-
"""
Triage Training Game — Flask App
==================================
Autonomous practice mode (no robot, no LLM).

Run:
    pip install flask
    python app.py

Then open: http://localhost:5000
"""

import os, json, sqlite3
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from design_patients import (
    PATIENTS_A, PATIENTS_B,
    derive_risk, derive_processes, derive_destination, sort_key
)

app = Flask(__name__)
app.secret_key = "triage-training-2024"
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_HTTPONLY=True,
)

import sqlite3

# ─── DATABASE SETUP ───────────────────────────────────────────────────────────
# Use a persistent directory — on Railway mount this path as a volume
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "sessions.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                data       TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS counters (
                name  TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO counters (name, value) VALUES ('participant_id', 0)
        """)
        conn.commit()

init_db()

# ─── SESSION LOGGING ──────────────────────────────────────────────────────────
def load_session(session_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT data FROM sessions WHERE session_id = ?",
            (session_id,)
        ).fetchone()
    return json.loads(row["data"]) if row else None

def save_session(data):
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO sessions (session_id, data, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                data = excluded.data,
                updated_at = excluded.updated_at
        """, (data["session_id"], json.dumps(data), now, now))
        conn.commit()

def load_all_sessions():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT data FROM sessions ORDER BY created_at DESC"
        ).fetchall()
    return [json.loads(r["data"]) for r in rows]

def get_next_participant_number():
    """Return the next participant number based on session count."""
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) as n FROM sessions").fetchone()
    return row["n"] + 1

def init_session_data(participant_id, set_label, groups, language):
    sid = f"{participant_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return {
        "session_id": sid,
        "participant_id": participant_id,
        "set": set_label,
        "groups": groups,
        "language": language,
        "created_at": datetime.now().isoformat(),
        "completed_at": None,
        "iterations": {}
    }


def build_db():
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

PID_TO_PATIENT, CORRECT_ORDERS = build_db()

def correct_processes(set_label, pid):
    p = PID_TO_PATIENT[(set_label, pid)]
    r = derive_risk(p)
    return derive_processes(p, r)

def correct_destination(set_label, pid):
    p = PID_TO_PATIENT[(set_label, pid)]
    r = derive_risk(p)
    return derive_destination(p, r)

def get_group_patients(set_label, group):
    """Return ordered patient dicts for a group."""
    pids = CORRECT_ORDERS[set_label][group]
    return [PID_TO_PATIENT[(set_label, pid)] for pid in pids]

def patient_for_client(p, set_label, include_answers=False):
    """Serialize patient for frontend (optionally with correct answers)."""
    r = derive_risk(p)
    d = {
        "pid": p["pid"],
        "name": p["name"],
        "condition": p["condition"],
        "hr": p["hr"], "bp": p["bp"], "spo2": p["spo2"],
        "rr": p["rr"], "temp": p["temp"],
        "alertness": p["alertness"],
        "onset": p["onset"],
        "mobility": p["mobility"],
        "companion": p["companion"],
        "cooperation": p["cooperation"],
        "risk": r,
        "explanation_en": p.get("explanation_en", ""),
        "explanation_es": p.get("explanation_es", ""),
    }
    if include_answers:
        d["correct_processes"] = correct_processes(set_label, p["pid"])
        d["correct_destination"] = correct_destination(set_label, p["pid"])
    return d

# ─── PATIENT DATABASE ─────────────────────────────────────────────────────────
def ensure_iteration(sess, group):
    key = str(group)
    if key not in sess["iterations"]:
        sess["iterations"][key] = {
            "group": group,
            "selection":    {"attempts": [], "final_score": None, "questions_asked": 0},
            "processes":    {"attempts": [], "final_score": None},
            "destinations": {"attempts": [], "final_score": None},
            "completed": False
        }
    return sess["iterations"][key]

# ─── VALIDATION LOGIC ─────────────────────────────────────────────────────────
def kendall_tau(placed_order, correct_order):
    """
    Kendall's Tau for a ranked list.
    Returns value in [0,1] where 1 = perfect order.
    placed_order: list of pids in participant's order (slot 1 → slot 5)
    correct_order: list of pids in correct order
    """
    n = len(correct_order)
    if n <= 1:
        return 1.0
    # Build rank lookup for correct order
    correct_rank = {pid: i for i, pid in enumerate(correct_order)}
    # Build participant rank from placed_order (only include pids in correct_order)
    placed_rank = {}
    for slot, pid in enumerate(placed_order):
        if pid and pid in correct_rank:
            placed_rank[pid] = slot

    pids = [p for p in correct_order if p in placed_rank]
    if len(pids) < 2:
        return 0.0

    concordant = discordant = 0
    for i in range(len(pids)):
        for j in range(i + 1, len(pids)):
            c_diff = correct_rank[pids[i]] - correct_rank[pids[j]]
            p_diff = placed_rank[pids[i]] - placed_rank[pids[j]]
            if c_diff * p_diff > 0:
                concordant += 1
            elif c_diff * p_diff < 0:
                discordant += 1

    total_pairs = len(pids) * (len(pids) - 1) / 2
    tau = (concordant - discordant) / total_pairs
    # Normalise to [0,1]
    return round((tau + 1) / 2, 4)

def phase_based_score(set_label, group, placed):
    """
    Hierarchical scoring:
    - 2pts: all Critical patients come before all Moderate (regardless of order within)
    - 2pts: all Moderate patients come before all Stable
    - 1pt per patient in correct position within their risk tier (up to 5)
    Returns dict with breakdown.
    """
    from design_patients import derive_risk, PATIENTS_A, PATIENTS_B
    patients = PATIENTS_A if set_label == "A" else PATIENTS_B
    pid_to_risk = {}
    for p in patients:
        pid_to_risk[p["pid"]] = derive_risk(p)

    correct = CORRECT_ORDERS[set_label][group]
    # Build placed list (slot 1..5)
    placed_list = [placed.get(str(i+1)) for i in range(5)]

    # Group ordering check
    crit_positions = [i for i, pid in enumerate(placed_list) if pid and pid_to_risk.get(pid)=="Critical"]
    mod_positions  = [i for i, pid in enumerate(placed_list) if pid and pid_to_risk.get(pid)=="Moderate"]
    stab_positions = [i for i, pid in enumerate(placed_list) if pid and pid_to_risk.get(pid)=="Stable"]

    # Crits before Mods
    crit_before_mod = (not crit_positions or not mod_positions or
                       max(crit_positions) < min(mod_positions))
    # Mods before Stables
    mod_before_stab = (not mod_positions or not stab_positions or
                       max(mod_positions) < min(stab_positions))

    # Within-tier ordering
    correct_within = 0
    correct_risks = [pid_to_risk.get(p,"") for p in correct]
    for risk_level in ("Critical", "Moderate", "Stable"):
        correct_tier = [p for p in correct if pid_to_risk.get(p)==risk_level]
        placed_tier  = [p for p in placed_list if p and pid_to_risk.get(p)==risk_level]
        for i, pid in enumerate(correct_tier):
            if i < len(placed_tier) and placed_tier[i] == pid:
                correct_within += 1

    tier_score     = (2 if crit_before_mod else 0) + (2 if mod_before_stab else 0)
    within_score   = correct_within
    total          = tier_score + within_score

    return {
        "tier_ordering_score": tier_score,
        "tier_ordering_max":   4,
        "within_tier_score":   within_score,
        "within_tier_max":     5,
        "total":               total,
        "max":                 9,
        "crit_before_mod":     crit_before_mod,
        "mod_before_stab":     mod_before_stab,
    }


def validate_selection(set_label, group, placed):
    correct = CORRECT_ORDERS[set_label][group]
    errors = []
    score = 0
    for i, exp_pid in enumerate(correct):
        slot = str(i + 1)
        placed_pid = placed.get(slot)
        if placed_pid == exp_pid:
            score += 1
        else:
            errors.append({
                "slot": i + 1,
                "placed": placed_pid,
                "expected": exp_pid,
                "expected_name": PID_TO_PATIENT[(set_label, exp_pid)]["name"],
                "explanation": PID_TO_PATIENT[(set_label, exp_pid)].get("explanation_en", "")
            })
    placed_list = [placed.get(str(i+1)) for i in range(5)]
    tau   = kendall_tau(placed_list, correct)
    phase = phase_based_score(set_label, group, placed)
    return score, errors, correct, tau, phase

def validate_processes(set_label, group, placed):
    """
    placed: {pid: [process_names]}
    Returns: score, errors
    """
    pids = CORRECT_ORDERS[set_label][group]
    errors = []
    score = 0
    for pid in pids:
        expected = sorted(correct_processes(set_label, pid))
        actual   = sorted(placed.get(pid, []))
        if actual == expected:
            score += 1
        else:
            missing = [p for p in expected if p not in actual]
            extra   = [p for p in actual   if p not in expected]
            errors.append({
                "pid": pid,
                "name": PID_TO_PATIENT[(set_label, pid)]["name"],
                "expected": expected,
                "placed": actual,
                "missing": missing,
                "extra": extra,
                "explanation": PID_TO_PATIENT[(set_label, pid)].get(
                    "explanation_en", "")
            })
    return score, errors

def validate_destinations(set_label, group, placed):
    """
    placed: {pid: destination_string}
    Returns: score, errors
    """
    pids = CORRECT_ORDERS[set_label][group]
    errors = []
    score = 0
    for pid in pids:
        expected = correct_destination(set_label, pid)
        actual   = placed.get(pid, "")
        if actual == expected:
            score += 1
        else:
            errors.append({
                "pid": pid,
                "name": PID_TO_PATIENT[(set_label, pid)]["name"],
                "expected": expected,
                "placed": actual,
                "explanation": PID_TO_PATIENT[(set_label, pid)].get(
                    "explanation_en", "")
            })
    return score, errors

# ─── ROUTES ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    n = get_next_participant_number()
    pid = f"P{n:03d}"
    return render_template("setup.html", participant_id=pid)

@app.route("/api/next_participant_id")
def api_next_participant_id():
    """Return the next available participant number."""
    n = get_next_participant_number()
    return jsonify({"number": n, "id": f"P{n:03d}"})


@app.route("/api/start", methods=["POST"])
def api_start():
    data           = request.json
    participant_id = data.get("participant_id", "").strip() or "anonymous"
    language       = data.get("language", "en")

    # Fixed experiment flow: Train = Set A groups 1-3, Test = Set B groups 1-3
    sess = init_session_data(participant_id, "A", [1,2,3], language)
    sess["phase"] = "train"      # train | test
    sess["test_started_at"] = None
    sess["game_started_at"] = None
    save_session(sess)

    session["session_id"]        = sess["session_id"]
    session["set"]               = "A"
    session["groups"]            = [1, 2, 3]
    session["language"]          = language
    session["current_group_idx"] = 0
    session["phase"]             = "train"

    return jsonify({"session_id": sess["session_id"], "ok": True,
                    "redirect": "/onboarding"})

@app.route("/api/start_test", methods=["POST"])
def api_start_test():
    """Transition from Train to Test phase."""
    sid = session.get("session_id")
    sess = load_session(sid)
    if not sess:
        return jsonify({"ok": False}), 400

    sess["phase"] = "test"
    sess["test_started_at"] = datetime.now().isoformat()
    save_session(sess)

    session["set"]               = "B"
    session["groups"]            = [1, 2, 3]
    session["current_group_idx"] = 0
    session["phase"]             = "test"

    return jsonify({"ok": True})

@app.route("/transition")
def transition():
    """Interstitial screen between Train and Test phases."""
    if "session_id" not in session:
        return redirect(url_for("index"))
    return render_template("transition.html", language=session.get("language","en"))

@app.route("/questionnaire")
def questionnaire():
    if "session_id" not in session:
        return redirect(url_for("index"))
    return render_template("questionnaire.html", language=session.get("language","en"))

@app.route("/api/submit_questionnaire", methods=["POST"])
def api_submit_questionnaire():
    data = request.json
    sid  = session.get("session_id")
    sess = load_session(sid)
    if not sess:
        return jsonify({"ok": False}), 400
    sess["questionnaire"] = {
        "answers":      data.get("answers", {}),
        "submitted_at": datetime.now().isoformat(),
    }
    save_session(sess)
    return jsonify({"ok": True})

@app.route("/onboarding")
def onboarding():
    if "session_id" not in session:
        return redirect(url_for("index"))
    return render_template("onboarding.html", language=session.get("language","en"))

@app.route("/api/record_reading", methods=["POST"])
def api_record_reading():
    """Save time spent on instructions and rules pages."""
    data = request.json
    sid  = session.get("session_id")
    if not sid:
        return jsonify({"ok": False}), 400

    sess = load_session(sid)
    if not sess:
        return jsonify({"ok": False}), 404

    sess["onboarding"] = {
        "instructions_time_sec": data.get("instructions_time_sec"),
        "rules_time_sec":        data.get("rules_time_sec"),
        "total_time_sec":        (data.get("instructions_time_sec", 0) +
                                  data.get("rules_time_sec", 0)),
        "completed_at":          datetime.now().isoformat(),
    }
    save_session(sess)
    return jsonify({"ok": True})

@app.route("/game")
def game():
    if "session_id" not in session:
        return redirect(url_for("index"))
    return render_template("game.html", language=session.get("language","en"))

@app.route("/api/group_patients")
def api_group_patients():
    """Return patient data for the current group."""
    if "session_id" not in session:
        return jsonify({"error": "no session", "done": False}), 401

    set_label = session.get("set", "A")
    groups    = session.get("groups", [1, 2, 3])
    idx       = session.get("current_group_idx", 0)

    if idx >= len(groups):
        return jsonify({"done": True})

    group = groups[idx]
    patients = get_group_patients(set_label, group)

    return jsonify({
        "done": False,
        "set": set_label,
        "group": group,
        "group_index": idx,
        "total_groups": len(groups),
        "language": session.get("language", "en"),
        "phase": session.get("phase", "train"),
        "patients": [patient_for_client(p, set_label) for p in patients],
        "correct_order": CORRECT_ORDERS[set_label][group],
    })

@app.route("/api/validate", methods=["POST"])
def api_validate():
    data      = request.json
    phase     = data["phase"]        # selection | processes | destinations
    answers      = data["answers"]
    group        = data["group"]
    phase_time   = data.get("phase_time_sec", None)
    rule_metrics = data.get("rule_metrics", {})

    set_label = session.get("set", "A")
    sid       = session.get("session_id")
    if not sid:
        return jsonify({"error": "no session"}), 400

    sess = load_session(sid)
    if not sess:
        return jsonify({"error": "session not found"}), 404

    it = ensure_iteration(sess, group)
    timestamp = datetime.now().isoformat()

    if phase == "selection":
        score, errors, correct, tau, phase_score = validate_selection(set_label, group, answers)
        attempt_num = len(it["selection"]["attempts"]) + 1
        it["selection"]["attempts"].append({
            "attempt":          attempt_num,
            "placed":           answers,
            "score":            f"{score}/5",
            "kendall_tau":      tau,
            "phase_score":      phase_score,
            "phase_time_sec":   phase_time,
            "rule_metrics":     rule_metrics,
            "errors":           errors,
            "timestamp":        timestamp,
        })
        if score == 5:
            it["selection"]["final_score"] = "5/5"
        result = {
            "score": score, "max": 5,
            "kendall_tau": tau,
            "phase_score": phase_score,
            "errors": errors,
            "correct_order": correct,
            "attempt": attempt_num,
            "perfect": score == 5,
        }

    elif phase == "processes":
        score, errors = validate_processes(set_label, group, answers)
        attempt_num = len(it["processes"]["attempts"]) + 1
        it["processes"]["attempts"].append({
            "attempt":        attempt_num,
            "placed":         answers,
            "score":          f"{score}/5",
            "phase_time_sec": phase_time,
            "rule_metrics":   rule_metrics,
            "errors":         errors,
            "timestamp":      timestamp,
        })
        if score == 5:
            it["processes"]["final_score"] = "5/5"

        pids = CORRECT_ORDERS[set_label][group]
        correct_all = {pid: correct_processes(set_label, pid) for pid in pids}
        result = {
            "score": score, "max": 5,
            "errors": errors,
            "correct_all": correct_all,
            "attempt": attempt_num,
            "perfect": score == 5,
        }

    elif phase == "destinations":
        score, errors = validate_destinations(set_label, group, answers)
        attempt_num = len(it["destinations"]["attempts"]) + 1
        it["destinations"]["attempts"].append({
            "attempt":        attempt_num,
            "placed":         answers,
            "score":          f"{score}/5",
            "phase_time_sec": phase_time,
            "rule_metrics":   rule_metrics,
            "errors":         errors,
            "timestamp":      timestamp,
        })
        if score == 5:
            it["destinations"]["final_score"] = "5/5"

        pids = CORRECT_ORDERS[set_label][group]
        correct_all = {pid: correct_destination(set_label, pid) for pid in pids}
        result = {
            "score": score, "max": 5,
            "errors": errors,
            "correct_all": correct_all,
            "attempt": attempt_num,
            "perfect": score == 5
        }

    else:
        return jsonify({"error": "unknown phase"}), 400

    save_session(sess)
    return jsonify(result)

@app.route("/api/complete_group", methods=["POST"])
def api_complete_group():
    """Mark current group complete and advance."""
    sid   = session.get("session_id")
    group = request.json.get("group")

    sess = load_session(sid)
    if sess:
        it = ensure_iteration(sess, group)
        it["completed"] = True
        it["completed_at"] = datetime.now().isoformat()
        save_session(sess)

    idx    = session.get("current_group_idx", 0)
    groups = session.get("groups", [1, 2, 3])
    phase  = session.get("phase", "train")
    session["current_group_idx"] = idx + 1

    if idx + 1 >= len(groups):
        if sess:
            if phase == "train":
                # Train done → go to transition screen
                sess["train_completed_at"] = datetime.now().isoformat()
                save_session(sess)
                return jsonify({"done": True, "next": "transition"})
            else:
                # Test done → go to results
                sess["completed_at"] = datetime.now().isoformat()
                save_session(sess)
                return jsonify({"done": True, "next": "results"})
    return jsonify({"done": False, "next_group": groups[idx + 1]})

@app.route("/api/record_game_start", methods=["POST"])
def api_record_game_start():
    """Record when participant starts playing (after onboarding)."""
    sid = session.get("session_id")
    sess = load_session(sid)
    if sess:
        phase = session.get("phase", "train")
        if phase == "train" and not sess.get("game_started_at"):
            sess["game_started_at"] = datetime.now().isoformat()
        elif phase == "test":
            sess["test_started_at"] = datetime.now().isoformat()
        save_session(sess)
    return jsonify({"ok": True})

@app.route("/results")
def results():
    sid = session.get("session_id")
    sess = load_session(sid) if sid else None
    if not sess:
        return redirect(url_for("index"))
    return render_template("results.html", sess=sess, language=session.get("language","en"))

@app.route("/admin")
def admin():
    sessions = load_all_sessions()
    return render_template("admin.html", sessions=sessions)

@app.route("/api/sessions")
def api_sessions():
    return jsonify(load_all_sessions())

if __name__ == "__main__":
    print("Triage Training App")
    print("Open: http://localhost:5000")
    app.run(debug=True, port=5000)
