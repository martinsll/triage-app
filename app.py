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
from rules_engine import (
    PID_TO_PATIENT, CORRECT_ORDERS,
    get_group_patients, patient_for_client,
    validate_selection, validate_processes, validate_destinations,
    correct_processes_for, correct_destination_for,
    kendall_tau, phase_based_score,
)

app = Flask(__name__)
app.secret_key = "triage-training-2024"

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


# ─── ROBOT QUESTIONNAIRE ROUTES ───────────────────────────────────────────────
@app.route("/robot")
def robot_index():
    n = get_next_participant_number()
    pid = f"R{n:03d}"
    return render_template("robot_setup.html", participant_id=pid)

@app.route("/api/start_robot", methods=["POST"])
def api_start_robot():
    data           = request.json
    participant_id = data.get("participant_id", "").strip() or "anonymous"
    language       = data.get("language", "en")

    sess = {
        "session_id":     f"{participant_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "participant_id": participant_id,
        "condition":      "robot",
        "language":       language,
        "created_at":     datetime.now().isoformat(),
        "completed_at":   None,
        "iterations":     {},
    }
    save_session(sess)

    session["session_id"]       = sess["session_id"]
    session["language"]         = language
    session["condition"]         = "robot"
    session["after_demographics"] = "/robot_ues"
    session["after_ues"]          = "/robot_nasa_tlx"
    session["after_nasa_tlx"]     = "/robot_questionnaire"

    return jsonify({"ok": True, "redirect": "/robot_demographics"})

@app.route("/robot_demographics")
def robot_demographics():
    if "session_id" not in session:
        return redirect(url_for("robot_index"))
    return render_template("demographics.html",
        language=session.get("language","en"),
        condition="robot")

@app.route("/robot_ues")
def robot_ues():
    if "session_id" not in session:
        return redirect(url_for("robot_index"))
    return render_template("ues_questionnaire.html",
        language=session.get("language","en"))

@app.route("/robot_nasa_tlx")
def robot_nasa_tlx():
    if "session_id" not in session:
        return redirect(url_for("robot_index"))
    return render_template("nasa_tlx.html",
        language=session.get("language","en"))

@app.route("/robot_questionnaire")
def robot_questionnaire():
    if "session_id" not in session:
        return redirect(url_for("robot_index"))
    return render_template("robot_questionnaire.html",
        language=session.get("language","en"))

@app.route("/robot_results")
def robot_results():
    if "session_id" not in session:
        return redirect(url_for("robot_index"))
    return render_template("robot_results.html",
        language=session.get("language","en"))

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
