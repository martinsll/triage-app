# -*- coding: utf-8 -*-
"""
Triage Game — Terminal Simulator (v3)
=======================================
Supports: guided_learning | error_based

Usage:
  python simulator.py --set A --mode guided_learning --lang en
  python simulator.py --set B --mode error_based --lang es
"""

import argparse, sys
from game_engine import (
    GameEngine, Phase, ITERATIONS, PID_TO_PATIENT,
    CORRECT_PROCESSES, CORRECT_DESTINATIONS, PROCESS_NAMES
)

SEP  = "─" * 58
SEP2 = "═" * 58

def hdr(t):   print(SEP2+f"\n  {t}\n"+SEP2)
def sec(t):   print(f"\n{SEP}\n  {t}\n{SEP}")
def robot(t): print(f"\n  🤖  {t}\n")

def show(actions):
    for a in actions:
        if   a['type']=='speak':         robot(a['text'])
        elif a['type']=='state_change':  print(f"  [→ {a['phase']}]")
        elif a['type']=='slot_target':   print(f"  [TARGET] slot {a['slot']} → {a['pid']}")
        elif a['type']=='process_target':print(f"  [PROCESS TARGET] {a['pid']} → {a.get('processes',[])}")
        elif a['type']=='log':           print(f"  [LOG] {a['phase']} attempt={a.get('attempt','')} score={a.get('score','')}")
        elif a['type']=='end_iteration':
            s=a['summary']
            print(f"\n  ── Iteration complete ──")
            print(f"  Selection: {s['selection']['final_score']} ({s['selection']['attempts']} attempts)")
            print(f"  Processes: {s['processes']['final_score']} ({s['processes']['attempts']} attempts)")

def ask_question(engine):
    q = input("  Your question: ").strip()
    if q:
        show(engine.ask_question(q))

def patient_ref(set_label, pids):
    print(f"\n  {'PID':<5} {'Name':<20} {'Condition':<14} Onset      Alertness")
    print("  "+"-"*65)
    for pid in sorted(pids, key=lambda p: int(p[1:])):
        p = PID_TO_PATIENT[(set_label, pid)]
        print(f"  {pid:<5} {p['name']:<20} {p['condition']:<14} "
              f"{p['onset']:<10} {p['alertness']}")

def correct_answer(set_label, iteration):
    pids = ITERATIONS[set_label][iteration]
    print(f"\n  ✓ Order: {' → '.join(pids)}")
    for pid in pids:
        procs = CORRECT_PROCESSES[set_label].get(pid,[])
        dest  = CORRECT_DESTINATIONS[set_label].get(pid,"?")
        names = [PROCESS_NAMES[p] for p in procs] if procs else ["none"]
        print(f"    {pid}: {', '.join(names)} | → {dest}")

# ─── GUIDED LEARNING RUNNER ───────────────────────────────────────────────────
def run_guided(engine, set_label, iteration):
    """Simulate guided learning slot by slot."""
    pids = ITERATIONS[set_label][iteration]

    sec("GUIDED — CARD SCAN")
    input("  [Enter to simulate showing a card to the robot]")
    base = 10 if set_label=="A" else 40
    pid_idx = int(pids[0][1:]) - 1
    show(engine.update({}, [base + pid_idx], {}))

    # Slot by slot
    current_board = {}
    while engine.phase in (Phase.SLOT_WAIT, Phase.SLOT_GUIDANCE):
        slot = engine.current_slot
        target = pids[slot-1]
        sec(f"SLOT {slot} — target: {target}")
        print(f"  Available PIDs: {', '.join(sorted(pids, key=lambda p:int(p[1:])))}")

        while True:
            cmd = input(f"  [Enter={target}] [other PID] [Q=question]: ").strip().upper()
            if cmd == 'Q':
                ask_question(engine)
            elif cmd == '' or cmd == target:
                current_board[slot] = target
                show(engine.update(dict(current_board), [], {}))
                break
            elif cmd in pids:
                # Wrong card placed
                current_board[slot] = cmd
                show(engine.update(dict(current_board), [], {}))
                # Remove wrong card for retry
                current_board.pop(slot, None)
            else:
                print(f"  Unknown PID. Available: {pids}")

    return current_board

# ─── ERROR-BASED RUNNER ───────────────────────────────────────────────────────
def run_error_based_selection(engine, set_label, iteration):
    """Simulate error-based selection with validate loop."""
    pids = ITERATIONS[set_label][iteration]

    sec("ERROR-BASED — PLACEMENT")
    print(f"  Correct order (for testing): {pids}")
    print(f"  Available PIDs: {', '.join(sorted(pids, key=lambda p:int(p[1:])))}")
    print("  Enter=correct  or  type 5 comma-separated PIDs")

    def get_board():
        while True:
            raw = input("  Slots 1-5: ").strip()
            if raw == "":
                return {i+1:p for i,p in enumerate(pids)}
            parts = [x.strip().upper() for x in raw.split(",")]
            if len(parts) != 5:
                print(f"  Need 5 PIDs."); continue
            invalid = [p for p in parts if p not in pids]
            if invalid:
                print(f"  Unknown: {invalid}"); continue
            return {i+1:p for i,p in enumerate(parts)}

    board = get_board()
    engine._board_state = board

    while engine.phase not in (Phase.PROCESS_INTRO, Phase.PROCESS_PLACING,
                                Phase.PROCESS_WAIT, Phase.ITERATION_COMPLETE):
        while True:
            cmd = input("\n  [V]=validate  [Q]=question: ").strip().lower()
            if cmd == 'q':
                ask_question(engine)
            elif cmd == 'v':
                break
        engine.trigger_evaluation()
        show(engine.update(board, [], {}))

        if engine.phase == Phase.SELECTION_CORRECTION:
            print("\n  Re-arrange cards (Enter=correct):")
            board = get_board()
            engine._board_state = board

    return board

