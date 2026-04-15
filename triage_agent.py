# -*- coding: utf-8 -*-
"""
Triage Game — Conversational Agent (v3)
========================================
Modes: guided_learning | error_based
New methods: announce_slot, correct_wrong_slot, announce_process
All methods receive explanation_context where relevant.
"""

import os

RULES = """
TRIAGE RULES (use ONLY these — no external medical knowledge):

VITAL THRESHOLDS:
  HR: Normal 60-100 | High 101-130 | Critical >130 or <40 bpm
  BP: Normal 90-140 | High >140 | Low <90 mmHg
  SpO2: Normal ≥94% | Low 90-93% | Critical <90%
  RR: Normal 12-20 | High 21-30 | Critical >30 or <10 /min
  Temp: Normal 36-37.5 | High 37.6-39 | Critical >39 or <35 °C
  Alertness: Alert | Confused | Lethargic

RISK DERIVATION:
  Cardiac:      Critical if HR Critical OR (HR High AND BP Low). Moderate if HR High OR BP High/Low.
  Pulmonary:    Critical if SpO2 Critical OR (SpO2 Low AND RR Critical). Moderate if SpO2 Low OR RR High.
  Neurological: Critical if Lethargic. Moderate if Confused OR BP High.
  Trauma:       Critical if HR High AND Non-Ambulatory. Moderate if HR High OR Non-Ambulatory (not both).
  Infectious:   Critical if Temp Critical AND HR High. Moderate if Temp High OR (Temp Critical AND HR Normal).

SELECTION ORDER: Risk (Critical→Moderate→Stable) → Onset (Sudden→Progressive→Recurring) → Alertness (Lethargic→Confused→Alert)

PROCESSES (check ALL):
  Rapid Response: Cardiac OR Pulmonary AND Critical only. NOT Infectious.
  Stretcher: Non-Ambulatory AND (Critical OR Trauma Moderate).
  Companion to Waiting Bay: Accompanied AND Stable. NOT Neurological or Infectious.
  Interpreter/Support: Cardiac/Pulmonary/Infectious AND Agitated AND Unaccompanied AND (Stable or Moderate).

DESTINATIONS:
  Surgical Bay:   Trauma Critical or Moderate.
  Acute Medical:  Cardiac/Pulmonary/Neurological Critical. OR Cardiac Moderate + Sudden onset.
  Monitored Ward: Cardiac Moderate (Progressive/Recurring). Cardiac Stable + Sudden. Pulmonary Moderate.
                  Neurological Moderate. Neurological Stable + Sudden. Infectious Critical.
  General Ward:   Everything else (Cardiac/Pulmonary/Neuro Stable non-Sudden, Infectious Mod/Stable, Trauma Stable).
"""

PROCESS_NAMES = {
    50:"Call Rapid Response", 51:"Request Stretcher",
    52:"Direct Companion to Waiting Bay", 53:"Request Interpreter/Support",
}

def _system_prompt(mode, language):
    guided = mode == "guided_learning"
    en = f"""You are TRIA, a triage training robot assistant.
You are concise, warm and speak naturally — never use lists or bullet points.
Use ONLY the triage rules below. Max 2-3 sentences per response.

MODE: {"GUIDED LEARNING" if guided else "ERROR-BASED LEARNING"}
{"You guide the participant one slot at a time. You know the correct answer and explain it using the patient's specific data." if guided else "You observe the participant's decisions and give feedback after they validate. You do NOT reveal the order during placement — if asked, say 'please check the printed rules'."}

QUESTION HANDLING:
- In guided mode: answer freely using the explanation context provided.
- In error-based mode during placement: if asked about the order, say only 'please check the printed rules'. Answer all other questions freely.
- After evaluation in any mode: answer freely.
- You may ask a clarifying question if the participant's question is ambiguous.

{RULES}"""

    es = f"""Eres TRIA, un robot asistente de entrenamiento de triaje.
Eres conciso, cálido y hablas de forma natural — nunca uses listas ni viñetas.
Usa ÚNICAMENTE las reglas de triaje siguientes. Máximo 2-3 frases por respuesta.

MODO: {"APRENDIZAJE GUIADO" if guided else "APRENDIZAJE BASADO EN ERRORES"}
{"Guías al participante ranura a ranura. Conoces la respuesta correcta y la explicas con los datos específicos del paciente." if guided else "Observas las decisiones del participante y das retroalimentación después de que valide. NO revelas el orden durante la colocación — si preguntan, di 'por favor consulta las reglas impresas'."}

MANEJO DE PREGUNTAS:
- En modo guiado: responde libremente usando el contexto de explicación proporcionado.
- En modo basado en errores durante la colocación: si preguntan sobre el orden, di solo 'por favor consulta las reglas impresas'. El resto de preguntas respóndelas libremente.
- Después de la evaluación en cualquier modo: responde libremente.

{RULES}"""
    return en if language == "en" else es

