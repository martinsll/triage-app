'''
#Codi Lavinia per solucionar problemes de detecció de més de 3 additional processes
def _camera_cb(self, msg):
        """
        Receive camera frame, detect ArUco markers,
        parse board state, and cache latest perception.
        """

        import time

        try:
            # ROS Image -> OpenCV image
            frame = self.bridge.imgmsg_to_cv2(
                msg,
                desired_encoding='passthrough'
            )

            # Convert YUY2 -> BGR
            frame = cv2.cvtColor(
                frame,
                cv2.COLOR_YUV2BGR_YUY2
            )

        except Exception as e:
            self.get_logger().error(f"CvBridge error: {e}")
            return

        try:
            # ------------------------------------------------------------
            # Detect markers
            # ------------------------------------------------------------
            markers = self.detect_all_markers(
                frame,
                self.aruco_detector
            )

            # ------------------------------------------------------------
            # Extract board corner markers
            # ------------------------------------------------------------
            corner_markers = {
                k: v for k, v in markers.items()
                if k in CORNER_IDS
            }

            # ------------------------------------------------------------
            # Compute board corners
            # ------------------------------------------------------------
            board_corners = self.get_board_corners(
                corner_markers
            )

            board_found = board_corners is not None

            # ------------------------------------------------------------
            # Parse scene
            # ------------------------------------------------------------
            board_state, all_visible, raw_process_state = self.parse_scene(
                markers,
                board_corners
            )

            # ============================================================
            # STABLE PROCESS TRACKING (TIME-BASED)
            # ============================================================

            now = time.time()

            # Timeout in seconds before removing unseen markers
            VISIBLE_TIMEOUT = 1.5

            # ------------------------------------------------------------
            # Update last-seen timestamps
            # ------------------------------------------------------------
            #
            # self.process_last_seen should be initialized once in __init_:
            #
            # self._process_last_seen = {}
            #
            # format:
            # {
            #   (pid, proc_id): timestamp
            # }
            #
            # ------------------------------------------------------------

            for pid, proc_ids in raw_process_state.items():
                for proc_id in proc_ids:
                    key = (pid, proc_id)
                    self._process_last_seen[key] = now

            # ------------------------------------------------------------
            # Build stable process state
            # ------------------------------------------------------------

            stable_processes = {}

            expired_keys = []

            for (pid, proc_id), last_seen in self._process_last_seen.items():

                # Keep marker alive for timeout window
                if (now - last_seen) < VISIBLE_TIMEOUT:
                    stable_processes.setdefault(pid, set()).add(proc_id)

                else:
                    expired_keys.append((pid, proc_id))

            # ------------------------------------------------------------
            # Cleanup expired markers
            # ------------------------------------------------------------

            for key in expired_keys:
                del self._process_last_seen[key]

            # ------------------------------------------------------------
            # Convert sets -> sorted lists
            # ------------------------------------------------------------

            process_state_integer = {
                pid: sorted(procs)
                for pid, procs in stable_processes.items()
            }

            process_state = {
                pid: sorted(
                    ARUCO_TO_PROCESS.get(p, p)
                    for p in procs
                )
                for pid, procs in stable_processes.items()
            }
'''
# -*- coding: utf-8 -*-
"""
Triage Game — Main Loop (v2)
==============================
Integrates camera detection + game engine + agent into one runnable script.

Detection each frame:
  1. Detect all ArUco markers
  2. Board corners (IDs 0-3) → compute 5 slots
  3. Patient cards (IDs 10-49) → assign to slots
  4. Destination cards (IDs 50-53) → map to patient in same slot
  5. Feed results to GameEngine.update()
  6. Print robot actions to terminal (TTS placeholder)

Controls:
  1/2/3/4  — start iteration
  R        — trigger evaluation (participant says "ready")
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
from game_engine import GameEngine, Phase

# ─── CONFIG ───────────────────────────────────────────────────────────────────
ARUCO_DICT  = cv2.aruco.DICT_4X4_100
N_SLOTS     = 5
UPSCALE     = 2.0

CORNER_IDS  = {0, 1, 2, 3}
PATIENT_IDS = set(range(10, 50))
DEST_IDS = {50, 51, 52, 53}

DEST_NAMES_SHORT = {
    50: "SurgBay",
    51: "RiskWard",
    52: "MonWard",
    53: "GenWard",
}

ARUCO_TO_DEST = {
    50: "Surgical Bay",
    51: "Risk Ward",
    52: "Monitored Ward",
    53: "General Ward",
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
        markers[0].mean(axis=0),  # centre of TL marker
        markers[1].mean(axis=0),  # centre of TR marker
        markers[2].mean(axis=0),  # centre of BL marker
        markers[3].mean(axis=0),  # centre of BR marker
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
                                    True)   # True = actual distance
        if dist >= -5:
            return idx
    return None

def find_slot_majority(corners_array, slots):
    """
    Assign a marker to a slot by majority vote across all 4 corners.
    More robust than centroid-only when marker straddles a slot boundary.
    Falls back to centroid if no corners land in any slot.
    """
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
      dest_state:      {pid: dest_aruco_id}  — one destination card per patient
    """
    if board_corners is None:
        return {}, [], {}

    slots = compute_slots(board_corners)
    slot_to_patient   = {}   # slot_idx → pid
    slot_to_dest      = {}   # slot_idx → aruco_id (one per slot)

    for aruco_id, corners in markers.items():
        # Use majority corner voting for robust slot assignment
        slot_idx = find_slot_majority(corners, slots)
        if slot_idx is None:
            continue
        if aruco_id in PATIENT_IDS:
            _, pid = PATIENT_DB[aruco_id]
            slot_to_patient[slot_idx] = pid
        elif aruco_id in DEST_IDS:
            slot_to_dest[slot_idx] = aruco_id

    board_state = {idx+1: pid for idx, pid in slot_to_patient.items()}
    dest_state  = {}
    for slot_idx, dest_id in slot_to_dest.items():
        pid = slot_to_patient.get(slot_idx)
        if pid:
            dest_state[pid] = [dest_id]  # list for compatibility with stability buffer

    all_visible = [aid for aid in markers if aid in PATIENT_IDS]
    return board_state, all_visible, dest_state

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
            print(f"  Destinations: {s.get('destinations',{}).get('final_score','?')} "
                  f"({s.get('destinations',{}).get('attempts','?')} attempts)")
    return has_speech

