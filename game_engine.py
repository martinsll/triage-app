# -*- coding: utf-8 -*-
"""
Triage Game — Game Logic Engine (v4)
=====================================
Two learning modes:
  guided_learning  — robot guides one slot at a time, auto-advances on correct
  error_based      — participant places all 5, says "validate", robot corrects

Phases:
  IDLE
  INTRO
  CARD_SCAN             (guided only: wait for any card visible)
  SLOT_GUIDANCE         (guided only: explaining current target slot)
  SLOT_WAIT             (guided only: waiting for correct card in slot)
  PLACEMENT             (error_based: participant places freely)
  VALIDATE_WAIT         (error_based: waiting for validate trigger)
  SELECTION_CORRECTION
  DEST_INTRO
  DEST_GUIDANCE         (guided only: explaining destination per patient)
  DEST_WAIT             (guided only: waiting for correct destination card)
  DEST_PLACING          (error_based: participant places destination cards)
  DEST_VALIDATE         (error_based: waiting for validate trigger)
  DEST_CORRECTION
  ITERATION_COMPLETE
"""

import time, json
from enum import Enum, auto
from dataclasses import dataclass, field, asdict
from typing import Optional


# ─── GAME DATA ────────────────────────────────────────────────────────────────
# Import from design_patients
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rules_engine import (
    PID_TO_PATIENT, CORRECT_ORDERS,
    validate_selection, validate_destinations,
    correct_destination_for,
    get_group_patients,
)
from design_patients import derive_risk

# Build ArUco → PID mapping and iteration order from rules_engine data
def _build_aruco_db():
    aruco_to_pid = {}
    for set_label in ("A", "B"):
        base = 10 if set_label == "A" else 40
        for (sl, pid) in PID_TO_PATIENT:
            if sl == set_label:
                pid_idx = int(pid[1:]) - 1
                aruco_to_pid[base + pid_idx] = (set_label, pid)
    return aruco_to_pid

ARUCO_TO_PID = _build_aruco_db()
ITERATIONS   = CORRECT_ORDERS  # same structure: {set: {group: [pids]}}

DEST_NAMES = {
    50: "Surgical Bay",
    51: "Risk Ward",
    52: "Monitored Ward",
    53: "General Ward",
}

# CORRECT_PROCESSES and CORRECT_DESTINATIONS now come from rules_engine

# ─── PHASES ───────────────────────────────────────────────────────────────────
class Phase(Enum):
    IDLE                = auto()
    INTRO               = auto()
    CARD_SCAN           = auto()
    SLOT_GUIDANCE       = auto()
    SLOT_WAIT           = auto()
    PLACEMENT           = auto()
    VALIDATE_WAIT       = auto()
    SELECTION_CORRECTION= auto()
    DEST_INTRO          = auto()
    DEST_GUIDANCE       = auto()
    DEST_WAIT           = auto()
    DEST_PLACING        = auto()
    DEST_VALIDATE       = auto()
    DEST_CORRECTION     = auto()
    ITERATION_COMPLETE  = auto()

class RobotMode(Enum):
    GUIDED_LEARNING = "guided_learning"
    ERROR_BASED     = "error_based"
    SILENT          = "silent"

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class AttemptLog:
    attempt:   int
    board:     dict
    errors:    list
    score:     str
    timestamp: float = field(default_factory=time.time)

@dataclass
class PhaseLog:
    phase:           str
    attempts:        list = field(default_factory=list)
    questions_asked: int  = 0
    final_score:     str  = ""

@dataclass
class IterationResult:
    set_label:    str
    iteration:    int
    mode:         str
    selection:    PhaseLog = field(default_factory=lambda: PhaseLog("selection"))
    destinations: PhaseLog = field(default_factory=lambda: PhaseLog("destinations"))
    timestamp:    float    = field(default_factory=time.time)

    def summary(self):
        def ps(pl):
            return {"attempts": len(pl.attempts),
                    "questions_asked": pl.questions_asked,
                    "final_score": pl.final_score,
                    "first_score": pl.attempts[0].score if pl.attempts else "—"}
        return {"set": self.set_label, "iteration": self.iteration,
                "mode": self.mode,
                "selection":    ps(self.selection),
                "destinations": ps(self.destinations)}

