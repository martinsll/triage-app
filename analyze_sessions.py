# -*- coding: utf-8 -*-
"""
Triage Session Data Extractor
================================
Reads sessions.db and produces flat CSV files ready for analysis in pandas/R/SPSS.

Output files:
  sessions_summary.csv    — one row per participant
  attempts.csv            — one row per attempt per phase per group per participant
  questionnaire.csv       — one row per participant with all questionnaire answers
  ues.csv                 — one row per participant with all UES answers

Usage:
  python analyze_sessions.py                          # uses data/sessions.db
  python analyze_sessions.py --db /path/to/sessions.db --out ./results/
"""

import sqlite3
import json
import csv
import os
import argparse
from datetime import datetime


def load_sessions(path):
    """Load sessions from either a SQLite .db file or a JSON file from /api/sessions."""
    if path.endswith('.json'):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # /api/sessions returns a list of session dicts directly
        if isinstance(data, list):
            return data
        # fallback if wrapped in a key
        return data.get('sessions', data)
    else:
        conn = sqlite3.connect(path)
        rows = conn.execute("SELECT data FROM sessions ORDER BY created_at").fetchall()
        conn.close()
        return [json.loads(r[0]) for r in rows]


def safe_int(val):
    """Parse '3/5' → 3, or return val if already numeric."""
    if isinstance(val, str) and '/' in val:
        return int(val.split('/')[0])
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def duration_seconds(start_iso, end_iso):
    """Seconds between two ISO timestamps."""
    if not start_iso or not end_iso:
        return None
    try:
        fmt = "%Y-%m-%dT%H:%M:%S.%f"
        t1 = datetime.fromisoformat(start_iso)
        t2 = datetime.fromisoformat(end_iso)
        return round((t2 - t1).total_seconds())
    except Exception:
        return None


# ─── SESSIONS SUMMARY ─────────────────────────────────────────────────────────
def build_sessions_summary(sessions):
    """One row per participant — overall scores and timing."""
    rows = []
    for s in sessions:
        pid   = s.get('participant_id', '')
        lang  = s.get('language', '')
        pset  = s.get('set', '')
        iters = s.get('iterations', {})

        # Timing
        train_duration = duration_seconds(
            s.get('game_started_at'), s.get('train_completed_at'))
        test_duration  = duration_seconds(
            s.get('test_started_at'), s.get('completed_at'))
        onb = s.get('onboarding', {})

        # Aggregate scores across all groups
        totals = {'selection': 0, 'processes': 0, 'destinations': 0}
        attempts_counts = {'selection': 0, 'processes': 0, 'destinations': 0}
        rule_consultations = 0
        rule_time_ms = 0

        for grp_key, it in iters.items():
            for phase in ('selection', 'processes', 'destinations'):
                ph = it.get(phase, {})
                att = ph.get('attempts', [])
                if att:
                    last = att[-1]
                    totals[phase] += safe_int(last.get('score', 0)) or 0
                    attempts_counts[phase] += len(att)
                    rc = last.get('rule_metrics', {})
                    rule_consultations += rc.get('total_consultations', 0) if isinstance(rc, dict) else 0
                    rule_time_ms += rc.get('total_time_ms', 0) if isinstance(rc, dict) else 0

        row = {
            'participant_id':          pid,
            'language':                lang,
            'set':                     pset,
            'created_at':              s.get('created_at', ''),
            'completed_at':            s.get('completed_at', ''),
            'train_duration_sec':      train_duration,
            'test_duration_sec':       test_duration,
            'instructions_time_sec':   onb.get('instructions_time_sec'),
            'rules_time_sec':          onb.get('rules_time_sec'),
            'n_groups':                len(iters),
            # Selection
            'sel_score_total':         totals['selection'],
            'sel_max':                 len(iters) * 5,
            'sel_attempts_total':      attempts_counts['selection'],
            # Processes
            'proc_score_total':        totals['processes'],
            'proc_max':                len(iters) * 5,
            'proc_attempts_total':     attempts_counts['processes'],
            # Destinations
            'dest_score_total':        totals['destinations'],
            'dest_max':                len(iters) * 5,
            'dest_attempts_total':     attempts_counts['destinations'],
            # Overall
            'total_score':             sum(totals.values()),
            'total_max':               len(iters) * 15,
            'rule_consultations_test': rule_consultations,
            'rule_time_sec_test':      round(rule_time_ms / 1000, 1),
        }
        rows.append(row)
    return rows


