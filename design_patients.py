# -*- coding: utf-8 -*-
"""
Triage Game — Patient Design Tool (v2)
Includes predetermined explanation texts per patient per group.
"""

import json

# ─── THRESHOLDS ───────────────────────────────────────────────────────────────
HR_CRIT_HIGH=130; HR_CRIT_LOW=40; HR_MOD=101
BP_HIGH=140; BP_LOW=90
SPO2_CRIT=80; SPO2_MOD=90
RR_CRIT_HIGH=30; RR_CRIT_LOW=10; RR_MOD=21
TEMP_CRIT=39.0; TEMP_CRIT_LOW=35.0; TEMP_MOD=38.0

def hr_level(v):
    if v>HR_CRIT_HIGH or v<HR_CRIT_LOW: return "Critical"
    if v>=HR_MOD: return "High"
    return "Normal"

def bp_level(v):
    if v>BP_HIGH: return "High"
    if v<BP_LOW:  return "Low"
    return "Normal"

def spo2_level(v):
    if v<SPO2_CRIT: return "Critical"
    if v<=SPO2_MOD: return "Low"
    return "Normal"

def rr_level(v):
    if v>RR_CRIT_HIGH or v<RR_CRIT_LOW: return "Critical"
    if v>=RR_MOD: return "High"
    return "Normal"

def temp_level(v):
    if v>TEMP_CRIT or v<TEMP_CRIT_LOW: return "Critical"
    if v>=TEMP_MOD: return "High"
    return "Normal"

def derive_risk(p):
    c=p["condition"]; ale=p["alertness"]; mob=p["mobility"]
    hr=hr_level(p["hr"]); bp=bp_level(p["bp"])
    s=spo2_level(p["spo2"]); rr=rr_level(p["rr"]); tmp=temp_level(p["temp"])
    if c=="Cardiac":
        if hr=="Critical" or (hr=="High" and bp in ("High","Low")): return "Critical"
        if hr=="High" or bp in ("High","Low"): return "Moderate"
        return "Stable"
    elif c=="Pulmonary":
        if s=="Critical" or (s=="Low" and rr=="Critical"): return "Critical"
        if s=="Low" or rr=="High": return "Moderate"
        return "Stable"
    elif c=="Neurological":
        if ale=="Lethargic": return "Critical"
        if ale=="Confused" or bp=="High": return "Moderate"
        return "Stable"
    elif c=="Trauma":
        if hr=="High" and mob=="Non-Ambulatory": return "Critical"
        if hr=="High" or mob=="Non-Ambulatory": return "Moderate"
        return "Stable"
    elif c=="Infectious":
        if tmp=="Critical" and hr=="High": return "Critical"
        if tmp=="High" or (tmp=="Critical" and hr=="Normal"): return "Moderate"
        return "Stable"
    return "Stable"

def derive_processes(p, risk):
    procs=[]; c=p["condition"]; mob=p["mobility"]
    cmp=p["companion"]; coo=p["cooperation"]
    if risk=="Critical" and c in ("Cardiac","Pulmonary"):
        procs.append("Rapid Response")
    if mob=="Non-Ambulatory":
        if risk=="Critical" or (risk=="Moderate" and c=="Trauma"):
            procs.append("Stretcher")
    if cmp=="Accompanied" and risk=="Stable" and c not in ("Neurological","Infectious"):
        procs.append("Companion Bay")
    if (c in ("Cardiac","Pulmonary","Infectious") and
            coo=="Agitated" and cmp=="Unaccompanied" and
            risk in ("Stable","Moderate")):
        procs.append("Interpreter")
    return procs

def derive_destination(p, risk):
    c=p["condition"]; onset=p["onset"]
    if c=="Trauma" and risk in ("Critical","Moderate"): return "Surgical Bay"
    if c in ("Cardiac","Pulmonary","Neurological") and risk=="Critical": return "Risk Ward"
    if c=="Cardiac" and risk=="Moderate" and onset=="Sudden": return "Risk Ward"
    if c=="Cardiac" and risk=="Moderate" and onset in ("Progressive","Recurring"): return "Monitored Ward"
    if c=="Cardiac" and risk=="Stable" and onset=="Sudden": return "Monitored Ward"
    if c=="Pulmonary" and risk=="Moderate": return "Monitored Ward"
    if c=="Neurological" and risk=="Moderate": return "Monitored Ward"
    if c=="Neurological" and risk=="Stable" and onset=="Sudden": return "Monitored Ward"
    if c=="Infectious" and risk=="Critical": return "Monitored Ward"
    return "General Ward"

RISK_ORDER={"Critical":0,"Moderate":1,"Stable":2}
ONSET_ORDER={"Sudden":0,"Progressive":1,"Recurring":2}
ALERT_ORDER={"Lethargic":0,"Confused":1,"Oriented":2}

def sort_key(p):
    risk=derive_risk(p)
    return (RISK_ORDER[risk],ONSET_ORDER[p["onset"]],ALERT_ORDER[p["alertness"]])

TRAPS = {
    "T1_alertness_tiebreak": "Two Critical+Sudden patients differ only in Alertness",
    "T2_infectious_not_first": "Infectious Critical ranks below another Critical",
    "T3_stable_beats_moderate": "Stable+Sudden ranks before Moderate+Recurring",
    "T4_onset_tiebreak": "Two same-risk patients differ only in Onset",
    "T5_no_rapid_infectious": "Infectious Critical — no Rapid Response",
    "T6_no_interpreter_neuro": "Neurological Agitated Unaccompanied — no Interpreter",
    "T7_stretcher_trauma_mod": "Trauma Moderate Non-Ambulatory → Stretcher",
    "T8_interpreter_cardiac_stable": "Cardiac Stable Agitated Unaccompanied → Interpreter",
    "T9_cardiac_mod_sudden_acute": "Cardiac Moderate Sudden → Risk Ward",
    "T10_cardiac_mod_progressive_monitored": "Cardiac Moderate Progressive → Monitored",
    "T11_neuro_stable_sudden_monitored": "Neurological Stable Sudden → Monitored",
    "T12_pulmonary_split": "Pulmonary Critical→Acute vs Moderate→Monitored",
    "T13_infectious_critical_monitored": "Infectious Critical → Monitored not Acute",
}