# ─── GAME ENGINE ──────────────────────────────────────────────────────────────
class GameEngine:
    def __init__(self, set_label: str, mode: str = "error_based",
                 language: str = "en"):
        assert set_label in ("A","B")
        assert mode in ("guided_learning","error_based","silent")
        assert language in ("en","es")

        self.set_label = set_label
        self.mode      = RobotMode(mode)
        self.language  = language
        self.phase     = Phase.IDLE
        self.iteration = 0
        self.current_pids   = []   # correct order for this iteration
        self.current_slot   = 0    # guided: which slot we are targeting (1-5)
        self.result         = None

        self._actions_queue  = []
        self._session_log    = []
        self._board_state    = {}
        self._dest_state    = {}
        self._eval_triggered = False
        self._attempt_count  = 0

        # No LLM — fully rules-based

    def set_language(self, language: str):
        self.language = language

    # ─── PUBLIC API ───────────────────────────────────────────────────────────
    def start_iteration(self, iteration: int):
        assert 1 <= iteration <= 3
        self.iteration    = iteration
        self.current_pids = ITERATIONS[self.set_label][iteration]
        self.current_slot = 0
        self.result       = IterationResult(
            set_label=self.set_label,
            iteration=iteration,
            mode=self.mode.value,
        )
        self._board_state    = {}
        self._dest_state    = {}
        self._eval_triggered = False
        self._attempt_count  = 0
        self._actions_queue  = []
        self._last_slot_card = {}   # {slot: last_pid_seen} — prevents repeated corrections

        print(f"\n[ENGINE] Set {self.set_label} | Iter {iteration} | "
              f"Mode: {self.mode.value}")
        print(f"[ENGINE] Correct order: {self.current_pids}")

        self.phase = Phase.INTRO
        text = self._fb_intro(iteration)
        self._queue({"type":"speak", "text":text})
        self._queue({"type":"state_change", "phase":"INTRO"})

        if self.mode == RobotMode.GUIDED_LEARNING:
            self.phase = Phase.CARD_SCAN
            self._queue({"type":"state_change", "phase":"CARD_SCAN"})
        else:
            self.phase = Phase.PLACEMENT
            self._queue({"type":"state_change", "phase":"PLACEMENT"})

        return self._flush_actions()

    def update(self, board_state: dict, all_visible_ids: list,
               process_state: dict):
        """Call every frame with latest detection results."""
        self._board_state   = board_state
        self._dest_state    = process_state

        # ── GUIDED: card scan ─────────────────────────────────────────────
        if self.phase == Phase.CARD_SCAN:
            detected = self._ids_to_pids(all_visible_ids)
            if any(p in self.current_pids for p in detected):
                self.current_slot = 1
                self._announce_slot(1)
                self.phase = Phase.SLOT_WAIT
                self._queue({"type":"state_change","phase":"SLOT_WAIT"})

        # ── GUIDED: waiting for correct card in current slot ──────────────
        elif self.phase == Phase.SLOT_WAIT:
            target_pid     = self.current_pids[self.current_slot - 1]
            placed_in_slot = board_state.get(self.current_slot)

            # Only react when the card in this slot has changed
            last_seen = self._last_slot_card.get(self.current_slot)
            if placed_in_slot != last_seen:
                self._last_slot_card[self.current_slot] = placed_in_slot

                if placed_in_slot == target_pid:
                    # Correct — auto advance
                    if self.current_slot == 5:
                        self._complete_selection()
                    else:
                        self.current_slot += 1
                        self._announce_slot(self.current_slot)

                elif placed_in_slot and placed_in_slot != target_pid:
                    # Wrong card placed — correct once, then wait for change
                    self._correct_wrong_slot(
                        self.current_slot, placed_in_slot, target_pid)

        # ── ERROR_BASED: waiting for validate trigger ─────────────────────
        elif self.phase in (Phase.VALIDATE_WAIT,
                            Phase.SELECTION_CORRECTION):
            if self._eval_triggered:
                self._eval_triggered = False
                self._do_evaluate_selection()

        # ── After selection: destination phase ───────────────────────────
        elif self.phase == Phase.DEST_INTRO:
            pass  # handled in transition

        # ── GUIDED: destination phase ─────────────────────────────────────
        elif self.phase == Phase.DEST_WAIT:
            target_pid = self.current_pids[self.current_slot - 1]
            expected   = correct_destination_for(self.set_label, target_pid)
            placed_ids = self._dest_state.get(target_pid, [])
            placed     = DEST_NAMES.get(placed_ids[0]) if placed_ids else None

            last_seen = self._last_slot_card.get(f"dest_{self.current_slot}")
            if placed != last_seen:
                self._last_slot_card[f"dest_{self.current_slot}"] = placed
                if placed == expected:
                    if self.current_slot == 5:
                        self._complete_destinations()
                    else:
                        self.current_slot += 1
                        self._announce_dest_slot(self.current_slot)

        # ── ERROR_BASED: destination validate ────────────────────────────
        elif self.phase in (Phase.DEST_VALIDATE,
                            Phase.DEST_CORRECTION):
            if self._eval_triggered:
                self._eval_triggered = False
                self._do_evaluate_destinations()

        return self._flush_actions()

    def trigger_evaluation(self):
        """Called when participant says 'validate' (error_based) or 'ready'."""
        if self.phase == Phase.PLACEMENT:
            self.phase = Phase.VALIDATE_WAIT
        if self.phase == Phase.DEST_PLACING:
            self.phase = Phase.DEST_VALIDATE
        if self.phase in (Phase.VALIDATE_WAIT,
                          Phase.SELECTION_CORRECTION,
                          Phase.DEST_VALIDATE,
                          Phase.DEST_CORRECTION):
            self._eval_triggered = True
            print(f"[ENGINE] Validate triggered — phase: {self.phase.name}")
        else:
            print(f"[ENGINE] Validate ignored — phase: {self.phase.name}")

    def ask_question(self, question: str):
        """Participant asks a question — answered with fixed fallback text."""
        # Log question
        if self.result:
            pl = (self.result.destinations
                  if self.phase in (Phase.DEST_INTRO, Phase.DEST_GUIDANCE,
                                    Phase.DEST_WAIT, Phase.DEST_PLACING,
                                    Phase.DEST_VALIDATE,
                                    Phase.DEST_CORRECTION)
                  else self.result.selection)
            pl.questions_asked += 1

        text = self._fb_question_answer()

        self._queue({"type":"speak", "text":text})
        return self._flush_actions()

    def get_session_log(self):
        return [r.summary() for r in self._session_log]

    def save_session_log(self, path: str):
        data = [{"set":r.set_label,"iteration":r.iteration,
                 "mode":r.mode,"timestamp":r.timestamp,
                 "summary":r.summary()} for r in self._session_log]
        with open(path,'w') as f:
            json.dump(data, f, indent=2)
        print(f"[ENGINE] Saved {path}")

    # ─── GUIDED SLOT ANNOUNCEMENTS ────────────────────────────────────────────
    def _announce_slot(self, slot_num: int):
        target_pid = self.current_pids[slot_num - 1]
        patient    = PID_TO_PATIENT[(self.set_label, target_pid)]
        expl_key   = f"explanation_{self.language}"
        expl       = patient.get(expl_key, patient.get(expl_key,""))

        text = (f"Slot {slot_num}: place {target_pid} {patient['name']}. "
                f"{expl}")
        self._queue({"type":"speak","text":text})
        self._queue({"type":"slot_target",
                     "slot":slot_num, "pid":target_pid})

    def _correct_wrong_slot(self, slot_num: int,
                            placed_pid: str, target_pid: str):
        """Guided: wrong card placed — correct using explanation as context."""
        patient    = PID_TO_PATIENT[(self.set_label, target_pid)]
        expl_key   = f"explanation_{self.language}"
        expl       = patient.get(expl_key, patient.get(expl_key,""))
        placed_pt  = PID_TO_PATIENT.get((self.set_label, placed_pid), {})

        text = (f"Slot {slot_num} should be {target_pid} {patient['name']}, "
                f"not {placed_pid}. {expl}")
        self._queue({"type":"speak","text":text})

    def _announce_dest_slot(self, slot_num: int):
        """Guided: announce which destination card to place for current patient."""
        target_pid = self.current_pids[slot_num - 1]
        patient    = PID_TO_PATIENT[(self.set_label, target_pid)]
        dest       = correct_destination_for(self.set_label, target_pid)
        expl_key   = f"exp_destination_{self.language}"
        expl       = patient.get(expl_key, patient.get("explanation_en",""))
        text = (f"For slot {slot_num}, {target_pid} {patient['name']}: "
                f"place {dest}. {expl}")
        self._queue({"type":"speak","text":text})
        self._queue({"type":"dest_target",
                     "slot":slot_num,"pid":target_pid,"destination":dest})

    # ─── EVALUATION ───────────────────────────────────────────────────────────
    def _do_evaluate_selection(self):
        expected = self.current_pids
        errors   = []
        score    = 0
        for slot in range(1,6):
            placed  = self._board_state.get(slot)
            exp_pid = expected[slot-1]
            if placed == exp_pid:
                score += 1
            else:
                errors.append((slot, placed, exp_pid))

        self._attempt_count += 1
        self.result.selection.attempts.append(AttemptLog(
            attempt=self._attempt_count,
            board=dict(self._board_state),
            errors=errors, score=f"{score}/5"))
        print(f"\n[ENGINE] Selection attempt {self._attempt_count}: {score}/5")

        if score == 5:
            self.result.selection.final_score = "5/5"
            text = self._fb_correct("selection")
            self._queue({"type":"speak","text":text})
            self._queue({"type":"log","phase":"selection",
                         "score":"5/5","attempt":self._attempt_count})
            self._transition_to_dest()
        else:
            pdata   = self._build_patient_data_dict(self.current_pids)
            context = self._build_explanation_context()
            text = self._fb_selection_correction(errors, expected)
            self._queue({"type":"speak","text":text})
            self._queue({"type": "speak", "text": context})  # Add context explanation
            self._queue({"type":"log","phase":"selection",
                         "score":f"{score}/5",
                         "attempt":self._attempt_count,"errors":errors})
            self._queue({"type":"listen"}) # Listen after correction to validate again
            self.phase = Phase.SELECTION_CORRECTION

    def _do_evaluate_destinations(self):
        errors = []; score = 0
        for pid in self.current_pids:
            placed_ids = self._dest_state.get(pid, [])
            placed     = DEST_NAMES.get(placed_ids[0]) if placed_ids else None
            expected   = correct_destination_for(self.set_label, pid)
            if placed == expected:
                score += 1
            else:
                errors.append((pid, placed, expected))

        self._attempt_count += 1
        self.result.destinations.attempts.append(AttemptLog(
            attempt=self._attempt_count,
            board={p: self._dest_state.get(p,[])
                   for p in self.current_pids},
            errors=errors, score=f"{score}/5"))
        print(f"[ENGINE] Destination attempt {self._attempt_count}: {score}/5")

        if score == 5:
            self.result.destinations.final_score = "5/5"
            text = self._fb_correct("destinations")
            self._queue({"type":"speak","text":text})
            self._queue({"type":"log","phase":"destinations",
                         "score":"5/5","attempt":self._attempt_count})
            self._finish_iteration()
        else:
            text = self._fb_dest_correction(errors)
            self._queue({"type":"speak","text":text})
            self._queue({"type":"log","phase":"destinations",
                         "score":f"{score}/5",
                         "attempt":self._attempt_count,"errors":errors})
            self._queue({"type":"listen"})
            self.phase = Phase.DEST_CORRECTION

    def _complete_selection(self):
        """Guided: all 5 slots correctly filled."""
        self.result.selection.final_score = "5/5"
        self.result.selection.attempts.append(AttemptLog(
            attempt=1, board=dict(self._board_state),
            errors=[], score="5/5"))
        text = self._fb_correct("selection")
        self._queue({"type":"speak","text":text})
        self._queue({"type":"log","phase":"selection","score":"5/5"})
        self._transition_to_dest()

    def _complete_destinations(self):
        """Guided: all destination cards correctly placed."""
        self.result.destinations.final_score = "5/5"
        self.result.destinations.attempts.append(AttemptLog(
            attempt=1,
            board={p: self._dest_state.get(p,[])
                   for p in self.current_pids},
            errors=[], score="5/5"))
        text = self._fb_correct("destinations")
        self._queue({"type":"speak","text":text})
        self._finish_iteration()

    # ─── PHASE TRANSITIONS ────────────────────────────────────────────────────
    def _transition_to_dest(self):
        self._attempt_count  = 0
        self.current_slot    = 1
        self._last_slot_card = {}
        self.phase = Phase.DEST_INTRO
        text = self._fb_dest_intro()
        self._queue({"type":"speak","text":text})
        self._queue({"type":"state_change","phase":"DEST_INTRO"})

        if self.mode == RobotMode.GUIDED_LEARNING:
            self._announce_dest_slot(1)
            self.phase = Phase.DEST_WAIT
            self._queue({"type":"state_change","phase":"DEST_WAIT"})
        else:
            self.phase = Phase.DEST_PLACING
            self._queue({"type":"state_change","phase":"DEST_PLACING"})

    def _finish_iteration(self):
        self._session_log.append(self.result)
        self.phase = Phase.ITERATION_COMPLETE
        self._queue({"type":"end_iteration","summary":self.result.summary()})
        print(f"\n[ENGINE] Iteration {self.iteration} complete")

    # ─── CONTEXT BUILDERS ─────────────────────────────────────────────────────
    def _build_explanation_context(self) -> str:
        """All explanation texts for current group."""
        lines = ["Patient explanations for this group:"]
        for pid in self.current_pids:
            p = PID_TO_PATIENT[(self.set_label, pid)]
            expl = p.get(f"explanation_{self.language}",
                         p.get("explanation_en",""))
            lines.append(f"  {pid} {p['name']}: {expl}")
        return "\n".join(lines)

    def _build_patient_data_dict(self, pids):
        result = {}
        for pid in pids:
            p = PID_TO_PATIENT.get((self.set_label, pid), {})
            result[pid] = {"condition": p.get("condition",""),
                           "name":      p.get("name","")}
        return result

    def _ids_to_pids(self, aruco_ids):
        pids = []
        for aid in aruco_ids:
            if aid in ARUCO_TO_PID:
                s, pid = ARUCO_TO_PID[aid]
                if s == self.set_label:
                    pids.append(pid)
        return pids

    # ─── FALLBACK TEXT ────────────────────────────────────────────────────────
    def _fb_intro(self, iteration):
        if iteration == 1:
            if self.mode == RobotMode.GUIDED_LEARNING:
                return ("Hello, I am TRIA. I will guide you through each "
                        "patient. Show me your cards to begin.")
            else:
                return ("Hello, I am TRIA. Arrange the five patients in "
                        "triage order, then say validate.")
        else:
            if self.mode == RobotMode.GUIDED_LEARNING:
                return "Next group. Show me your cards."
            else:
                return "Next group. Arrange and say validate when ready."

    def _fb_correct(self, phase):
        if phase == "selection":
            return "Correct order."
        return "All destinations correct."

    def _fb_selection_correction(self, errors, expected):
        parts = [f"slot {s}: expected {e}, got {p or 'empty'}"
                 for s,p,e in errors]
        order = ", ".join(f"slot {i+1}:{p}"
                          for i,p in enumerate(expected))
        return (f"Errors: {'; '.join(parts)}. "
                f"Correct order: {order}.")

    def _fb_dest_intro(self):
        return ("Place the destination card below each patient card. "
                "Say validate when done."
                if self.mode == RobotMode.ERROR_BASED
                else "Now I will guide you through the destination cards.")

    def _fb_dest_correction(self, errors):
        parts = []
        for pid, placed, expected in errors:
            p = PID_TO_PATIENT[(self.set_label, pid)]
            expl_key = f"exp_destination_{self.language}"
            expl = p.get(expl_key, p.get("explanation_en",""))
            msg = f"{pid} {p['name']}: place {expected}"
            if placed:
                msg += f", not {placed}"
            msg += f". {expl}"
            parts.append(msg)
        return " ".join(parts)

    def _fb_question_answer(self):
        if self.mode == RobotMode.ERROR_BASED:
            return ("Please check the printed rules."
                    if self.language=="en"
                    else "Por favor consulta las reglas impresas.")
        return ("Check the triage rules for guidance."
                if self.language=="en"
                else "Consulta las reglas de triaje.")

    def _queue(self, action):
        action['timestamp'] = time.time()
        self._actions_queue.append(action)

    def _flush_actions(self):
        actions = list(self._actions_queue)
        self._actions_queue.clear()
        return actions