# ─── PROCESS PHASE ────────────────────────────────────────────────────────────
def run_process_phase(engine, set_label, iteration, current_mode):
    """Run process phase for both modes."""
    pids = ITERATIONS[set_label][iteration]

    if current_mode == "guided_learning":
        # Guided: slot by slot process attachment
        current_procs = {}
        while engine.phase in (Phase.PROCESS_WAIT, Phase.PROCESS_GUIDANCE,
                                Phase.PROCESS_INTRO):
            if engine.phase == Phase.PROCESS_INTRO:
                show(engine.update({},{},{}))
                continue
            slot = engine.current_slot
            target_pid = pids[slot-1]
            expected = sorted(CORRECT_PROCESSES[set_label].get(target_pid,[]))
            sec(f"PROCESS SLOT {slot} — {target_pid}")
            print(f"  Process IDs: 50=RapidResponse 51=Stretcher "
                  f"52=CompanionBay 53=Interpreter")
            expected_str = ", ".join(str(p) for p in expected) if expected else "none"

            while True:
                cmd = input(f"  [Enter={expected_str}] [IDs] [Q=question]: ").strip().lower()
                if cmd == 'q':
                    ask_question(engine)
                elif cmd in ('','c'):
                    current_procs[target_pid] = expected
                    show(engine.update({}, [], dict(current_procs)))
                    break
                elif cmd == 'none' or cmd == '0':
                    current_procs[target_pid] = []
                    show(engine.update({}, [], dict(current_procs)))
                    break
                else:
                    try:
                        ids = sorted([int(x) for x in cmd.split(",")])
                        current_procs[target_pid] = ids
                        show(engine.update({}, [], dict(current_procs)))
                        break
                    except ValueError:
                        print("  Invalid input.")
    else:
        # Error-based: attach all at once, then validate
        sec("PROCESS PHASE — ERROR-BASED")
        print("  Process IDs: 50=RapidResponse 51=Stretcher "
              "52=CompanionBay 53=Interpreter")
        print("  Enter=correct  or  type: PID:IDs,IDs ... (e.g. A02:50,51)")

        def get_procs():
            raw = input("  Processes [Enter=all correct]: ").strip()
            if not raw:
                return {p: sorted(CORRECT_PROCESSES[set_label].get(p,[]))
                        for p in pids}
            procs = {p: sorted(CORRECT_PROCESSES[set_label].get(p,[]))
                     for p in pids}
            for part in raw.split():
                if ':' in part:
                    pid, ids_str = part.split(':', 1)
                    pid = pid.upper()
                    if pid in pids:
                        try:
                            ids = [int(x) for x in ids_str.split(',') if x]
                            procs[pid] = sorted(ids)
                        except ValueError:
                            pass
            return procs

        procs = get_procs()
        engine._process_state = procs

        while engine.phase not in (Phase.ITERATION_COMPLETE,):
            while True:
                cmd = input("\n  [V]=validate  [Q]=question: ").strip().lower()
                if cmd == 'q':
                    ask_question(engine)
                elif cmd == 'v':
                    break
            engine.trigger_evaluation()
            show(engine.update({}, [], procs))
            if engine.phase == Phase.PROCESS_CORRECTION:
                print("\n  Update processes (Enter=all correct):")
                procs = get_procs()
                engine._process_state = procs

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set",  default="A", choices=["A","B"])
    parser.add_argument("--mode", default="error_based",
                        choices=["guided_learning","error_based","silent"])
    parser.add_argument("--lang", default="en", choices=["en","es"])
    args = parser.parse_args()

    hdr(f"TRIAGE SIMULATOR — Set {args.set} | "
        f"{args.mode.upper()} | {args.lang.upper()}")
    print("  Q = ask question at any prompt")
    print("  V = validate (error_based)")
    print("  Enter = use correct answer")

    engine = GameEngine(set_label=args.set, mode=args.mode,
                        language=args.lang)

    while True:
        sec("SELECT ITERATION")
        iteration = None
        while iteration not in (1,2,3):
            try:
                val = input("  Iteration (1-3) or 0 to quit: ").strip()
                if val == "0":
                    print("\n  Session log:")
                    for e in engine.get_session_log():
                        print(f"    {e}")
                    engine.save_session_log(f"sim_{args.set}_{args.mode}.json")
                    sys.exit(0)
                iteration = int(val)
            except ValueError:
                pass

        pids = ITERATIONS[args.set][iteration]
        show(engine.start_iteration(iteration))
        patient_ref(args.set, pids)

        if input("\n  Show correct answers? (y/n): ").strip().lower() == 'y':
            correct_answer(args.set, iteration)

        if args.mode == "guided_learning":
            run_guided(engine, args.set, iteration)
        else:
            run_error_based_selection(engine, args.set, iteration)

        run_process_phase(engine, args.set, iteration, args.mode)

        if not input("\n  Another iteration? (y/n): ").strip().lower().startswith('y'):
            break

    print("\n  Session log:")
    for e in engine.get_session_log():
        print(f"    {e}")
    engine.save_session_log(f"sim_{args.set}_{args.mode}.json")
    print("  Done.")

if __name__ == "__main__":
    main()