def detect_traps(group_patients):
    found=[]
    derived=[(p,derive_risk(p)) for p in group_patients]
    risks=derived
    if any(r=="Critical" and p["condition"]=="Infectious" for p,r in risks):
        if any(r=="Critical" and p["condition"]!="Infectious" for p,r in risks):
            found.append("T2_infectious_not_first")
        found.append("T5_no_rapid_infectious")
        found.append("T13_infectious_critical_monitored")
    crit_sudden=[(p,r) for p,r in risks if r=="Critical" and p["onset"]=="Sudden"]
    if len(crit_sudden)>=2 and len(set(p["alertness"] for p,r in crit_sudden))>1:
        found.append("T1_alertness_tiebreak")
    if (any(r=="Stable" and p["onset"]=="Sudden" for p,r in risks) and
            any(r=="Moderate" and p["onset"]=="Recurring" for p,r in risks)):
        found.append("T3_stable_beats_moderate")
    for rl in ("Critical","Moderate","Stable"):
        same=[p for p,r in risks if r==rl]
        if len(set(p["onset"] for p in same))>1:
            found.append("T4_onset_tiebreak"); break
    if any(p["condition"]=="Neurological" and p["cooperation"]=="Agitated"
           and p["companion"]=="Unaccompanied" for p,r in risks):
        found.append("T6_no_interpreter_neuro")
    if any(r=="Moderate" and p["condition"]=="Trauma" and
           p["mobility"]=="Non-Ambulatory" for p,r in risks):
        found.append("T7_stretcher_trauma_mod")
    if any(r=="Stable" and p["condition"]=="Cardiac" and
           p["cooperation"]=="Agitated" and p["companion"]=="Unaccompanied"
           for p,r in risks):
        found.append("T8_interpreter_cardiac_stable")
    if any(r=="Moderate" and p["condition"]=="Cardiac" and
           p["onset"]=="Sudden" for p,r in risks):
        found.append("T9_cardiac_mod_sudden_acute")
    if any(r=="Moderate" and p["condition"]=="Cardiac" and
           p["onset"] in ("Progressive","Recurring") for p,r in risks):
        found.append("T10_cardiac_mod_progressive_monitored")
    if any(r=="Stable" and p["condition"]=="Neurological" and
           p["onset"]=="Sudden" for p,r in risks):
        found.append("T11_neuro_stable_sudden_monitored")
    pulm=[(p,r) for p,r in risks if p["condition"]=="Pulmonary"]
    if "Critical" in {r for p,r in pulm} and "Moderate" in {r for p,r in pulm}:
        found.append("T12_pulmonary_split")
    return found

# ─── PATIENT DEFINITIONS ──────────────────────────────────────────────────────
# explanation_en / explanation_es: predetermined text read by robot in
# guided learning mode. 1-2 sentences explaining WHY this patient ranks
# where they do. Used as LLM context for follow-up questions.

