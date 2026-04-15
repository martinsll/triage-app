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
  CARD_SCAN           (guided only: wait for any card visible)
  SLOT_GUIDANCE       (guided only: explaining current target slot)
  SLOT_WAIT           (guided only: waiting for correct card in slot)
  PLACEMENT           (error_based: participant places freely)
  VALIDATE_WAIT       (error_based: waiting for validate trigger)
  SELECTION_CORRECTION
  PROCESS_INTRO
  PROCESS_GUIDANCE    (guided only: explaining process per patient)
  PROCESS_WAIT        (guided only: waiting for correct process)
  PROCESS_PLACING     (error_based: participant attaches processes)
  PROCESS_VALIDATE    (error_based: waiting for validate trigger)
  PROCESS_CORRECTION
  DESTINATION_PHASE   (deferred)
  ITERATION_COMPLETE
"""

import time, json
from enum import Enum, auto
from dataclasses import dataclass, field, asdict
from typing import Optional

try:
    from triage_agent import TriageAgent as LLMClient
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    print("[ENGINE] No LLM module — using fallback text.")

# ─── GAME DATA ────────────────────────────────────────────────────────────────
# Import from design_patients
import sys
sys.path.insert(0, '/home/claude')
from design_patients import (
    PATIENTS_A, PATIENTS_B,
    derive_risk, derive_processes, derive_destination, sort_key
)

def _build_db():
    """Build lookup dicts from patient lists."""
    pid_to_patient = {}   # (set, pid) → patient dict
    aruco_to_pid   = {}   # aruco_id → (set, pid)
    iterations     = {"A":{}, "B":{}}
    for set_label, patients in [("A", PATIENTS_A), ("B", PATIENTS_B)]:
        base = 10 if set_label == "A" else 40
        groups = {}
        for p in patients:
            pid_idx = int(p['pid'][1:]) - 1
            aruco_id = base + pid_idx
            aruco_to_pid[aruco_id] = (set_label, p['pid'])
            pid_to_patient[(set_label, p['pid'])] = p
            groups.setdefault(p['group'], []).append(p)
        for grp_num, grp_patients in groups.items():
            ordered = sorted(grp_patients, key=sort_key)
            iterations[set_label][grp_num] = [p['pid'] for p in ordered]
    return pid_to_patient, aruco_to_pid, iterations

PID_TO_PATIENT, ARUCO_TO_PID, ITERATIONS = _build_db()

PROCESS_NAMES = {
    50: "Call Rapid Response",
    51: "Request Stretcher",
    52: "Direct Companion to Waiting Bay",
    53: "Request Interpreter/Support",
}

CORRECT_PROCESSES = {}
CORRECT_DESTINATIONS = {}
for set_label, patients in [("A", PATIENTS_A), ("B", PATIENTS_B)]:
    CORRECT_PROCESSES[set_label] = {}
    CORRECT_DESTINATIONS[set_label] = {}
    for p in patients:
        risk = derive_risk(p)
        CORRECT_PROCESSES[set_label][p['pid']] = derive_processes(p, risk)
        CORRECT_DESTINATIONS[set_label][p['pid']] = derive_destination(p, risk)

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
    PROCESS_INTRO       = auto()
    PROCESS_GUIDANCE    = auto()
    PROCESS_WAIT        = auto()
    PROCESS_PLACING     = auto()
    PROCESS_VALIDATE    = auto()
    PROCESS_CORRECTION  = auto()
    DESTINATION_PHASE   = auto()
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
    processes:    PhaseLog = field(default_factory=lambda: PhaseLog("processes"))
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
                "processes":    ps(self.processes),
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
        self._process_state  = {}
        self._eval_triggered = False
        self._attempt_count  = 0

        self.llm = None
        if LLM_AVAILABLE and mode != "silent":
            self.llm = LLMClient(mode=mode, language=language)

    def set_language(self, language: str):
        self.language = language
        if self.llm:
            self.llm.set_language(language)

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
        self._process_state  = {}
        self._eval_triggered = False
        self._attempt_count  = 0
        self._actions_queue  = []
        self._last_slot_card = {}   # {slot: last_pid_seen} — prevents repeated corrections

        print(f"\n[ENGINE] Set {self.set_label} | Iter {iteration} | "
              f"Mode: {self.mode.value}")
        print(f"[ENGINE] Correct order: {self.current_pids}")

        self.phase = Phase.INTRO
        text = (self.llm.introduction(iteration, self.mode.value,
                                      self.set_label)
                if self.llm else self._fb_intro(iteration))
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
        self._process_state = process_state

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

        # ── After selection: process phase ────────────────────────────────
        elif self.phase == Phase.PROCESS_INTRO:
            pass  # handled in transition

        # ── GUIDED: process phase ─────────────────────────────────────────
        elif self.phase == Phase.PROCESS_WAIT:
            target_pid = self.current_pids[self.current_slot - 1]
            expected   = sorted(CORRECT_PROCESSES[self.set_label].get(
                target_pid, []))
            placed     = sorted(process_state.get(target_pid, []))

            # Only react when process cards on this patient have changed
            last_seen = self._last_slot_card.get(f"proc_{self.current_slot}")
            if placed != last_seen:
                self._last_slot_card[f"proc_{self.current_slot}"] = placed
                if placed == expected:
                    if self.current_slot == 5:
                        self._complete_processes()
                    else:
                        self.current_slot += 1
                        self._announce_process_slot(self.current_slot)

        # ── ERROR_BASED: process validate ─────────────────────────────────
        elif self.phase in (Phase.PROCESS_VALIDATE,
                            Phase.PROCESS_CORRECTION):
            if self._eval_triggered:
                self._eval_triggered = False
                self._do_evaluate_processes()

        return self._flush_actions()

    def trigger_evaluation(self):
        """Called when participant says 'validate' (error_based) or 'ready'."""
        if self.phase == Phase.PLACEMENT:
            self.phase = Phase.VALIDATE_WAIT
        if self.phase == Phase.PROCESS_PLACING:
            self.phase = Phase.PROCESS_VALIDATE
        if self.phase in (Phase.VALIDATE_WAIT,
                          Phase.SELECTION_CORRECTION,
                          Phase.PROCESS_VALIDATE,
                          Phase.PROCESS_CORRECTION):
            self._eval_triggered = True
            print(f"[ENGINE] Validate triggered — phase: {self.phase.name}")
        else:
            print(f"[ENGINE] Validate ignored — phase: {self.phase.name}")

    def ask_question(self, question: str):
        """Participant asks a question — answered by LLM with context."""
        # Log question
        if self.result:
            pl = (self.result.processes
                  if self.phase in (Phase.PROCESS_INTRO, Phase.PROCESS_GUIDANCE,
                                    Phase.PROCESS_WAIT, Phase.PROCESS_PLACING,
                                    Phase.PROCESS_VALIDATE,
                                    Phase.PROCESS_CORRECTION)
                  else self.result.selection)
            pl.questions_asked += 1

        if self.llm:
            # Build explanation context for current group
            context = self._build_explanation_context()
            text = self.llm.answer_question(
                question=question,
                phase=self.phase.name,
                mode=self.mode.value,
                iteration=self.iteration,
                explanation_context=context,
            )
        else:
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
        expl       = patient.get(expl_key, patient.get("explanation_en",""))

        if self.llm:
            text = self.llm.announce_slot(
                slot_num=slot_num,
                pid=target_pid,
                patient_name=patient['name'],
                explanation=expl,
                language=self.language,
            )
        else:
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
        expl       = patient.get(expl_key, patient.get("explanation_en",""))
        placed_pt  = PID_TO_PATIENT.get((self.set_label, placed_pid), {})

        if self.llm:
            text = self.llm.correct_wrong_slot(
                slot_num=slot_num,
                placed_pid=placed_pid,
                placed_name=placed_pt.get('name', placed_pid),
                target_pid=target_pid,
                target_name=patient['name'],
                explanation=expl,
                language=self.language,
            )
        else:
            text = (f"Slot {slot_num} should be {target_pid} {patient['name']}, "
                    f"not {placed_pid}. {expl}")
        self._queue({"type":"speak","text":text})

    def _announce_process_slot(self, slot_num: int):
        """Guided: announce which processes to attach for current patient."""
        target_pid = self.current_pids[slot_num - 1]
        patient    = PID_TO_PATIENT[(self.set_label, target_pid)]
        risk       = derive_risk(patient)
        procs      = CORRECT_PROCESSES[self.set_label].get(target_pid, [])
        proc_names = [PROCESS_NAMES[p] for p in procs]

        if self.llm:
            text = self.llm.announce_process(
                slot_num=slot_num,
                pid=target_pid,
                patient_name=patient['name'],
                processes=proc_names,
                language=self.language,
            )
        else:
            if proc_names:
                text = (f"For slot {slot_num}, {target_pid} {patient['name']}: "
                        f"attach {', '.join(proc_names)}.")
            else:
                text = (f"For slot {slot_num}, {target_pid} {patient['name']}: "
                        f"no additional processes needed.")
        self._queue({"type":"speak","text":text})
        self._queue({"type":"process_target",
                     "slot":slot_num,"pid":target_pid,"processes":procs})

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
            text = (self.llm.phase_correct("selection", self.iteration,
                                           "processes")
                    if self.llm else self._fb_correct("selection"))
            self._queue({"type":"speak","text":text})
            self._queue({"type":"log","phase":"selection",
                         "score":"5/5","attempt":self._attempt_count})
            self._transition_to_process()
        else:
            pdata   = self._build_patient_data_dict(self.current_pids)
            context = self._build_explanation_context()
            text    = (self.llm.selection_correction(
                           errors, expected, pdata,
                           attempt_num=self._attempt_count,
                           explanation_context=context)
                       if self.llm
                       else self._fb_selection_correction(errors, expected))
            self._queue({"type":"speak","text":text})
            self._queue({"type":"log","phase":"selection",
                         "score":f"{score}/5",
                         "attempt":self._attempt_count,"errors":errors})
            self.phase = Phase.SELECTION_CORRECTION

    def _do_evaluate_processes(self):
        errors = []; score = 0
        for pid in self.current_pids:
            placed   = sorted(self._process_state.get(pid,[]))
            expected = sorted(CORRECT_PROCESSES[self.set_label].get(pid,[]))
            if placed == expected:
                score += 1
            else:
                errors.append((pid, placed, expected))

        self._attempt_count += 1
        self.result.processes.attempts.append(AttemptLog(
            attempt=self._attempt_count,
            board={p: self._process_state.get(p,[])
                   for p in self.current_pids},
            errors=errors, score=f"{score}/5"))
        print(f"[ENGINE] Process attempt {self._attempt_count}: {score}/5")

        if score == 5:
            self.result.processes.final_score = "5/5"
            text = (self.llm.phase_correct("processes", self.iteration,
                                           "next_iteration")
                    if self.llm else self._fb_correct("processes"))
            self._queue({"type":"speak","text":text})
            self._queue({"type":"log","phase":"processes",
                         "score":"5/5","attempt":self._attempt_count})
            self._finish_iteration()
        else:
            pdata   = self._build_patient_data_dict(self.current_pids)
            context = self._build_explanation_context()
            text    = (self.llm.process_correction(
                           errors, pdata,
                           attempt_num=self._attempt_count,
                           explanation_context=context)
                       if self.llm
                       else self._fb_process_correction(errors))
            self._queue({"type":"speak","text":text})
            self._queue({"type":"log","phase":"processes",
                         "score":f"{score}/5",
                         "attempt":self._attempt_count,"errors":errors})
            self.phase = Phase.PROCESS_CORRECTION

    def _complete_selection(self):
        """Guided: all 5 slots correctly filled."""
        self.result.selection.final_score = "5/5"
        self.result.selection.attempts.append(AttemptLog(
            attempt=1, board=dict(self._board_state),
            errors=[], score="5/5"))
        text = (self.llm.phase_correct("selection", self.iteration,
                                       "processes")
                if self.llm else self._fb_correct("selection"))
        self._queue({"type":"speak","text":text})
        self._queue({"type":"log","phase":"selection","score":"5/5"})
        self._transition_to_process()

    def _complete_processes(self):
        """Guided: all processes correctly attached."""
        self.result.processes.final_score = "5/5"
        self.result.processes.attempts.append(AttemptLog(
            attempt=1,
            board={p: self._process_state.get(p,[])
                   for p in self.current_pids},
            errors=[], score="5/5"))
        text = (self.llm.phase_correct("processes", self.iteration,
                                       "next_iteration")
                if self.llm else self._fb_correct("processes"))
        self._queue({"type":"speak","text":text})
        self._finish_iteration()

    # ─── PHASE TRANSITIONS ────────────────────────────────────────────────────
    def _transition_to_process(self):
        self._attempt_count  = 0
        self.current_slot    = 1
        self._last_slot_card = {}   # reset for process phase tracking
        self.phase = Phase.PROCESS_INTRO
        text = (self.llm.process_intro(self.iteration)
                if self.llm else self._fb_process_intro())
        self._queue({"type":"speak","text":text})
        self._queue({"type":"state_change","phase":"PROCESS_INTRO"})

        if self.mode == RobotMode.GUIDED_LEARNING:
            self._announce_process_slot(1)
            self.phase = Phase.PROCESS_WAIT
            self._queue({"type":"state_change","phase":"PROCESS_WAIT"})
        else:
            self.phase = Phase.PROCESS_PLACING
            self._queue({"type":"state_change","phase":"PROCESS_PLACING"})

    def _finish_iteration(self):
        if self.llm and hasattr(self.llm,'end_iteration'):
            self.llm.end_iteration(self.iteration, self.result.summary())
        self._session_log.append(self.result)
        self.phase = Phase.ITERATION_COMPLETE
        self._queue({"type":"end_iteration","summary":self.result.summary()})
        print(f"\n[ENGINE] Iteration {self.iteration} complete")

    # ─── CONTEXT BUILDERS ─────────────────────────────────────────────────────
    def _build_explanation_context(self) -> str:
        """All explanation texts for current group — injected into LLM."""
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
            return "Correct order. Now attach process cards to each patient."
        return "All processes correct."

    def _fb_selection_correction(self, errors, expected):
        parts = [f"slot {s}: expected {e}, got {p or 'empty'}"
                 for s,p,e in errors]
        order = ", ".join(f"slot {i+1}:{p}"
                          for i,p in enumerate(expected))
        return (f"Errors: {'; '.join(parts)}. "
                f"Correct order: {order}.")

    def _fb_process_intro(self):
        return ("Attach the additional process cards to each patient card. "
                "Say validate when done."
                if self.mode == RobotMode.ERROR_BASED
                else "Now I will guide you through the process cards.")

    def _fb_process_correction(self, errors):
        parts = []
        for pid,placed,expected in errors:
            missing=[PROCESS_NAMES[i] for i in expected if i not in placed]
            extra  =[PROCESS_NAMES[i] for i in placed  if i not in expected]
            msg=f"{pid}:"
            if missing: msg+=f" add {', '.join(missing)}"
            if extra:   msg+=f" remove {', '.join(extra)}"
            parts.append(msg)
        return f"Process errors: {' '.join(parts)}."

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