def format_status(engine, board_state, dest_state_int,
                  corners_found, board_found):
    phase = engine.phase.name
    if not board_found:
        return f"[{corners_found}/4 corners] [Phase: {phase}]"
    parts = []
    for slot in range(1, N_SLOTS+1):
        pid      = board_state.get(slot, "----")
        dest_ids = dest_state_int.get(pid, []) if pid != "----" else []
        dest_str = DEST_NAMES_SHORT.get(dest_ids[0], "?") if dest_ids else ""
        cell = f"[{slot}:{pid}" + (f"|{dest_str}" if dest_str else "") + "]"
        parts.append(cell)
    return f"[{phase}]  " + "  ".join(parts)

# ─── QUESTION INPUT ───────────────────────────────────────────────────────────

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
    print("  1/2/3/4  start iteration")
    print("  R        ready / trigger evaluation")
    print("  L        toggle language en/es")
    print("  I        print game state")
    print("  S        snapshot")
    print("  X        quit")
    print("─" * 58)

    aruco_dict   = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    aruco_params = cv2.aruco.DetectorParameters()
    aruco_det    = cv2.aruco.ArucoDetector(aruco_dict, aruco_params)

    engine     = GameEngine(set_label=args.set, mode=args.mode,
                            language=args.lang)
    snapshot_n = 0
    last_status = ""

    # Stability buffer — destination cards must be detected for N consecutive
    # frames before being committed. Prevents flickering false positives.
    STABLE_FRAMES  = 15   # frames to commit (~0.5s at 30fps)
    DECAY_RATE     = 1    # slower decay = more tolerant of brief occlusions
    dest_counter   = {}   # {(pid, dest_id): frame_count}
    stable_dests   = {}   # {pid: set(dest_ids)} — committed stable state

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # ── Detection ─────────────────────────────────────────────────────
        markers        = detect_all_markers(frame, aruco_det)
        corner_markers = {k:v for k,v in markers.items() if k in CORNER_IDS}
        board_corners  = get_board_corners(corner_markers)
        board_found    = board_corners is not None

        board_state, all_visible, raw_dest_state = parse_scene(
            markers, board_corners)

        # ── Stability buffering for destination cards ─────────────────────
        seen_pairs = set()
        for pid, dest_ids in raw_dest_state.items():
            for dest_id in dest_ids:
                key = (pid, dest_id)
                seen_pairs.add(key)
                dest_counter[key] = dest_counter.get(key, 0) + 1
                if dest_counter[key] >= STABLE_FRAMES:
                    stable_dests.setdefault(pid, set()).add(dest_id)

        for key in list(dest_counter.keys()):
            if key not in seen_pairs:
                dest_counter[key] = max(0, dest_counter[key] - DECAY_RATE)
                if dest_counter[key] == 0:
                    pid, dest_id = key
                    if pid in stable_dests:
                        stable_dests[pid].discard(dest_id)
                        if not stable_dests[pid]:
                            del stable_dests[pid]
                    del dest_counter[key]

        # Convert to engine format: {pid: [dest_id]} (single id per patient)
        dest_state     = {pid: [next(iter(ids))] for pid, ids in stable_dests.items() if ids}
        dest_state_int = {pid: sorted(ids)       for pid, ids in stable_dests.items() if ids}

        # ── Feed engine ────────────────────────────────────────────────────
        if engine.phase != Phase.IDLE:
            actions = engine.update(board_state, all_visible, dest_state)
            if actions:
                had_speech = handle_actions(actions)
                if had_speech:
                    last_status = ""  # force reprint only after speech

        # ── Status line — only reprint when changed ────────────────────────

        status = format_status(engine, board_state, dest_state_int,
                               len(corner_markers), board_found)
        
        if status != last_status:
            print(f"\r{status:<120}", end="", flush=True)
            last_status = status
        cv2.imshow("Triage Game", frame)

        key = cv2.waitKey(30) & 0xFF

        if key == ord('x'):
            print()
            break

        elif key in (ord('1'), ord('2'), ord('3'), ord('4')):
            iteration = int(chr(key))
            print(f"\n[Starting iteration {iteration}]")
            actions = engine.start_iteration(iteration)
            handle_actions(actions)
            # Reset destination stability buffer for new iteration
            dest_counter = {}
            stable_dests = {}

        elif key == ord('r'):
            print()
            engine.trigger_evaluation()
            actions = engine.update(board_state, all_visible, dest_state)
            handle_actions(actions)

        elif key == ord('l'):
            new_lang = "es" if engine.language == "en" else "en"
            engine.set_language(new_lang)
            print(f"\n[Language → {new_lang}]")

        elif key == ord('i'):
            print()
            print(f"  Phase:    {engine.phase.name}")
            print(f"  Board:    {board_state}")
            print(f"  Destinations:{dest_state}")
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