PATIENTS_A = [
    # GROUP 1
    {"pid":"P01","name":"Marco T., 54M","group":1,
     "condition":"Cardiac","hr":142,"bp":118,"spo2":91,"rr":16,"temp":36.8,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Marco is Cardiac with HR 142 — that is Critical. He has Sudden onset and is Alert, so he goes second among the Critical patients.",
     "explanation_es":"Marco es Cardiaco con FC 142, lo que es Crítico. Tiene inicio Súbito y está Alerta, por lo que va segundo entre los pacientes Críticos.",
     "exp_selection_en":"Marco T. is Cardiac Critical (HR 142 bpm (Critical)). Onset Sudden, alertness Oriented.",
     "exp_processes_en":"Marco T. is Cardiac Critical: needs Rapid Response.",
     "exp_destination_en":"Marco T. is Cardiac Critical with Sudden onset → Risk Ward.",
     "exp_selection_es":"Marco T. es Cardiaco Crítico (HR 142 bpm (Critical)). Inicio Súbito, conciencia Orientado.",
     "exp_processes_es":"Marco T. es Cardiaco Crítico: necesita Respuesta Rápida.",
     "exp_destination_es":"Marco T. es Cardiaco Crítico con inicio Súbito → Sala de Riesgo."},

    {"pid":"P02","name":"Chiara V., 28F","group":1,
     "condition":"Pulmonary","hr":92,"bp":115,"spo2":76,"rr":24,"temp":39.1,
     "alertness":"Lethargic","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Chiara is Pulmonary with SpO2 87% — Critical. She is Lethargic with Sudden onset, which puts her first among all patients. She also needs a Stretcher and Rapid Response.",
     "explanation_es":"Chiara es Pulmonar con SpO2 87%, Crítica. Está Letárgica con inicio Súbito, lo que la pone primera. También necesita Camilla y Respuesta Rápida.",
     "exp_selection_en":"Chiara V. is Pulmonary Critical (SpO2 76% (Critical)). Onset Sudden, alertness Lethargic.",
     "exp_processes_en":"Chiara V. is Pulmonary Critical: needs Rapid Response, Stretcher.",
     "exp_destination_en":"Chiara V. is Pulmonary Critical with Sudden onset → Risk Ward.",
     "exp_selection_es":"Chiara V. es Pulmonar Crítico (SpO2 76% (Critical)). Inicio Súbito, conciencia Letárgico.",
     "exp_processes_es":"Chiara V. es Pulmonar Crítico: necesita Respuesta Rápida, Camilla.",
     "exp_destination_es":"Chiara V. es Pulmonar Crítico con inicio Súbito → Sala de Riesgo."},

    {"pid":"P03","name":"Elena C., 42F","group":1,
     "condition":"Cardiac","hr":115,"bp":118,"spo2":95,"rr":32,"temp":37.0,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Elena is Cardiac with HR 115 — that makes her Moderate. With Sudden onset, Cardiac Moderate goes to Risk Ward, not Monitored Ward. She also needs Interpreter support.",
     "explanation_es":"Elena es Cardiaca con FC 115, Moderada. Con inicio Súbito, Cardiaca Moderada va a Urgencias Médicas, no a la Sala Vigilada. También necesita Intérprete.",
     "exp_selection_en":"Elena C. is Cardiac Moderate (HR 115 bpm (Abnormal)). Onset Sudden, alertness Oriented.",
     "exp_processes_en":"Elena C. is Cardiac Moderate: needs Interpreter.",
     "exp_destination_en":"Elena C. is Cardiac Moderate with Sudden onset → Risk Ward.",
     "exp_selection_es":"Elena C. es Cardiaco Moderado (HR 115 bpm (Abnormal)). Inicio Súbito, conciencia Orientado.",
     "exp_processes_es":"Elena C. es Cardiaco Moderado: necesita Intérprete.",
     "exp_destination_es":"Elena C. es Cardiaco Moderado con inicio Súbito → Sala de Riesgo."},

    {"pid":"P04","name":"Yuki T., 61F","group":1,
     "condition":"Infectious","hr":112,"bp":148,"spo2":95,"rr":18,"temp":39.4,
     "alertness":"Oriented","onset":"Progressive","mobility":"Non-Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Yuki is Infectious with Temp 39.4 and HR 112 — both Critical thresholds, so she is Critical. Progressive onset places her third among Critical patients. Important: no Rapid Response for Infectious — that only applies to Cardiac and Pulmonary.",
     "explanation_es":"Yuki es Infecciosa con Temp 39.4 y FC 112, ambos umbrales Críticos. Inicio Progresivo la coloca tercera. Importante: no hay Respuesta Rápida para Infecciosos.",
     "exp_selection_en":"Yuki T. is Infectious Critical (HR 112 bpm (Abnormal) + Temp 39.4°C (Critical)). Onset Progressive, alertness Oriented.",
     "exp_processes_en":"Yuki T. is Infectious Critical: needs Stretcher.",
     "exp_destination_en":"Yuki T. is Infectious Critical with Progressive onset → Monitored Ward.",
     "exp_selection_es":"Yuki T. es Infeccioso Crítico (HR 112 bpm (Abnormal) + Temp 39.4°C (Critical)). Inicio Progresivo, conciencia Orientado.",
     "exp_processes_es":"Yuki T. es Infeccioso Crítico: necesita Camilla.",
     "exp_destination_es":"Yuki T. es Infeccioso Crítico con inicio Progresivo → Sala Vigilada."},

    {"pid":"P05","name":"David W., 58M","group":1,
     "condition":"Neurological","hr":128,"bp":128,"spo2":97,"rr":14,"temp":36.9,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"David is Neurological, Alert with normal BP — that is Stable. However his onset is Sudden, so a Stable Neurological patient with Sudden onset goes to Monitored Ward, not General Ward.",
     "explanation_es":"David es Neurológico, Alerta con TA normal — Estable. Pero con inicio Súbito, un Neurológico Estable va a Sala Vigilada, no a Planta General.",
     "exp_selection_en":"David W. is Neurological Stable (Alertness Oriented, BP normal). Onset Sudden, alertness Oriented.",
     "exp_processes_en":"David W. is Neurological Stable: no additional processes needed.",
     "exp_destination_en":"David W. is Neurological Stable with Sudden onset → Monitored Ward.",
     "exp_selection_es":"David W. es Neurológico Estable (Alertness Oriented, BP normal). Inicio Súbito, conciencia Orientado.",
     "exp_processes_es":"David W. es Neurológico Estable: no necesita procesos adicionales.",
     "exp_destination_es":"David W. es Neurológico Estable con inicio Súbito → Sala Vigilada."},

    # GROUP 2
    {"pid":"P06","name":"Stefan M., 83M","group":2,
     "condition":"Pulmonary","hr":96,"bp":122,"spo2":88,"rr":32,"temp":39.2,
     "alertness":"Oriented","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Stefan is Pulmonary with SpO2 88% and RR 32 — both Critical. He is Alert with Sudden onset, placing him second. He needs Rapid Response and a Stretcher.",
     "explanation_es":"Stefan es Pulmonar con SpO2 88% y FR 32, ambos Críticos. Alerta con inicio Súbito, segundo en el orden. Necesita Respuesta Rápida y Camilla.",
     "exp_selection_en":"Stefan M. is Pulmonary Critical (SpO2 88% (Abnormal) + RR 32/min (Critical)). Onset Sudden, alertness Oriented.",
     "exp_processes_en":"Stefan M. is Pulmonary Critical: needs Rapid Response, Stretcher.",
     "exp_destination_en":"Stefan M. is Pulmonary Critical with Sudden onset → Risk Ward.",
     "exp_selection_es":"Stefan M. es Pulmonar Crítico (SpO2 88% (Abnormal) + RR 32/min (Critical)). Inicio Súbito, conciencia Orientado.",
     "exp_processes_es":"Stefan M. es Pulmonar Crítico: necesita Respuesta Rápida, Camilla.",
     "exp_destination_es":"Stefan M. es Pulmonar Crítico con inicio Súbito → Sala de Riesgo."},

    {"pid":"P07","name":"Nora H., 35F","group":2,
     "condition":"Neurological","hr":134,"bp":162,"spo2":95,"rr":15,"temp":37.0,
     "alertness":"Lethargic","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Nora is Neurological and Lethargic — that alone makes her Critical. Progressive onset places her after Stefan. She goes to Risk Ward.",
     "explanation_es":"Nora es Neurológica y Letárgica, lo que por sí solo la hace Crítica. Inicio Progresivo la coloca después de Stefan. Va a Urgencias Médicas.",
     "exp_selection_en":"Nora H. is Neurological Critical (Alertness: Lethargic (Critical)). Onset Progressive, alertness Lethargic.",
     "exp_processes_en":"Nora H. is Neurological Critical: no additional processes needed.",
     "exp_destination_en":"Nora H. is Neurological Critical with Progressive onset → Risk Ward.",
     "exp_selection_es":"Nora H. es Neurológico Crítico (Alertness: Lethargic (Critical)). Inicio Progresivo, conciencia Letárgico.",
     "exp_processes_es":"Nora H. es Neurológico Crítico: no necesita procesos adicionales.",
     "exp_destination_es":"Nora H. es Neurológico Crítico con inicio Progresivo → Sala de Riesgo."},

    {"pid":"P08","name":"Bruno S., 77M","group":2,
     "condition":"Cardiac","hr":108,"bp":125,"spo2":92,"rr":16,"temp":36.7,
     "alertness":"Oriented","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Bruno is Cardiac with HR 108 — Moderate. His onset is Progressive, so he goes to Monitored Ward, not Risk Ward. Cardiac Moderate with Sudden onset would go to Risk Ward, but Progressive means Monitored.",
     "explanation_es":"Bruno es Cardiaco con FC 108, Moderado. Inicio Progresivo, va a Sala Vigilada. Si fuera Súbito iría a Urgencias Médicas, pero Progresivo significa Vigilada.",
     "exp_selection_en":"Bruno S. is Cardiac Moderate (HR 108 bpm (Abnormal)). Onset Progressive, alertness Oriented.",
     "exp_processes_en":"Bruno S. is Cardiac Moderate: no additional processes needed.",
     "exp_destination_en":"Bruno S. is Cardiac Moderate with Progressive onset → Monitored Ward.",
     "exp_selection_es":"Bruno S. es Cardiaco Moderado (HR 108 bpm (Abnormal)). Inicio Progresivo, conciencia Orientado.",
     "exp_processes_es":"Bruno S. es Cardiaco Moderado: no necesita procesos adicionales.",
     "exp_destination_es":"Bruno S. es Cardiaco Moderado con inicio Progresivo → Sala Vigilada."},

    {"pid":"P09","name":"Felix P., 69M","group":2,
     "condition":"Pulmonary","hr":84,"bp":118,"spo2":92,"rr":22,"temp":38.8,
     "alertness":"Oriented","onset":"Recurring","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Felix is Pulmonary with SpO2 92% — Moderate. Recurring onset ranks him after Bruno. He needs Interpreter support since he is Agitated and Unaccompanied.",
     "explanation_es":"Felix es Pulmonar con SpO2 92%, Moderado. Inicio Recurrente lo sitúa después de Bruno. Necesita Intérprete por estar Agitado y Sin Acompañante.",
     "exp_selection_en":"Felix P. is Pulmonary Moderate (RR 22/min (Abnormal)). Onset Recurring, alertness Oriented.",
     "exp_processes_en":"Felix P. is Pulmonary Moderate: needs Interpreter.",
     "exp_destination_en":"Felix P. is Pulmonary Moderate with Recurring onset → Monitored Ward.",
     "exp_selection_es":"Felix P. es Pulmonar Moderado (RR 22/min (Abnormal)). Inicio Recurrente, conciencia Orientado.",
     "exp_processes_es":"Felix P. es Pulmonar Moderado: necesita Intérprete.",
     "exp_destination_es":"Felix P. es Pulmonar Moderado con inicio Recurrente → Sala Vigilada."},

    {"pid":"P10","name":"Ingrid L., 50F","group":2,
     "condition":"Neurological","hr":126,"bp":138,"spo2":96,"rr":14,"temp":37.2,
     "alertness":"Confused","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Ingrid is Neurological and Confused — Moderate. Sudden onset ranks her first among Moderate patients. Important: even though she is Agitated and Unaccompanied, Neurological patients do not get Interpreter support.",
     "explanation_es":"Ingrid es Neurológica y Confusa, Moderada. Inicio Súbito la coloca primera entre Moderados. Importante: aunque esté Agitada y Sin Acompañante, los Neurológicos no reciben Intérprete.",
     "exp_selection_en":"Ingrid L. is Neurological Moderate (Alertness: Confused (Abnormal)). Onset Sudden, alertness Confused.",
     "exp_processes_en":"Ingrid L. is Neurological Moderate: no additional processes needed.",
     "exp_destination_en":"Ingrid L. is Neurological Moderate with Sudden onset → Monitored Ward.",
     "exp_selection_es":"Ingrid L. es Neurológico Moderado (Alertness: Confused (Abnormal)). Inicio Súbito, conciencia Confuso.",
     "exp_processes_es":"Ingrid L. es Neurológico Moderado: no necesita procesos adicionales.",
     "exp_destination_es":"Ingrid L. es Neurológico Moderado con inicio Súbito → Sala Vigilada."},

    # GROUP 3
    {"pid":"P11","name":"Rashid A., 39M","group":3,
     "condition":"Trauma","hr":118,"bp":95,"spo2":96,"rr":20,"temp":38.9,
     "alertness":"Oriented","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Rashid is Trauma with HR 118 and Non-Ambulatory — both conditions together make him Critical. Sudden onset places him first. He needs a Stretcher and goes to Surgical Bay.",
     "explanation_es":"Rashid es Traumático con FC 118 y No Ambulatorio, ambas condiciones juntas lo hacen Crítico. Inicio Súbito lo coloca primero. Necesita Camilla y va a Quirófano.",
     "exp_selection_en":"Rashid A. is Trauma Critical (HR 118 bpm (Abnormal) + Non-Ambulatory). Onset Sudden, alertness Oriented.",
     "exp_processes_en":"Rashid A. is Trauma Critical: needs Stretcher.",
     "exp_destination_en":"Rashid A. is Trauma Critical with Sudden onset → Surgical Bay.",
     "exp_selection_es":"Rashid A. es Trauma Crítico (HR 118 bpm (Abnormal) + Non-Ambulatory). Inicio Súbito, conciencia Orientado.",
     "exp_processes_es":"Rashid A. es Trauma Crítico: necesita Camilla.",
     "exp_destination_es":"Rashid A. es Trauma Crítico con inicio Súbito → Quirófano."},

    {"pid":"P12","name":"Amara D., 23F","group":3,
     "condition":"Trauma","hr":88,"bp":112,"spo2":91,"rr":15,"temp":36.9,
     "alertness":"Oriented","onset":"Progressive","mobility":"Non-Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Amara is Trauma and Non-Ambulatory with normal HR — that is Moderate, not Critical. She still needs a Stretcher because Trauma Moderate Non-Ambulatory qualifies. Progressive onset places her second.",
     "explanation_es":"Amara es Traumática y No Ambulatoria con FC normal, Moderada. Sigue necesitando Camilla porque Trauma Moderado No Ambulatorio califica. Inicio Progresivo, segunda.",
     "exp_selection_en":"Amara D. is Trauma Moderate (Non-Ambulatory). Onset Progressive, alertness Oriented.",
     "exp_processes_en":"Amara D. is Trauma Moderate: needs Stretcher.",
     "exp_destination_en":"Amara D. is Trauma Moderate with Progressive onset → Surgical Bay.",
     "exp_selection_es":"Amara D. es Trauma Moderado (Non-Ambulatory). Inicio Progresivo, conciencia Orientado.",
     "exp_processes_es":"Amara D. es Trauma Moderado: necesita Camilla.",
     "exp_destination_es":"Amara D. es Trauma Moderado con inicio Progresivo → Quirófano."},

    {"pid":"P13","name":"Priya J., 47F","group":3,
     "condition":"Neurological","hr":78,"bp":132,"spo2":96,"rr":8,"temp":36.8,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Priya is Neurological, Alert with normal BP — Stable. But Sudden onset for a Stable Neurological patient means Monitored Ward, not General Ward. She ranks before Mia because Stable Sudden beats Moderate Recurring.",
     "explanation_es":"Priya es Neurológica, Alerta con TA normal, Estable. Pero inicio Súbito para un Neurológico Estable significa Sala Vigilada. Va antes que Mia porque Estable Súbito supera Moderado Recurrente.",
     "exp_selection_en":"Priya J. is Neurological Stable (Alertness Oriented, BP normal). Onset Sudden, alertness Oriented.",
     "exp_processes_en":"Priya J. is Neurological Stable: no additional processes needed.",
     "exp_destination_en":"Priya J. is Neurological Stable with Sudden onset → Monitored Ward.",
     "exp_selection_es":"Priya J. es Neurológico Estable (Alertness Oriented, BP normal). Inicio Súbito, conciencia Orientado.",
     "exp_processes_es":"Priya J. es Neurológico Estable: no necesita procesos adicionales.",
     "exp_destination_es":"Priya J. es Neurológico Estable con inicio Súbito → Sala Vigilada."},

    {"pid":"P14","name":"Carlos E., 55M","group":3,
     "condition":"Cardiac","hr":88,"bp":125,"spo2":97,"rr":15,"temp":39.0,
     "alertness":"Oriented","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Carlos is Cardiac with normal HR and BP — Stable. Sudden onset means Monitored Ward. He is Agitated and Unaccompanied, so he needs Interpreter support.",
     "explanation_es":"Carlos es Cardiaco con FC y TA normales, Estable. Inicio Súbito significa Sala Vigilada. Está Agitado y Sin Acompañante, por lo que necesita Intérprete.",
     "exp_selection_en":"Carlos E. is Cardiac Stable (HR and BP within normal range). Onset Progressive, alertness Oriented.",
     "exp_processes_en":"Carlos E. is Cardiac Stable: needs Interpreter.",
     "exp_destination_en":"Carlos E. is Cardiac Stable with Progressive onset → General Ward.",
     "exp_selection_es":"Carlos E. es Cardiaco Estable (HR and BP within normal range). Inicio Progresivo, conciencia Orientado.",
     "exp_processes_es":"Carlos E. es Cardiaco Estable: necesita Intérprete.",
     "exp_destination_es":"Carlos E. es Cardiaco Estable con inicio Progresivo → Planta General."},

    {"pid":"P15","name":"Mia F., 66F","group":3,
     "condition":"Infectious","hr":82,"bp":148,"spo2":96,"rr":16,"temp":38.4,
     "alertness":"Oriented","onset":"Recurring","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Mia is Infectious with Temp 38.4 — Moderate. Recurring onset places her last. Moderate Infectious goes to General Ward.",
     "explanation_es":"Mia es Infecciosa con Temp 38.4, Moderada. Inicio Recurrente la coloca última. Infecciosa Moderada va a Planta General.",
     "exp_selection_en":"Mia F. is Infectious Moderate (Temp 38.4°C (Abnormal)). Onset Recurring, alertness Oriented.",
     "exp_processes_en":"Mia F. is Infectious Moderate: no additional processes needed.",
     "exp_destination_en":"Mia F. is Infectious Moderate with Recurring onset → General Ward.",
     "exp_selection_es":"Mia F. es Infeccioso Moderado (Temp 38.4°C (Abnormal)). Inicio Recurrente, conciencia Orientado.",
     "exp_processes_es":"Mia F. es Infeccioso Moderado: no necesita procesos adicionales.",
     "exp_destination_es":"Mia F. es Infeccioso Moderado con inicio Recurrente → Planta General."},
]