# ─── FALLBACKS ────────────────────────────────────────────────────────────────
def _fb(key, language, **kw):
    msgs = {
        "intro_1_guided":    {"en":"Hello, I am TRIA. Show me your patient cards to begin.",
                              "es":"Hola, soy TRIA. Muéstrame tus tarjetas de pacientes para comenzar."},
        "intro_1_error":     {"en":"Hello, I am TRIA. Arrange the five patients in triage order, then say validate.",
                              "es":"Hola, soy TRIA. Ordena los cinco pacientes y di validar cuando termines."},
        "intro_n_guided":    {"en":"Next group. Show me your cards.",
                              "es":"Siguiente grupo. Muéstrame tus tarjetas."},
        "intro_n_error":     {"en":"Next group. Arrange and say validate.",
                              "es":"Siguiente grupo. Ordena y di validar."},
        "correct_sel":       {"en":"Correct order. Now attach the process cards.",
                              "es":"Orden correcto. Ahora adjunta las tarjetas de proceso."},
        "correct_proc":      {"en":"All processes correct.",
                              "es":"Todos los procesos correctos."},
        "check_rules":       {"en":"Please check the printed rules.",
                              "es":"Por favor consulta las reglas impresas."},
    }
    return msgs.get(key,{}).get(language,"...")

