# -*- coding: utf-8 -*-
"""
Triage Session Data Extractor — Single flat CSV
=================================================
One row per participant. All data flattened.

Usage:
  python analyze_sessions.py                          # uses data/sessions.db
  python analyze_sessions.py --db sessions.json --out ./results/
"""

import sqlite3, json, csv, os, argparse
from datetime import datetime


def load_sessions(path):
    if path.endswith('.json'):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        if not content:
            return []
        data = json.loads(content)
        return data if isinstance(data, list) else data.get('sessions', [])
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT data FROM sessions ORDER BY created_at").fetchall()
    conn.close()
    return [json.loads(r[0]) for r in rows]


def safe_int(val):
    if isinstance(val, str) and '/' in val:
        try: return int(val.split('/')[0])
        except: return None
    try: return int(val)
    except: return None


def duration_sec(t1, t2):
    if not t1 or not t2: return None
    try: return round((datetime.fromisoformat(t2) - datetime.fromisoformat(t1)).total_seconds())
    except: return None


def flatten_phase(row, prefix, it, phase):
    """Flatten one phase (selection/processes/destinations) into row."""
    ph  = it.get(phase, {})
    att = ph.get('attempts', [])
    if not att:
        return
    a  = att[-1]
    sc = safe_int(a.get('score', 0)) or 0
    rc = a.get('rule_metrics', {}) or {}

    row[f'{prefix}_{phase}_score']        = sc
    row[f'{prefix}_{phase}_time_sec']     = a.get('phase_time_sec')
    row[f'{prefix}_{phase}_rule_consult'] = rc.get('total_consultations', 0) if isinstance(rc, dict) else 0
    row[f'{prefix}_{phase}_rule_time_sec']= round(rc.get('total_time_ms', 0) / 1000, 1) if isinstance(rc, dict) else 0

    # Correction screen tracking (to be added later)
    corr = a.get('correction', {}) or {}
    row[f'{prefix}_{phase}_correction_time_sec']      = corr.get('time_sec')
    row[f'{prefix}_{phase}_correction_rule_time_sec'] = round(corr.get('rule_time_ms', 0) / 1000, 1) if corr else 0

    if phase == 'selection':
        row[f'{prefix}_kendall_tau']         = a.get('kendall_tau')
        ps = a.get('phase_score', {})
        if isinstance(ps, dict):
            row[f'{prefix}_phase_score']         = ps.get('total')
            row[f'{prefix}_tier_ordering_score'] = ps.get('tier_ordering_score')
            row[f'{prefix}_within_tier_score']   = ps.get('within_tier_score')


def flatten_label(row, label, iters):
    """Flatten all groups for a given label (train or test)."""
    # Filter iterations by phase label
    label_iters = {k: v for k, v in iters.items()
                   if v.get('phase', 'train') == label or k.startswith(f'{label}_')}

    # Sort by group number
    sorted_iters = sorted(label_iters.items(),
                          key=lambda x: int(x[1].get('group', x[0].split('_')[-1])))

    total_sel = total_proc = total_dest = 0
    total_rule_consult = 0
    total_rule_time_ms = 0

    # Totals first
    for _, it in sorted_iters:
        grp = it.get('group', 0)
        prefix = f'{label}_g{grp}'
        for phase in ('selection', 'processes', 'destinations'):
            ph = it.get(phase, {})
            att = ph.get('attempts', [])
            if att:
                sc = safe_int(att[-1].get('score', 0)) or 0
                rc = att[-1].get('rule_metrics', {}) or {}
                if phase == 'selection':   total_sel  += sc
                if phase == 'processes':   total_proc += sc
                if phase == 'destinations':total_dest += sc
                if isinstance(rc, dict):
                    total_rule_consult += rc.get('total_consultations', 0)
                    total_rule_time_ms += rc.get('total_time_ms', 0)

    row[f'{label}_sel_total']     = total_sel
    row[f'{label}_proc_total']    = total_proc
    row[f'{label}_dest_total']    = total_dest
    row[f'{label}_total']         = total_sel + total_proc + total_dest
    row[f'{label}_max']           = len(sorted_iters) * 15
    row[f'{label}_rule_consult']  = total_rule_consult
    row[f'{label}_rule_time_sec'] = round(total_rule_time_ms / 1000, 1)

    # Per-group detail
    for _, it in sorted_iters:
        grp    = it.get('group', 0)
        prefix = f'{label}_g{grp}'
        for phase in ('selection', 'processes', 'destinations'):
            flatten_phase(row, prefix, it, phase)