# ─── ATTEMPTS ─────────────────────────────────────────────────────────────────
def build_attempts(sessions):
    """One row per attempt per phase per group per participant."""
    rows = []
    for s in sessions:
        pid   = s.get('participant_id', '')
        lang  = s.get('language', '')
        pset  = s.get('set', '')
        iters = s.get('iterations', {})

        for grp_key, it in iters.items():
            group = it.get('group', int(grp_key))
            for phase in ('selection', 'processes', 'destinations'):
                ph = it.get(phase, {})
                for att in ph.get('attempts', []):
                    rc = att.get('rule_metrics', {})
                    phase_sc = att.get('phase_score', {})
                    row = {
                        'participant_id':       pid,
                        'language':             lang,
                        'set':                  pset,
                        'group':                group,
                        'phase':                phase,
                        'attempt':              att.get('attempt'),
                        'score':                safe_int(att.get('score', 0)),
                        'score_max':            5,
                        'score_pct':            round((safe_int(att.get('score', 0)) or 0) / 5 * 100),
                        'kendall_tau':          att.get('kendall_tau'),
                        'phase_score_total':    phase_sc.get('total') if isinstance(phase_sc, dict) else None,
                        'phase_score_max':      phase_sc.get('max') if isinstance(phase_sc, dict) else None,
                        'tier_ordering_score':  phase_sc.get('tier_ordering_score') if isinstance(phase_sc, dict) else None,
                        'within_tier_score':    phase_sc.get('within_tier_score') if isinstance(phase_sc, dict) else None,
                        'phase_time_sec':       att.get('phase_time_sec'),
                        'rule_consultations':   rc.get('total_consultations', 0) if isinstance(rc, dict) else 0,
                        'rule_time_ms':         rc.get('total_time_ms', 0) if isinstance(rc, dict) else 0,
                        'timestamp':            att.get('timestamp', ''),
                        'n_errors':             len(att.get('errors', [])),
                        'perfect':              1 if safe_int(att.get('score', 0)) == 5 else 0,
                    }
                    rows.append(row)
    return rows


# ─── QUESTIONNAIRE ────────────────────────────────────────────────────────────
def build_questionnaire(sessions):
    """One row per participant with all questionnaire answers."""
    rows = []
    for s in sessions:
        q = s.get('questionnaire', {})
        if not q:
            continue
        answers = q.get('answers', {})
        row = {'participant_id': s.get('participant_id', '')}
        for k, v in answers.items():
            row[f'q_{k}'] = v
        row['submitted_at'] = q.get('submitted_at', '')
        rows.append(row)
    return rows


# ─── UES ──────────────────────────────────────────────────────────────────────
def build_ues(sessions):
    """One row per participant with UES answers and computed dimension scores."""
    DIMENSIONS = {
        'FA': ['FA1','FA2','FA3'],
        'PU': ['PU1','PU2','PU3'],
        'AE': ['AE1','AE2','AE3'],
        'RW': ['RW1','RW2','RW3'],
    }
    # PU items are reverse-scored (frustration, confusion, taxing)
    REVERSE = {'PU1', 'PU2', 'PU3'}

    rows = []
    for s in sessions:
        ues = s.get('ues_questionnaire', {})
        if not ues:
            continue
        answers = ues.get('answers', {})
        row = {
            'participant_id': s.get('participant_id', ''),
            'submitted_at':   ues.get('submitted_at', ''),
            'presentation_order': ','.join(ues.get('order', [])),
        }
        # Raw items
        for item_id, val in answers.items():
            row[f'ues_{item_id}'] = val

        # Dimension scores (mean of reverse-scored items where applicable)
        for dim, items in DIMENSIONS.items():
            scores = []
            for item in items:
                v = answers.get(item)
                if v is not None:
                    v = int(v)
                    if item in REVERSE:
                        v = 6 - v  # reverse: 1→5, 2→4, 3→3, 4→2, 5→1
                    scores.append(v)
            row[f'ues_{dim}_mean'] = round(sum(scores)/len(scores), 3) if scores else None

        # Total UES mean
        all_scores = []
        for dim, items in DIMENSIONS.items():
            for item in items:
                v = answers.get(item)
                if v is not None:
                    v = int(v)
                    if item in REVERSE:
                        v = 6 - v
                    all_scores.append(v)
        row['ues_total_mean'] = round(sum(all_scores)/len(all_scores), 3) if all_scores else None

        rows.append(row)
    return rows


# ─── WRITE CSV ────────────────────────────────────────────────────────────────
def write_csv(rows, path):
    if not rows:
        print(f"  No data for {path}")
        return
    keys = list(rows[0].keys())
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓ {path}  ({len(rows)} rows)")


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='Export triage session data to CSV')
    parser.add_argument('--db',  default='data/sessions.db', help='Path to sessions.db or sessions.json from /api/sessions')
    parser.add_argument('--out', default='.',                 help='Output directory')
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"[ERROR] File not found: {args.db}")
        print("  Options:")
        print("  1. SQLite:  python analyze_sessions.py --db data/sessions.db")
        print("  2. JSON:    curl https://YOUR-APP.railway.app/api/sessions > sessions.json")
        print("              python analyze_sessions.py --db sessions.json")
        return

    os.makedirs(args.out, exist_ok=True)

    print(f"Loading sessions from: {args.db}")
    sessions = load_sessions(args.db)
    print(f"  Found {len(sessions)} session(s)\n")

    print("Writing CSV files:")
    write_csv(build_sessions_summary(sessions), os.path.join(args.out, 'sessions_summary.csv'))
    write_csv(build_attempts(sessions),          os.path.join(args.out, 'attempts.csv'))
    write_csv(build_questionnaire(sessions),     os.path.join(args.out, 'questionnaire.csv'))
    write_csv(build_ues(sessions),               os.path.join(args.out, 'ues.csv'))

    print(f"\nDone. Files saved to: {os.path.abspath(args.out)}")
    print("\nQuick pandas example:")
    print("  import pandas as pd")
    print("  summary = pd.read_csv('sessions_summary.csv')")
    print("  attempts = pd.read_csv('attempts.csv')")
    print("  ues = pd.read_csv('ues.csv')")
    print("  merged = summary.merge(ues, on='participant_id')")


if __name__ == '__main__':
    main()