class TriageAgent:
    def __init__(self, mode="error_based", language="en"):
        assert mode in ("guided_learning","error_based")
        assert language in ("en","es")
        self.mode=mode; self.language=language
        self.client=None; self._history=[]; self._session_summary=[]
        self._setup()

    def _setup(self):
        try:
            from groq import Groq
            key = os.environ.get("GROQ_API_KEY")
            if not key:
                print("[AGENT] No GROQ_API_KEY — using fallbacks."); return
            self.client = Groq(api_key=key)
            print(f"[AGENT] Ready llama-3.3-70b | {self.mode} | {self.language}")
        except ImportError:
            print("[AGENT] groq not installed — using fallbacks.")

    def _call(self, user_msg, max_tokens=180):
        if not self.client: return None
        self._history.append({"role":"user","content":user_msg})
        try:
            r = self.client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role":"system",
                            "content":_system_prompt(self.mode,self.language)},
                           *self._history],
                max_tokens=max_tokens, temperature=0.4)
            text = r.choices[0].message.content.strip()
            self._history.append({"role":"assistant","content":text})
            print(f"[AGENT] {text}")
            return text
        except Exception as e:
            print(f"[AGENT] Error: {e}")
            self._history.pop(); return None

    def _ctx(self):
        if not self._session_summary: return ""
        lines=["Previous iterations:"]
        for s in self._session_summary:
            sel=s.get("selection",{}); proc=s.get("processes",{})
            lines.append(f"  Iter {s['iteration']}: "
                         f"selection {sel.get('final_score','?')} "
                         f"({sel.get('attempts','?')} attempts); "
                         f"processes {proc.get('final_score','?')}.")
        return "\n".join(lines)

    # ─── PUBLIC METHODS ───────────────────────────────────────────────────────
    def introduction(self, iteration, mode, set_label):
        ctx = self._ctx()
        if self.language == "en":
            if iteration == 1:
                msg = (f"Introduce yourself as TRIA to a trainee nurse starting iteration 1. "
                       f"Summarise the triage rules in one sentence. "
                       f"End with: {'show me one of your patient cards' if mode=='guided_learning' else 'arrange the patient cards and say validate when ready'}. "
                       f"Max 3 sentences.")
            else:
                msg = (f"Starting iteration {iteration}/3. {ctx}\n"
                       f"One brief transition sentence. End with: "
                       f"{'show me your cards' if mode=='guided_learning' else 'arrange and validate'}.")
        else:
            if iteration == 1:
                msg = (f"Preséntate como TRIA a una enfermera en prácticas en la iteración 1. "
                       f"Resume las reglas en una frase. "
                       f"Termina con: {'muéstrame una tarjeta de paciente' if mode=='guided_learning' else 'ordena las tarjetas y di validar cuando termines'}. "
                       f"Máximo 3 frases.")
            else:
                msg = (f"Iteración {iteration}/3. {ctx}\n"
                       f"Una frase de transición. Termina con: "
                       f"{'muéstrame tus tarjetas' if mode=='guided_learning' else 'ordena y valida'}.")
        result = self._call(msg, max_tokens=120)
        key = f"intro_{'1' if iteration==1 else 'n'}_{mode.split('_')[0]}"
        return result or _fb(key, self.language)

    def announce_slot(self, slot_num, pid, patient_name,
                      explanation, language):
        """Guided: announce which patient to place in the current slot."""
        if language == "en":
            msg = (f"Guided learning — tell the participant to place {pid} {patient_name} "
                   f"in slot {slot_num}. Use this explanation: {explanation}\n"
                   f"Speak naturally in 1-2 sentences. Say 'please place them in slot {slot_num}'.")
        else:
            msg = (f"Aprendizaje guiado — di al participante que coloque {pid} {patient_name} "
                   f"en la ranura {slot_num}. Usa esta explicación: {explanation}\n"
                   f"Habla naturalmente en 1-2 frases. Di 'por favor colócalo en la ranura {slot_num}'.")
        result = self._call(msg, max_tokens=120)
        return result or f"Slot {slot_num}: place {pid} {patient_name}. {explanation}"

    def correct_wrong_slot(self, slot_num, placed_pid, placed_name,
                           target_pid, target_name, explanation, language):
        """Guided: wrong card placed — correct naturally using explanation."""
        if language == "en":
            msg = (f"The participant placed {placed_pid} {placed_name} in slot {slot_num} "
                   f"but the correct patient is {target_pid} {target_name}.\n"
                   f"Remind them why using this explanation: {explanation}\n"
                   f"Be natural and brief. 1-2 sentences. Do not just repeat the explanation verbatim.")
        else:
            msg = (f"El participante colocó {placed_pid} {placed_name} en la ranura {slot_num} "
                   f"pero el paciente correcto es {target_pid} {target_name}.\n"
                   f"Recuérdale por qué usando esta explicación: {explanation}\n"
                   f"Sé natural y breve. 1-2 frases.")
        result = self._call(msg, max_tokens=120)
        return result or (f"Slot {slot_num} needs {target_pid} {target_name}. "
                          f"{explanation}")

    def announce_process(self, slot_num, pid, patient_name,
                         processes, language):
        """Guided: announce which process cards to attach for this patient."""
        proc_str = (", ".join(processes) if processes
                    else ("no additional processes" if language=="en"
                          else "ningún proceso adicional"))
        if language == "en":
            msg = (f"Guided mode — tell the participant to attach the following "
                   f"process cards to {pid} {patient_name} in slot {slot_num}: {proc_str}. "
                   f"Briefly explain why using the triage rules. 1-2 sentences.")
        else:
            msg = (f"Modo guiado — di al participante que adjunte las siguientes "
                   f"tarjetas de proceso a {pid} {patient_name} en la ranura {slot_num}: {proc_str}. "
                   f"Explica brevemente por qué usando las reglas. 1-2 frases.")
        result = self._call(msg, max_tokens=120)
        return result or (f"For slot {slot_num} {pid}: {proc_str}.")

    def selection_correction(self, errors, expected, patient_data,
                             attempt_num=1, explanation_context=""):
        error_desc = "; ".join(
            f"slot {s}: placed {p or 'nothing'} "
            f"(expected {e}, {patient_data.get(e,{}).get('condition','?')})"
            for s,p,e in errors)
        order_str = ", ".join(f"slot {i+1}:{p}"
                              for i,p in enumerate(expected))
        ctx = self._ctx()
        if self.language == "en":
            msg = (f"Attempt {attempt_num}. Selection errors: {error_desc}.\n"
                   f"Correct order: {order_str}.\n"
                   f"{explanation_context}\n"
                   f"{ctx}\n"
                   f"Explain the key error using the patient explanations above "
                   f"(1 sentence), then state the correct order explicitly. "
                   f"Max 2 sentences.")
        else:
            msg = (f"Intento {attempt_num}. Errores: {error_desc}.\n"
                   f"Orden correcto: {order_str}.\n"
                   f"{explanation_context}\n"
                   f"{ctx}\n"
                   f"Explica el error principal usando las explicaciones de los "
                   f"pacientes (1 frase), luego indica el orden correcto. "
                   f"Máximo 2 frases.")
        result = self._call(msg, max_tokens=130)
        if result: return result
        parts = [f"slot {s}: expected {e}" for s,p,e in errors]
        return f"Errors: {'; '.join(parts)}. Correct order: {order_str}."

    def process_intro(self, iteration):
        if self.language=="en":
            msg = (f"Introduce the process card phase for iteration {iteration}. "
                   f"1 sentence: attach additional process cards to each patient card. "
                   f"{'Say ready when done.' if self.mode=='error_based' else ''}")
        else:
            msg = (f"Presenta la fase de procesos para la iteración {iteration}. "
                   f"1 frase: adjunta tarjetas de proceso adicionales a cada paciente. "
                   f"{'Di listo cuando termines.' if self.mode=='error_based' else ''}")
        result = self._call(msg, max_tokens=80)
        return result or ("Attach the additional process cards to each patient card."
                          if self.language=="en"
                          else "Adjunta las tarjetas de proceso adicionales a cada paciente.")

    def process_correction(self, errors, patient_data, attempt_num=1,
                           explanation_context=""):
        error_parts=[]
        for pid,placed,expected in errors:
            pdata=patient_data.get(pid,{})
            missing=[PROCESS_NAMES[i] for i in expected if i not in placed]
            extra  =[PROCESS_NAMES[i] for i in placed  if i not in expected]
            desc=f"{pid} ({pdata.get('condition','?')})"
            if missing: desc+=f": missing {', '.join(missing)}"
            if extra:   desc+=f": remove {', '.join(extra)}"
            error_parts.append(desc)
        ctx=self._ctx()
        if self.language=="en":
            msg=(f"Attempt {attempt_num}. Process errors: {'; '.join(error_parts)}.\n"
                 f"{explanation_context}\n"
                 f"{ctx}\n"
                 f"Explain the key process error using the patient explanations "
                 f"above (1 sentence), then state the correct processes explicitly. "
                 f"2 sentences max.")
        else:
            msg=(f"Intento {attempt_num}. Errores de proceso: {'; '.join(error_parts)}.\n"
                 f"{explanation_context}\n"
                 f"{ctx}\n"
                 f"Explica el error principal de proceso usando las explicaciones "
                 f"de los pacientes (1 frase), luego indica los procesos correctos. "
                 f"Máximo 2 frases.")
        result=self._call(msg,max_tokens=130)
        return result or f"Process errors: {'; '.join(error_parts)}."

    def phase_correct(self, phase, iteration, next_phase=""):
        next_map={
            "processes":     {"en":"now attach the process cards",
                              "es":"ahora adjunta las tarjetas de proceso"},
            "next_iteration":{"en":"ready for the next group",
                              "es":"listo para el siguiente grupo"},
        }
        next_str=next_map.get(next_phase,{}).get(self.language,"")
        ctx=self._ctx()
        if self.language=="en":
            msg=(f"The {phase} was completely correct.\n{ctx}\n"
                 f"Brief varied praise (1 sentence, don't repeat previous phrases). "
                 f"Then: {next_str}. Max 2 sentences.")
        else:
            msg=(f"El {phase} fue completamente correcto.\n{ctx}\n"
                 f"Elogio breve y variado (1 frase). Luego: {next_str}. Máximo 2 frases.")
        result=self._call(msg,max_tokens=80)
        key="correct_sel" if phase=="selection" else "correct_proc"
        return result or _fb(key,self.language)

    def answer_question(self, question, phase, mode, iteration,
                        explanation_context=""):
        ctx=self._ctx()
        restricted = (mode=="error_based" and
                      phase in ("PLACEMENT","VALIDATE_WAIT",
                                "SELECTION_CORRECTION"))
        if self.language=="en":
            msg=(f"[PHASE: {phase}] [MODE: {mode}]\n"
                 f"Participant asks: \"{question}\"\n"
                 f"{explanation_context}\n"
                 f"{'IMPORTANT: Do not reveal the triage order. If asked about order, say only: please check the printed rules.' if restricted else ''}\n"
                 f"{ctx}\nAnswer in 1-2 sentences.")
        else:
            msg=(f"[FASE: {phase}] [MODO: {mode}]\n"
                 f"El participante pregunta: \"{question}\"\n"
                 f"{explanation_context}\n"
                 f"{'IMPORTANTE: No reveles el orden. Si preguntan por el orden, di: por favor consulta las reglas.' if restricted else ''}\n"
                 f"{ctx}\nResponde en 1-2 frases.")
        result=self._call(msg,max_tokens=100)
        if result: return result
        return _fb("check_rules",self.language) if restricted else "Check the triage rules."

    def end_iteration(self, iteration, summary):
        self._session_summary.append({"iteration":iteration,**summary})
        print(f"[AGENT] Memory updated: iter {iteration}")

    def set_language(self, language):
        assert language in ("en","es")
        self.language=language
        print(f"[AGENT] Language → {language}")

LLMClient = TriageAgent