def flatten_session(s):
    row = {}

    # ── PARTICIPANT INFO ───────────────────────────────────────────────────────
    row['participant_id'] = s.get('participant_id', '')
    row['condition']      = s.get('condition', 'web')
    row['mode']           = s.get('mode', 'error_based')
    row['language']       = s.get('language', '')
    row['set']            = s.get('set', '')
    row['created_at']     = s.get('created_at', '')
    row['completed_at']   = s.get('completed_at', '')

    # ── DEMOGRAPHICS ──────────────────────────────────────────────────────────
    demo = s.get('demographics', {}).get('answers', {})
    row['age']               = demo.get('age')
    row['gender']            = demo.get('gender')
    row['education']         = demo.get('education')
    row['robot_experience']  = demo.get('robot_experience')

    # ── TIMING ────────────────────────────────────────────────────────────────
    row['instructions_time_sec'] = s.get('onboarding', {}).get('instructions_time_sec')
    row['rules_time_sec']        = s.get('onboarding', {}).get('rules_time_sec')
    row['train_duration_sec']    = duration_sec(s.get('game_started_at'), s.get('train_completed_at'))
    row['test_duration_sec']     = duration_sec(s.get('test_started_at'), s.get('completed_at'))

    # ── GAME SCORES: TRAIN then TEST ─────────────────────────────────────────
    iters = s.get('iterations', {})
    flatten_label(row, 'train', iters)
    flatten_label(row, 'test',  iters)

    # ── NASA-TLX ──────────────────────────────────────────────────────────────
    nasa = s.get('nasa_tlx', {}).get('answers', {})
    for dim in ('mental','physical','temporal','performance','effort','frustration'):
        row[f'nasa_{dim}'] = nasa.get(dim)
    row['nasa_mean'] = round(sum(v for v in nasa.values() if v is not None) / len(nasa), 1) if nasa else None

    # ── UES ───────────────────────────────────────────────────────────────────
    ues     = s.get('ues_questionnaire', {})
    ues_ans = ues.get('answers', {})
    REVERSE = {'PU1','PU2','PU3'}
    DIMS    = {'FA':['FA1','FA2','FA3'],'PU':['PU1','PU2','PU3'],
               'AE':['AE1','AE2','AE3'],'RW':['RW1','RW2','RW3']}

    row['ues_presentation_order'] = ','.join(ues.get('order', []))
    all_ues = []
    for item_id in ['FA1','FA2','FA3','PU1','PU2','PU3','AE1','AE2','AE3','RW1','RW2','RW3']:
        row[f'ues_{item_id}'] = ues_ans.get(item_id)
    for dim, items in DIMS.items():
        scores = []
        for item in items:
            v = ues_ans.get(item)
            if v is not None:
                v = int(v)
                if item in REVERSE: v = 6 - v
                scores.append(v); all_ues.append(v)
        row[f'ues_{dim}_mean'] = round(sum(scores)/len(scores), 3) if scores else None
    row['ues_total_mean'] = round(sum(all_ues)/len(all_ues), 3) if all_ues else None

    # ── QUESTIONNAIRE ─────────────────────────────────────────────────────────
    for k, v in s.get('questionnaire', {}).get('answers', {}).items():
        row[f'q_{k}'] = v

    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',  default='data/sessions.db')
    parser.add_argument('--out', default='.')
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"[ERROR] File not found: {args.db}")
        print("  Download: curl -u admin:triage2024 https://YOUR-APP.railway.app/api/sessions > sessions.json")
        return

    print(f"Loading from: {args.db}")
    sessions = load_sessions(args.db)
    if not sessions:
        print("  No sessions found.")
        return
    print(f"  {len(sessions)} session(s)")

    rows = [flatten_session(s) for s in sessions]

    # Collect all columns preserving insertion order
    all_keys = list(dict.fromkeys(k for row in rows for k in row))

    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, 'triage_data.csv')
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in all_keys})

    print(f"  ✓ {out_path}  ({len(rows)} rows × {len(all_keys)} columns)")
    print("\nQuick pandas:")
    print("  import pandas as pd")
    print("  df = pd.read_csv('triage_data.csv')")
    print("  df.groupby('mode')[['train_total','test_total']].mean()")

if __name__ == '__main__':
    main()