PATIENTS_B = [
    # GROUP 1
    {"pid":"P01","name":"James K., 49M","group":1,
     "condition":"Cardiac","hr":138,"bp":105,"spo2":95,"rr":17,"temp":39.3,
     "alertness":"Lethargic","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"James is Cardiac with HR 138 — Critical. He is Lethargic with Sudden onset, placing him first. He needs Rapid Response and a Stretcher.",
     "explanation_es":"James es Cardiaco con FC 138, Crítico. Letárgico con inicio Súbito, primero en el orden. Necesita Respuesta Rápida y Camilla.",
     "exp_selection_en":"James K. is Cardiac Critical (HR 138 bpm (Critical)). Onset Sudden, alertness Lethargic.",
     "exp_processes_en":"James K. is Cardiac Critical: needs Rapid Response, Stretcher.",
     "exp_destination_en":"James K. is Cardiac Critical with Sudden onset → Risk Ward.",
     "exp_selection_es":"James K. es Cardiaco Crítico (HR 138 bpm (Critical)). Inicio Súbito, conciencia Letárgico.",
     "exp_processes_es":"James K. es Cardiaco Crítico: necesita Respuesta Rápida, Camilla.",
     "exp_destination_es":"James K. es Cardiaco Crítico con inicio Súbito → Sala de Riesgo."},

    {"pid":"P02","name":"Fatima B., 38F","group":1,
     "condition":"Pulmonary","hr":128,"bp":118,"spo2":77,"rr":19,"temp":36.7,
     "alertness":"Oriented","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Fatima is Pulmonary with SpO2 88% — Critical. Alert with Sudden onset, she goes second after James. She needs Rapid Response and a Stretcher.",
     "explanation_es":"Fatima es Pulmonar con SpO2 88%, Crítica. Alerta con inicio Súbito, segunda después de James. Necesita Respuesta Rápida y Camilla.",
     "exp_selection_en":"Fatima B. is Pulmonary Critical (SpO2 77% (Critical)). Onset Sudden, alertness Oriented.",
     "exp_processes_en":"Fatima B. is Pulmonary Critical: needs Rapid Response, Stretcher.",
     "exp_destination_en":"Fatima B. is Pulmonary Critical with Sudden onset → Risk Ward.",
     "exp_selection_es":"Fatima B. es Pulmonar Crítico (SpO2 77% (Critical)). Inicio Súbito, conciencia Orientado.",
     "exp_processes_es":"Fatima B. es Pulmonar Crítico: necesita Respuesta Rápida, Camilla.",
     "exp_destination_es":"Fatima B. es Pulmonar Crítico con inicio Súbito → Sala de Riesgo."},

    {"pid":"P03","name":"Luca M., 74M","group":1,
     "condition":"Cardiac","hr":114,"bp":122,"spo2":91,"rr":16,"temp":36.8,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Luca is Cardiac with HR 114 — Moderate. Sudden onset means he goes to Risk Ward. He needs Interpreter support.",
     "explanation_es":"Luca es Cardiaco con FC 114, Moderado. Inicio Súbito significa Urgencias Médicas. Necesita Intérprete.",
     "exp_selection_en":"Luca M. is Cardiac Moderate (HR 114 bpm (Abnormal)). Onset Sudden, alertness Oriented.",
     "exp_processes_en":"Luca M. is Cardiac Moderate: needs Interpreter.",
     "exp_destination_en":"Luca M. is Cardiac Moderate with Sudden onset → Risk Ward.",
     "exp_selection_es":"Luca M. es Cardiaco Moderado (HR 114 bpm (Abnormal)). Inicio Súbito, conciencia Orientado.",
     "exp_processes_es":"Luca M. es Cardiaco Moderado: necesita Intérprete.",
     "exp_destination_es":"Luca M. es Cardiaco Moderado con inicio Súbito → Sala de Riesgo."},

    {"pid":"P04","name":"Thomas H., 61M","group":1,
     "condition":"Infectious","hr":116,"bp":110,"spo2":96,"rr":33,"temp":39.6,
     "alertness":"Oriented","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Thomas is Infectious with Temp 39.6 and HR 116 — Critical. Progressive onset places him third among Critical patients. No Rapid Response for Infectious — goes to Monitored Ward.",
     "explanation_es":"Thomas es Infeccioso con Temp 39.6 y FC 116, Crítico. Inicio Progresivo, tercero entre Críticos. Sin Respuesta Rápida para Infecciosos, va a Sala Vigilada.",
     "exp_selection_en":"Thomas H. is Infectious Critical (HR 116 bpm (Abnormal) + Temp 39.6°C (Critical)). Onset Progressive, alertness Oriented.",
     "exp_processes_en":"Thomas H. is Infectious Critical: no additional processes needed.",
     "exp_destination_en":"Thomas H. is Infectious Critical with Progressive onset → Monitored Ward.",
     "exp_selection_es":"Thomas H. es Infeccioso Crítico (HR 116 bpm (Abnormal) + Temp 39.6°C (Critical)). Inicio Progresivo, conciencia Orientado.",
     "exp_processes_es":"Thomas H. es Infeccioso Crítico: no necesita procesos adicionales.",
     "exp_destination_es":"Thomas H. es Infeccioso Crítico con inicio Progresivo → Sala Vigilada."},

    {"pid":"P05","name":"Rosa T., 41F","group":1,
     "condition":"Neurological","hr":76,"bp":130,"spo2":97,"rr":14,"temp":38.9,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Rosa is Neurological, Alert with normal BP — Stable. Sudden onset for a Stable Neurological patient means Monitored Ward, not General Ward.",
     "explanation_es":"Rosa es Neurológica, Alerta con TA normal, Estable. Inicio Súbito para un Neurológico Estable significa Sala Vigilada, no Planta General.",
     "exp_selection_en":"Rosa T. is Neurological Stable (Alertness Oriented, BP normal). Onset Sudden, alertness Oriented.",
     "exp_processes_en":"Rosa T. is Neurological Stable: no additional processes needed.",
     "exp_destination_en":"Rosa T. is Neurological Stable with Sudden onset → Monitored Ward.",
     "exp_selection_es":"Rosa T. es Neurológico Estable (Alertness Oriented, BP normal). Inicio Súbito, conciencia Orientado.",
     "exp_processes_es":"Rosa T. es Neurológico Estable: no necesita procesos adicionales.",
     "exp_destination_es":"Rosa T. es Neurológico Estable con inicio Súbito → Sala Vigilada."},

    # GROUP 2
    {"pid":"P06","name":"Yara N., 52F","group":2,
     "condition":"Pulmonary","hr":98,"bp":115,"spo2":76,"rr":28,"temp":38.7,
     "alertness":"Oriented","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Yara is Pulmonary with SpO2 87% — Critical. Alert with Sudden onset, she goes second after Ahmed. She needs Rapid Response and a Stretcher.",
     "explanation_es":"Yara es Pulmonar con SpO2 87%, Crítica. Alerta con inicio Súbito, segunda después de Ahmed. Necesita Respuesta Rápida y Camilla.",
     "exp_selection_en":"Yara N. is Pulmonary Critical (SpO2 76% (Critical)). Onset Sudden, alertness Oriented.",
     "exp_processes_en":"Yara N. is Pulmonary Critical: needs Rapid Response, Stretcher.",
     "exp_destination_en":"Yara N. is Pulmonary Critical with Sudden onset → Risk Ward.",
     "exp_selection_es":"Yara N. es Pulmonar Crítico (SpO2 76% (Critical)). Inicio Súbito, conciencia Orientado.",
     "exp_processes_es":"Yara N. es Pulmonar Crítico: necesita Respuesta Rápida, Camilla.",
     "exp_destination_es":"Yara N. es Pulmonar Crítico con inicio Súbito → Sala de Riesgo."},

    {"pid":"P07","name":"Ahmed R., 85M","group":2,
     "condition":"Neurological","hr":82,"bp":168,"spo2":95,"rr":16,"temp":39.1,
     "alertness":"Lethargic","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Ahmed is Neurological and Lethargic — Critical regardless of other vitals. Lethargic with Sudden onset puts him first.",
     "explanation_es":"Ahmed es Neurológico y Letárgico, Crítico independientemente de otros signos. Letárgico con inicio Súbito lo coloca primero.",
     "exp_selection_en":"Ahmed R. is Neurological Critical (Alertness: Lethargic (Critical)). Onset Sudden, alertness Lethargic.",
     "exp_processes_en":"Ahmed R. is Neurological Critical: no additional processes needed.",
     "exp_destination_en":"Ahmed R. is Neurological Critical with Sudden onset → Risk Ward.",
     "exp_selection_es":"Ahmed R. es Neurológico Crítico (Alertness: Lethargic (Critical)). Inicio Súbito, conciencia Letárgico.",
     "exp_processes_es":"Ahmed R. es Neurológico Crítico: no necesita procesos adicionales.",
     "exp_destination_es":"Ahmed R. es Neurológico Crítico con inicio Súbito → Sala de Riesgo."},

    {"pid":"P08","name":"Clara S., 44F","group":2,
     "condition":"Cardiac","hr":95,"bp":148,"spo2":96,"rr":31,"temp":36.8,
     "alertness":"Oriented","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Clara is Cardiac with BP 148 — Moderate. Progressive onset means Monitored Ward. Cardiac Moderate with Progressive onset goes to Monitored, not Risk Ward.",
     "explanation_es":"Clara es Cardiaca con TA 148, Moderada. Inicio Progresivo significa Sala Vigilada. Cardiaca Moderada con Progresivo va a Vigilada, no a Urgencias.",
     "exp_selection_en":"Clara S. is Cardiac Moderate (BP 148 mmHg (Abnormal)). Onset Progressive, alertness Oriented.",
     "exp_processes_en":"Clara S. is Cardiac Moderate: no additional processes needed.",
     "exp_destination_en":"Clara S. is Cardiac Moderate with Progressive onset → Monitored Ward.",
     "exp_selection_es":"Clara S. es Cardiaco Moderado (BP 148 mmHg (Abnormal)). Inicio Progresivo, conciencia Orientado.",
     "exp_processes_es":"Clara S. es Cardiaco Moderado: no necesita procesos adicionales.",
     "exp_destination_es":"Clara S. es Cardiaco Moderado con inicio Progresivo → Sala Vigilada."},

    {"pid":"P09","name":"Oscar V., 56M","group":2,
     "condition":"Pulmonary","hr":86,"bp":120,"spo2":91,"rr":23,"temp":39.0,
     "alertness":"Oriented","onset":"Recurring","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Oscar is Pulmonary with SpO2 91% — Moderate. Recurring onset places him last among Moderate patients. He needs Interpreter support.",
     "explanation_es":"Oscar es Pulmonar con SpO2 91%, Moderado. Inicio Recurrente lo coloca último entre Moderados. Necesita Intérprete.",
     "exp_selection_en":"Oscar V. is Pulmonary Moderate (RR 23/min (Abnormal)). Onset Recurring, alertness Oriented.",
     "exp_processes_en":"Oscar V. is Pulmonary Moderate: needs Interpreter.",
     "exp_destination_en":"Oscar V. is Pulmonary Moderate with Recurring onset → Monitored Ward.",
     "exp_selection_es":"Oscar V. es Pulmonar Moderado (RR 23/min (Abnormal)). Inicio Recurrente, conciencia Orientado.",
     "exp_processes_es":"Oscar V. es Pulmonar Moderado: necesita Intérprete.",
     "exp_destination_es":"Oscar V. es Pulmonar Moderado con inicio Recurrente → Sala Vigilada."},

    {"pid":"P10","name":"Vera C., 27F","group":2,
     "condition":"Neurological","hr":129,"bp":135,"spo2":97,"rr":15,"temp":37.1,
     "alertness":"Confused","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Vera is Neurological and Confused — Moderate. Sudden onset ranks her first among Moderate patients. Even though she is Agitated and Unaccompanied, Neurological patients do not get Interpreter support.",
     "explanation_es":"Vera es Neurológica y Confusa, Moderada. Inicio Súbito la coloca primera entre Moderados. Aunque Agitada y Sin Acompañante, los Neurológicos no reciben Intérprete.",
     "exp_selection_en":"Vera C. is Neurological Moderate (Alertness: Confused (Abnormal)). Onset Sudden, alertness Confused.",
     "exp_processes_en":"Vera C. is Neurological Moderate: no additional processes needed.",
     "exp_destination_en":"Vera C. is Neurological Moderate with Sudden onset → Monitored Ward.",
     "exp_selection_es":"Vera C. es Neurológico Moderado (Alertness: Confused (Abnormal)). Inicio Súbito, conciencia Confuso.",
     "exp_processes_es":"Vera C. es Neurológico Moderado: no necesita procesos adicionales.",
     "exp_destination_es":"Vera C. es Neurológico Moderado con inicio Súbito → Sala Vigilada."},

    # GROUP 3
    {"pid":"P11","name":"Paulo F., 78M","group":3,
     "condition":"Trauma","hr":122,"bp":98,"spo2":91,"rr":21,"temp":37.0,
     "alertness":"Oriented","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Paulo is Trauma with HR 122 and Non-Ambulatory — Critical. Sudden onset places him first. He needs a Stretcher and goes to Surgical Bay.",
     "explanation_es":"Paulo es Traumático con FC 122 y No Ambulatorio, Crítico. Inicio Súbito, primero. Necesita Camilla y va a Quirófano.",
     "exp_selection_en":"Paulo F. is Trauma Critical (HR 122 bpm (Abnormal) + Non-Ambulatory). Onset Sudden, alertness Oriented.",
     "exp_processes_en":"Paulo F. is Trauma Critical: needs Stretcher.",
     "exp_destination_en":"Paulo F. is Trauma Critical with Sudden onset → Surgical Bay.",
     "exp_selection_es":"Paulo F. es Trauma Crítico (HR 122 bpm (Abnormal) + Non-Ambulatory). Inicio Súbito, conciencia Orientado.",
     "exp_processes_es":"Paulo F. es Trauma Crítico: necesita Camilla.",
     "exp_destination_es":"Paulo F. es Trauma Crítico con inicio Súbito → Quirófano."},

    {"pid":"P12","name":"Hana M., 36F","group":3,
     "condition":"Trauma","hr":85,"bp":118,"spo2":97,"rr":16,"temp":39.2,
     "alertness":"Oriented","onset":"Progressive","mobility":"Non-Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Hana is Trauma Non-Ambulatory with normal HR — Moderate. Non-Ambulatory alone makes Trauma Moderate, and she still needs a Stretcher. Progressive onset places her second.",
     "explanation_es":"Hana es Traumática No Ambulatoria con FC normal, Moderada. No Ambulatoria sola hace Trauma Moderado y sigue necesitando Camilla. Progresivo, segunda.",
     "exp_selection_en":"Hana M. is Trauma Moderate (Non-Ambulatory). Onset Progressive, alertness Oriented.",
     "exp_processes_en":"Hana M. is Trauma Moderate: needs Stretcher.",
     "exp_destination_en":"Hana M. is Trauma Moderate with Progressive onset → Surgical Bay.",
     "exp_selection_es":"Hana M. es Trauma Moderado (Non-Ambulatory). Inicio Progresivo, conciencia Orientado.",
     "exp_processes_es":"Hana M. es Trauma Moderado: necesita Camilla.",
     "exp_destination_es":"Hana M. es Trauma Moderado con inicio Progresivo → Quirófano."},

    {"pid":"P13","name":"Igor P., 82M","group":3,
     "condition":"Neurological","hr":128,"bp":132,"spo2":96,"rr":15,"temp":36.9,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Igor is Neurological, Alert with BP 132 — Stable. Sudden onset means Monitored Ward. He ranks before Luis because Stable Sudden beats Moderate Recurring.",
     "explanation_es":"Igor es Neurológico, Alerta con TA 132, Estable. Inicio Súbito significa Sala Vigilada. Va antes que Luis porque Estable Súbito supera Moderado Recurrente.",
     "exp_selection_en":"Igor P. is Neurological Stable (Alertness Oriented, BP normal). Onset Sudden, alertness Oriented.",
     "exp_processes_en":"Igor P. is Neurological Stable: no additional processes needed.",
     "exp_destination_en":"Igor P. is Neurological Stable with Sudden onset → Monitored Ward.",
     "exp_selection_es":"Igor P. es Neurológico Estable (Alertness Oriented, BP normal). Inicio Súbito, conciencia Orientado.",
     "exp_processes_es":"Igor P. es Neurológico Estable: no necesita procesos adicionales.",
     "exp_destination_es":"Igor P. es Neurológico Estable con inicio Súbito → Sala Vigilada."},

    {"pid":"P14","name":"Zara O., 48F","group":3,
     "condition":"Cardiac","hr":90,"bp":122,"spo2":97,"rr":8,"temp":36.7,
     "alertness":"Oriented","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Zara is Cardiac with normal HR and BP — Stable. Sudden onset means Monitored Ward. She is Agitated and Unaccompanied so she needs Interpreter support.",
     "explanation_es":"Zara es Cardiaca con FC y TA normales, Estable. Inicio Súbito significa Sala Vigilada. Agitada y Sin Acompañante, necesita Intérprete.",
     "exp_selection_en":"Zara O. is Cardiac Stable (HR and BP within normal range). Onset Progressive, alertness Oriented.",
     "exp_processes_en":"Zara O. is Cardiac Stable: needs Interpreter.",
     "exp_destination_en":"Zara O. is Cardiac Stable with Progressive onset → General Ward.",
     "exp_selection_es":"Zara O. es Cardiaco Estable (HR and BP within normal range). Inicio Progresivo, conciencia Orientado.",
     "exp_processes_es":"Zara O. es Cardiaco Estable: necesita Intérprete.",
     "exp_destination_es":"Zara O. es Cardiaco Estable con inicio Progresivo → Planta General."},

    {"pid":"P15","name":"Luis D., 57M","group":3,
     "condition":"Infectious","hr":125,"bp":115,"spo2":96,"rr":17,"temp":38.6,
     "alertness":"Oriented","onset":"Recurring","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Luis is Infectious with Temp 38.6 — Moderate. Recurring onset places him last. Infectious Moderate goes to General Ward.",
     "explanation_es":"Luis es Infeccioso con Temp 38.6, Moderado. Inicio Recurrente lo coloca último. Infeccioso Moderado va a Planta General.",
     "exp_selection_en":"Luis D. is Infectious Moderate (Temp 38.6°C (Abnormal)). Onset Recurring, alertness Oriented.",
     "exp_processes_en":"Luis D. is Infectious Moderate: no additional processes needed.",
     "exp_destination_en":"Luis D. is Infectious Moderate with Recurring onset → General Ward.",
     "exp_selection_es":"Luis D. es Infeccioso Moderado (Temp 38.6°C (Abnormal)). Inicio Recurrente, conciencia Orientado.",
     "exp_processes_es":"Luis D. es Infeccioso Moderado: no necesita procesos adicionales.",
     "exp_destination_es":"Luis D. es Infeccioso Moderado con inicio Recurrente → Planta General."},
]

if __name__ == "__main__":
    import json
    for set_label, patients in [("A", PATIENTS_A), ("B", PATIENTS_B)]:
        groups = {}
        for p in patients:
            groups.setdefault(p['group'],[]).append(p)
        print(f"\n{'='*60}\nSET {set_label}\n{'='*60}")
        for g in sorted(groups):
            print(f"\nGroup {g}:")
            for p in sorted(groups[g], key=sort_key):
                risk = derive_risk(p)
                procs = derive_processes(p, risk)
                dest = derive_destination(p, risk)
                print(f"  {p['pid']} {p['name']:20} {risk:8} | "
                      f"{', '.join(procs) or 'none':35} | {dest}")
    save = input("\nSave design_output.json? (y/n): ").strip().lower()
    if save == 'y':
        data = {"set_a": PATIENTS_A, "set_b": PATIENTS_B}
        with open("design_output.json","w") as f:
            json.dump(data, f, indent=2)
        print("Saved.")
