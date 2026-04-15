# -*- coding: utf-8 -*-
"""
Triage Game — Main Loop (v2)
==============================
Integrates camera detection + game engine + agent into one runnable script.

Detection each frame:
  1. Detect all ArUco markers
  2. Board corners (IDs 0-3) → compute 5 slots
  3. Patient cards (IDs 10-49) → assign to slots
  4. Process cards (IDs 50-53) → map to patient in same slot
  5. Feed results to GameEngine.update()
  6. Print robot actions to terminal (TTS placeholder)

Controls:
  1/2/3/4  — start iteration
  R        — trigger evaluation (participant says "ready")
  Q        — ask a question (participant asks agent something)
  L        — toggle language en/es
  I        — print current game state
  S        — save snapshot
  X        — quit

Usage:
  python main_game.py --set A --mode error_based --lang en
  python main_game.py --set B --mode guided_learning --lang es

Requirements:
  pip install opencv-contrib-python
"""

import cv2
import numpy as np
import sys
import argparse
import time
from game_engine import GameEngine, Phase, ARUCO_TO_PID

# ─── CONFIG ───────────────────────────────────────────────────────────────────
ARUCO_DICT  = cv2.aruco.DICT_4X4_100
N_SLOTS     = 5
UPSCALE     = 2.0

CORNER_IDS  = {0, 1, 2, 3}
PATIENT_IDS = set(range(10, 50))
PROCESS_IDS = {50, 51, 52, 53}

PROCESS_NAMES = {
    50: "RapidResp",
    51: "Stretcher",
    52: "Companion",
    53: "Interpreter",
}

PATIENT_DB = {
    10:("A","P01"), 11:("A","P02"), 12:("A","P03"), 13:("A","P04"),
    14:("A","P05"), 15:("A","P06"), 16:("A","P07"), 17:("A","P08"),
    18:("A","P09"), 19:("A","P10"), 20:("A","P11"), 21:("A","P12"),
    22:("A","P13"), 23:("A","P14"), 24:("A","P15"), 25:("A","P16"),
    26:("A","P17"), 27:("A","P18"), 28:("A","P19"), 29:("A","P20"),
    30:("B","P01"), 31:("B","P02"), 32:("B","P03"), 33:("B","P04"),
    34:("B","P05"), 35:("B","P06"), 36:("B","P07"), 37:("B","P08"),
    38:("B","P09"), 39:("B","P10"), 40:("B","P11"), 41:("B","P12"),
    42:("B","P13"), 43:("B","P14"), 44:("B","P15"), 45:("B","P16"),
    46:("B","P17"), 47:("B","P18"), 48:("B","P19"), 49:("B","P20"),
}

# ─── PREPROCESSING ────────────────────────────────────────────────────────────
def preprocess(frame, upscale=UPSCALE):
    h, w = frame.shape[:2]
    large = cv2.resize(frame, (int(w*upscale), int(h*upscale)),
                       interpolation=cv2.INTER_CUBIC)
    gray  = cv2.cvtColor(large, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    gray  = clahe.apply(gray)
    _, binary = cv2.threshold(gray, 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary

# ─── ARUCO DETECTION ──────────────────────────────────────────────────────────
def detect_all_markers(frame, detector):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detector.detectMarkers(gray)
    result = {}
    if ids is not None:
        for i, mid in enumerate(ids.flatten()):
            result[int(mid)] = corners[i][0]
    return result

# ─── BOARD GEOMETRY ───────────────────────────────────────────────────────────
def get_board_corners(markers):
    if not {0,1,2,3}.issubset(markers.keys()):
        return None
    # Use centroid of each corner marker — stable regardless of orientation
    return np.array([
        markers[0].mean(axis=0),
        markers[1].mean(axis=0),
        markers[2].mean(axis=0),
        markers[3].mean(axis=0),
    ], dtype=np.float32)

def compute_slots(board_corners, n=N_SLOTS):
    tl, tr, bl, br = board_corners
    slots = []
    for i in range(n):
        t0 = tl + (tr-tl) * (i/n)
        t1 = tl + (tr-tl) * ((i+1)/n)
        b0 = bl + (br-bl) * (i/n)
        b1 = bl + (br-bl) * ((i+1)/n)
        slots.append(np.array([t0,t1,b1,b0], dtype=np.float32))
    return slots

def find_slot(centre, slots):
    """Returns slot index (0-based) or None. Uses actual pixel distance."""
    for idx, poly in enumerate(slots):
        dist = cv2.pointPolygonTest(poly,
                                    (float(centre[0]), float(centre[1])),
                                    True)
        if dist >= -5:
            return idx
    return None

def find_slot_majority(corners_array, slots):
    """Majority vote across 4 corners — robust near slot boundaries."""
    votes = {}
    for corner in corners_array:
        idx = find_slot(corner, slots)
        if idx is not None:
            votes[idx] = votes.get(idx, 0) + 1
    if not votes:
        return find_slot(corners_array.mean(axis=0), slots)
    return max(votes, key=lambda k: (votes[k], -k))

# ─── SCENE PARSER ─────────────────────────────────────────────────────────────
def parse_scene(markers, board_corners):
    """
    Returns:
      board_state:     {slot(1-5): pid}
      all_visible_ids: [aruco_id, ...]  all patient IDs visible anywhere
      process_state:   {pid: [process_aruco_ids]}
    """
    if board_corners is None:
        return {}, [], {}

    slots = compute_slots(board_corners)
    slot_to_patient  = {}   # slot_idx → pid
    slot_to_processes = {}  # slot_idx → [aruco_id]

    for aruco_id, corners in markers.items():
        slot_idx = find_slot_majority(corners, slots)
        if slot_idx is None:
            continue
        if aruco_id in PATIENT_IDS:
            _, pid = PATIENT_DB[aruco_id]
            slot_to_patient[slot_idx] = pid
        elif aruco_id in PROCESS_IDS:
            slot_to_processes.setdefault(slot_idx, []).append(aruco_id)

    board_state   = {idx+1: pid for idx, pid in slot_to_patient.items()}
    process_state = {}
    for slot_idx, proc_ids in slot_to_processes.items():
        pid = slot_to_patient.get(slot_idx)
        if pid:
            process_state[pid] = proc_ids

    all_visible = [aid for aid in markers if aid in PATIENT_IDS]
    return board_state, all_visible, process_state

# ─── TERMINAL DISPLAY ─────────────────────────────────────────────────────────
def handle_actions(actions):
    has_speech = any(a['type'] == 'speak' for a in actions)
    for a in actions:
        if a['type'] == 'speak':
            print(f"\n  🤖  {a['text']}\n")
        elif a['type'] == 'state_change':
            # Only print state changes — no extra newlines
            print(f"\n  [→ {a['phase']}]")
        elif a['type'] == 'log':
            print(f"\n  [LOG] {a['phase']} attempt={a.get('attempt','')} "
                  f"score={a.get('score','')}")
        elif a['type'] == 'end_iteration':
            s = a['summary']
            sel  = s.get('selection',{})
            proc = s.get('processes',{})
            print(f"\n  ── Iteration complete ──")
            print(f"  Selection:  {sel.get('final_score','?')} "
                  f"({sel.get('attempts','?')} attempts)")
            print(f"  Processes:  {proc.get('final_score','?')} "
                  f"({proc.get('attempts','?')} attempts)")
    return has_speech

def format_status(engine, board_state, process_state,
                  corners_found, board_found):
    phase = engine.phase.name
    if not board_found:
        return f"[{corners_found}/4 corners] [Phase: {phase}]"
    parts = []
    for slot in range(1, N_SLOTS+1):
        pid   = board_state.get(slot, "----")
        procs = process_state.get(pid, []) if pid != "----" else []
        # Use short abbreviations to keep line manageable
        proc_str = "+".join(PROCESS_NAMES.get(p, "?") for p in sorted(procs))
        cell = f"[{slot}:{pid}" + (f"|{proc_str}" if proc_str else "") + "]"
        parts.append(cell)
    return f"[{phase}]  " + "  ".join(parts)

# ─── QUESTION INPUT ───────────────────────────────────────────────────────────
def get_question():
    """Pause camera loop to get typed question from participant."""
    print("\n  Type your question (or press Enter to cancel):")
    q = input("  > ").strip()
    return q if q else None

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set",  default="A", choices=["A","B"])
    parser.add_argument("--mode", default="error_based",
                        choices=["guided_learning","error_based","silent"])
    parser.add_argument("--lang", default="en", choices=["en","es"])
    args = parser.parse_args()

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("ERROR: Could not open webcam.")
        sys.exit(1)

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Camera: {w}x{h}")
    print(f"Game: Set {args.set} | Mode: {args.mode} | Lang: {args.lang}")
    print("─" * 58)
    print("Controls (click camera window first):")
    print("  1/2/3  start iteration")
    print("  V      validate (error_based mode)")
    print("  Q      ask a question")
    print("  L      toggle language en/es")
    print("  I      print game state")
    print("  S      snapshot")
    print("  X      quit")
    print("─" * 58)

    aruco_dict   = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    aruco_params = cv2.aruco.DetectorParameters()
    aruco_det    = cv2.aruco.ArucoDetector(aruco_dict, aruco_params)

    engine     = GameEngine(set_label=args.set, mode=args.mode,
                            language=args.lang)
    snapshot_n = 0
    last_status = ""

    # Stability buffer — process cards must be detected for N consecutive
    # frames before being committed. Prevents flickering false positives.
    STABLE_FRAMES    = 8
    process_counter  = {}   # {(pid, proc_id): consecutive_frame_count}
    stable_processes = {}   # {pid: set(proc_ids)} — committed stable state

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # ── Detection ─────────────────────────────────────────────────────
        markers        = detect_all_markers(frame, aruco_det)
        corner_markers = {k:v for k,v in markers.items() if k in CORNER_IDS}
        board_corners  = get_board_corners(corner_markers)
        board_found    = board_corners is not None

        board_state, all_visible, raw_process_state = parse_scene(
            markers, board_corners)

        # ── Stability buffering for process cards ─────────────────────────
        # Increment counter for currently seen (pid, proc) pairs
        seen_pairs = set()
        for pid, proc_ids in raw_process_state.items():
            for proc_id in proc_ids:
                key = (pid, proc_id)
                seen_pairs.add(key)
                process_counter[key] = process_counter.get(key, 0) + 1
                # Commit once stable
                if process_counter[key] >= STABLE_FRAMES:
                    stable_processes.setdefault(pid, set()).add(proc_id)

        # Decay counters for pairs no longer seen
        for key in list(process_counter.keys()):
            if key not in seen_pairs:
                process_counter[key] = max(0, process_counter[key] - 2)
                # Remove from stable if counter hits 0
                if process_counter[key] == 0:
                    pid, proc_id = key
                    if pid in stable_processes:
                        stable_processes[pid].discard(proc_id)
                        if not stable_processes[pid]:
                            del stable_processes[pid]
                    del process_counter[key]

        # Convert stable_processes sets to sorted lists for engine
        process_state = {pid: sorted(procs)
                         for pid, procs in stable_processes.items()}

        # Debug: print raw vs stable if they differ
        if raw_process_state != {p: sorted(s)
                                  for p, s in stable_processes.items()
                                  if s}:
            raw_str = str(raw_process_state)
            if len(raw_str) < 80:
                pass  # uncomment below to debug
                # print(f"\n  [RAW] {raw_str}", flush=True)

        # ── Feed engine ────────────────────────────────────────────────────
        if engine.phase != Phase.IDLE:
            actions = engine.update(board_state, all_visible, process_state)
            if actions:
                had_speech = handle_actions(actions)
                if had_speech:
                    last_status = ""  # force reprint only after speech

        # ── Status line — only reprint when changed ────────────────────────
        status = format_status(engine, board_state, process_state,
                               len(corner_markers), board_found)
        if status != last_status:
            print(f"\r{status:<120}", end="", flush=True)
            last_status = status
        cv2.imshow("Triage Game", frame)

        key = cv2.waitKey(30) & 0xFF

        if key == ord('x'):
            print()
            break

        elif key in (ord('1'), ord('2'), ord('3')):
            iteration = int(chr(key))
            print(f"\n[Starting iteration {iteration}]")
            actions = engine.start_iteration(iteration)
            handle_actions(actions)
            # Reset process stability buffer for new iteration
            process_counter  = {}
            stable_processes = {}

        elif key == ord('v'):
            print()
            engine.trigger_evaluation()
            actions = engine.update(board_state, all_visible, process_state)
            handle_actions(actions)

        elif key == ord('q'):
            print()
            question = get_question()
            if question:
                actions = engine.ask_question(question)
                handle_actions(actions)

        elif key == ord('l'):
            new_lang = "es" if engine.language == "en" else "en"
            engine.set_language(new_lang)
            print(f"\n[Language → {new_lang}]")

        elif key == ord('i'):
            print()
            print(f"  Phase:    {engine.phase.name}")
            print(f"  Board:    {board_state}")
            print(f"  Processes:{process_state}")
            if engine.result:
                print(f"  Summary:  {engine.result.summary()}")
            print(f"  Session:  {engine.get_session_log()}")

        elif key == ord('s'):
            fname = f"snapshot_{snapshot_n:02d}.jpg"
            cv2.imwrite(fname, frame)
            print(f"\nSaved {fname}")
            snapshot_n += 1

    engine.save_session_log(
        f"session_{args.set}_{args.mode}_{int(time.time())}.json")
    cap.release()
    cv2.destroyAllWindows()
    print("Done.")

if __name__ == "__main__":
    main()
