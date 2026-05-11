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
RR_CRIT_HIGH=30; RR_MOD=21; RR_NORM_LOW=11
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
    if v>RR_CRIT_HIGH: return "Critical"
    if v>=RR_MOD: return "High"

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
    {"pid":"P01","name":"Marco, 54M","group":1,
     "condition":"Cardiac","hr":142,"bp":118,"spo2":91,"rr":16,"temp":36.8,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Marco is Cardiac with HR 142 — that is Critical. He has Sudden onset and is Alert, so he goes second among the Critical patients.",
     "explanation_es":"Marco es Cardiaco con FC 142, lo que es Crítico. Tiene inicio Súbito y está Alerta, por lo que va segundo entre los pacientes Críticos.",
     "exp_selection_en":"Marco goes second. He is Cardiac Critical (HR 142 bpm — above the Critical threshold of 130). All three Critical patients rank above Elena (Moderate) and David (Stable). Among the Critical trio, Chiara and Marco share Sudden onset. Chiara goes first because she is Lethargic; Marco is Oriented. Marco ranks above Yuki because his onset is Sudden versus Yuki's Progressive.",
     "exp_processes_en":"Rapid Response (Cardiac Critical). No Stretcher: Cardiac Critical qualifies on risk, but Marco is Ambulatory — both conditions must be met. No Interpreter: Marco is Agitated and Unaccompanied, which fulfils the social criteria, but Interpreter only applies to Stable or Moderate patients — Marco is Critical.",
     "exp_destination_en":"Risk Ward (Cardiac Critical always goes there regardless of onset).",
     "exp_selection_es":"Marco va segundo. Es Cardiaco Crítico (FC 142 lpm — por encima del umbral Crítico de 130). Los tres pacientes Críticos tienen prioridad sobre Elena (Moderado) y David (Estable). Entre los Críticos, Chiara y Marco comparten inicio Súbito. Chiara va primero por ser Letárgica; Marco está Orientado. Marco supera a Yuki porque su inicio es Súbito frente al Progresivo de Yuki.",
     "exp_processes_es":"Respuesta Rápida (Cardiaco Crítico). No Camilla: el riesgo Crítico Cardiaco cumple el criterio de riesgo, pero Marco es Ambulatorio — ambas condiciones son necesarias. No Intérprete: Marco está Agitado y Sin Acompañante, lo que cumple el criterio social, pero el Intérprete solo aplica a pacientes Estables o Moderados — Marco es Crítico.",
     "exp_destination_es":"Sala de Riesgo (Cardiaco Crítico siempre va allí)."},

    {"pid":"P02","name":"Chiara, 28F","group":1,
     "condition":"Pulmonary","hr":92,"bp":115,"spo2":76,"rr":24,"temp":39.1,
     "alertness":"Lethargic","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Chiara is Pulmonary with SpO2 87% — Critical. She is Lethargic with Sudden onset, which puts her first among all patients. She also needs a Stretcher and Rapid Response.",
     "explanation_es":"Chiara es Pulmonar con SpO2 87%, Crítica. Está Letárgica con inicio Súbito, lo que la pone primera. También necesita Camilla y Respuesta Rápida.",
     "exp_selection_en":"Chiara goes first. She is Pulmonary Critical (SpO2 76% — below the Critical threshold of 80%). All three Critical patients rank above the others. Among them, Chiara and Marco have Sudden onset. Between the two, Chiara is Lethargic while Marco is Oriented — Lethargic always takes priority. Her temperature (39.1°C) is Critical, but temperature does not affect Pulmonary risk derivation.",
     "exp_processes_en":"Rapid Response (Pulmonary Critical). Stretcher (Critical and Non-Ambulatory). Although she is Accompanied, Companion Bay requires Stable risk — Chiara is Critical.",
     "exp_destination_en":"Risk Ward (Pulmonary Critical always goes there). Monitored Ward would apply if she were Pulmonary Moderate.",
     "exp_selection_es":"Chiara va primera. Es Pulmonar Crítico (SpO2 76% — por debajo del umbral Crítico del 80%). Los tres Críticos tienen prioridad sobre los demás. Entre ellos, Chiara y Marco tienen inicio Súbito. Entre ambos, Chiara está Letárgica y Marco Orientado — el estado Letárgico siempre tiene prioridad. Su temperatura (39.1°C) es Crítica, pero la temperatura no afecta la derivación de riesgo Pulmonar.",
     "exp_processes_es":"Respuesta Rápida (Pulmonar Crítico). Camilla (Crítico y No Ambulatoria). Aunque está Acompañada, la Sala de Acompañante requiere riesgo Estable — Chiara es Crítica.",
     "exp_destination_es":"Sala de Riesgo (Pulmonar Crítica siempre va allí). La Sala Vigilada aplicaría si fuera Pulmonar Moderado."},

    {"pid":"P03","name":"Elena, 42F","group":1,
     "condition":"Cardiac","hr":115,"bp":118,"spo2":95,"rr":32,"temp":37.0,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Elena is Cardiac with HR 115 — that makes her Moderate. With Sudden onset, Cardiac Moderate goes to Risk Ward, not Monitored Ward. She also needs Interpreter support.",
     "explanation_es":"Elena es Cardiaca con FC 115, Moderada. Con inicio Súbito, Cardiaca Moderada va a Urgencias Médicas, no a la Sala Vigilada. También necesita Intérprete.",
     "exp_selection_en":"Elena goes fourth. She is Cardiac Moderate (HR 115 bpm — Abnormal, 101–130). She is not Critical: Cardiac Critical requires either HR above 130 (hers is 115) or HR Abnormal AND BP Abnormal simultaneously — her BP (118 mmHg) is Normal. Note that her RR is 32/min (Critical, >30), but respiratory rate does not affect Cardiac risk. All three Critical patients rank above her.",
     "exp_processes_en":"Interpreter (Cardiac, Moderate risk, Agitated, Unaccompanied — all four criteria met). No Rapid Response: Cardiac qualifies on condition, but Rapid Response requires Critical risk — Elena is Moderate.",
     "exp_destination_en":"Risk Ward. Cardiac Moderate with Sudden onset goes to the Risk Ward. Monitored Ward applies to Cardiac Moderate only with Progressive or Recurring onset.",
     "exp_selection_es":"Elena va cuarta. Es Cardiaco Moderado (FC 115 lpm — Anormal, 101–130). No es Crítico: Cardiaco Crítico requiere FC por encima de 130 (la suya es 115) o FC Anormal Y TA Anormal simultáneamente — su TA (118 mmHg) es Normal. Nota: su FR es 32/min (Crítica, >30), pero la frecuencia respiratoria no afecta el riesgo Cardiaco. Los tres pacientes Críticos tienen prioridad.",
     "exp_processes_es":"Intérprete (Cardiaco, riesgo Moderado, Agitada, Sin Acompañante — los cuatro criterios cumplidos). No Respuesta Rápida: Cardiaco cumple el criterio de condición, pero la Respuesta Rápida requiere riesgo Crítico — Elena es Moderada.",
     "exp_destination_es":"Sala de Riesgo. Cardiaco Moderado con inicio Súbito va a la Sala de Riesgo. La Sala Vigilada aplica a Cardiaco Moderado solo con inicio Progresivo o Recurrente."},

    {"pid":"P04","name":"Yuki, 61F","group":1,
     "condition":"Infectious","hr":112,"bp":148,"spo2":95,"rr":18,"temp":39.4,
     "alertness":"Oriented","onset":"Progressive","mobility":"Non-Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Yuki is Infectious with Temp 39.4 and HR 112 — both Critical thresholds, so she is Critical. Progressive onset places her third among Critical patients. Important: no Rapid Response for Infectious — that only applies to Cardiac and Pulmonary.",
     "explanation_es":"Yuki es Infecciosa con Temp 39.4 y FC 112, ambos umbrales Críticos. Inicio Progresivo la coloca tercera. Importante: no hay Respuesta Rápida para Infecciosos.",
     "exp_selection_en":"Yuki goes third. She is Infectious Critical: HR 112 bpm (Abnormal) AND Temp 39.4°C (Critical, >39°C) — both must be met simultaneously. She is not Moderate: scenario 1 requires only Temp Abnormal (38–39°C), but her temperature is already Critical; scenario 2 requires Normal HR AND Temp Critical, but her HR is Abnormal. Among the Critical trio, her Progressive onset ranks below Chiara's and Marco's Sudden onset.",
     "exp_processes_en":"Stretcher (Infectious Critical and Non-Ambulatory). No Rapid Response: Yuki is Critical, but Rapid Response only applies to Cardiac and Pulmonary Critical — not Infectious.",
     "exp_destination_en":"Monitored Ward — not the Risk Ward. Infectious Critical goes to the Monitored Ward. Risk Ward is reserved for Cardiac and Pulmonary Critical. Do not assume Critical always means Risk Ward.",
     "exp_selection_es":"Yuki va tercera. Es Infecciosa Crítica: FC 112 lpm (Anormal) Y Temp 39.4°C (Crítica, >39°C) — ambas deben cumplirse simultáneamente. No es Moderada: el escenario 1 requiere solo Temp Anormal (38–39°C), pero su temperatura ya es Crítica; el escenario 2 requiere FC Normal Y Temp Crítica, pero su FC es Anormal. Entre los tres Críticos, su inicio Progresivo queda por debajo del Súbito de Chiara y Marco.",
     "exp_processes_es":"Camilla (Infecciosa Crítica y No Ambulatoria). No Respuesta Rápida: Yuki es Crítica, pero la Respuesta Rápida solo aplica a Cardiaco y Pulmonar Crítico — no a Infeccioso.",
     "exp_destination_es":"Sala Vigilada — no la Sala de Riesgo. Los Infecciosos Críticos van a la Sala Vigilada. La Sala de Riesgo está reservada para Cardiaco y Pulmonar Crítico. No asumir que Crítico siempre significa Sala de Riesgo."},

    {"pid":"P05","name":"David, 58M","group":1,
     "condition":"Neurological","hr":128,"bp":128,"spo2":97,"rr":14,"temp":36.9,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"David is Neurological, Alert with normal BP — that is Stable. However his onset is Sudden, so a Stable Neurological patient with Sudden onset goes to Monitored Ward, not General Ward.",
     "explanation_es":"David es Neurológico, Alerta con TA normal — Estable. Pero con inicio Súbito, un Neurológico Estable va a Sala Vigilada, no a Planta General.",
     "exp_selection_en":"David goes last. He is Neurological Stable. Neurological Critical requires Lethargic alertness — David is Oriented. Neurological Moderate requires Alertness Confused (David is Oriented) or BP High Critical (David's BP is 128 mmHg, Normal). His HR (128 bpm) is Abnormal, but heart rate does not affect Neurological risk. As the only Stable patient he ranks below all Critical and Moderate patients.",
     "exp_processes_en":"No additional processes. No Companion Bay: David is Accompanied and Stable — two of the required criteria — but Companion Bay explicitly excludes Neurological patients.",
     "exp_destination_en":"Monitored Ward. Neurological Stable with Sudden onset goes there. General Ward applies only with Progressive or Recurring onset.",
     "exp_selection_es":"David va último. Es Neurológico Estable. Neurológico Crítico requiere conciencia Letárgica — David está Orientado. Neurológico Moderado requiere conciencia Confusa (David está Orientado) o TA Crítica Alta (TA de David: 128 mmHg, Normal). Su FC (128 lpm) es Anormal, pero la frecuencia cardiaca no afecta el riesgo Neurológico. Como único paciente Estable, está por debajo de todos los Críticos y Moderados.",
     "exp_processes_es":"Sin procesos adicionales. No Sala de Acompañante: David está Acompañado y es Estable — dos de los criterios necesarios — pero la Sala de Acompañante excluye explícitamente a los pacientes Neurológicos.",
     "exp_destination_es":"Sala Vigilada. Neurológico Estable con inicio Súbito va allí. La Planta General aplica solo con inicio Progresivo o Recurrente."},

    # GROUP 2
    {"pid":"P06","name":"Stefan, 83M","group":2,
     "condition":"Pulmonary","hr":96,"bp":122,"spo2":88,"rr":32,"temp":39.2,
     "alertness":"Oriented","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Stefan is Pulmonary with SpO2 88% and RR 32 — both Critical. He is Alert with Sudden onset, placing him second. He needs Rapid Response and a Stretcher.",
     "explanation_es":"Stefan es Pulmonar con SpO2 88% y FR 32, ambos Críticos. Alerta con inicio Súbito, segundo en el orden. Necesita Respuesta Rápida y Camilla.",
     "exp_selection_en":"Stefan goes first. He is Pulmonary Critical via the combined scenario: SpO2 88% (Abnormal) AND RR 32/min (Critical, >30) — both must be present simultaneously. Among the two Critical patients, Stefan has Sudden onset while Nora has Progressive — Sudden takes priority regardless of alertness.",
     "exp_processes_en":"Rapid Response (Pulmonary Critical). Stretcher (Critical and Non-Ambulatory). No Interpreter: Stefan is Unaccompanied but Cooperative — Agitated is required.",
     "exp_destination_en":"Risk Ward (Pulmonary Critical always goes there). Monitored Ward would apply only if he were Pulmonary Moderate.",
     "exp_selection_es":"Stefan va primero. Es Pulmonar Crítico por el escenario combinado: SpO2 88% (Anormal) Y FR 32/min (Crítica, >30) — ambas deben darse simultáneamente. Entre los dos Críticos, Stefan tiene inicio Súbito y Nora Progresivo — el Súbito tiene prioridad independientemente de la conciencia.",
     "exp_processes_es":"Respuesta Rápida (Pulmonar Crítico). Camilla (Crítico y No Ambulatorio). No Intérprete: Stefan está Sin Acompañante pero es Cooperativo — se requiere Agitado.",
     "exp_destination_es":"Sala de Riesgo (Pulmonar Crítico siempre va allí). La Sala Vigilada aplicaría solo si fuera Pulmonar Moderado."},

    {"pid":"P07","name":"Nora, 35F","group":2,
     "condition":"Neurological","hr":134,"bp":162,"spo2":95,"rr":15,"temp":37.0,
     "alertness":"Lethargic","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Nora is Neurological and Lethargic — that alone makes her Critical. Progressive onset places her after Stefan. She goes to Risk Ward.",
     "explanation_es":"Nora es Neurológica y Letárgica, lo que por sí solo la hace Crítica. Inicio Progresivo la coloca después de Stefan. Va a Urgencias Médicas.",
     "exp_selection_en":"Nora goes second. She is Neurological Critical (Lethargic — the sole criterion for Neurological Critical). Her HR (134 — Critical) and BP (162 — Abnormal) are strong distractors: they do not affect Neurological risk. Stefan's Sudden onset places him first despite Nora being Lethargic — onset is checked before alertness in the tiebreak.",
     "exp_processes_en":"No additional processes. No Rapid Response: Neurological Critical does not qualify — Rapid Response is restricted to Cardiac and Pulmonary Critical only. No Stretcher: Ambulatory.",
     "exp_destination_en":"Risk Ward (Neurological Critical always goes there).",
     "exp_selection_es":"Nora va segunda. Es Neurológica Crítica (Letárgica — el único criterio para Neurológico Crítico). Su FC (134 — Crítica) y TA (162 — Anormal) son fuertes distractores: no afectan el riesgo Neurológico. El inicio Súbito de Stefan lo coloca primero aunque Nora sea Letárgica — el inicio se evalúa antes que la conciencia en el desempate.",
     "exp_processes_es":"Sin procesos adicionales. No Respuesta Rápida: Neurológico Crítico no cumple el criterio — la Respuesta Rápida está restringida a Cardiaco y Pulmonar Crítico. No Camilla: Ambulatoria.",
     "exp_destination_es":"Sala de Riesgo (Neurológico Crítico siempre va allí)."},

    {"pid":"P08","name":"Bruno, 77M","group":2,
     "condition":"Cardiac","hr":108,"bp":125,"spo2":92,"rr":16,"temp":36.7,
     "alertness":"Oriented","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Bruno is Cardiac with HR 108 — Moderate. His onset is Progressive, so he goes to Monitored Ward, not Risk Ward. Cardiac Moderate with Sudden onset would go to Risk Ward, but Progressive means Monitored.",
     "explanation_es":"Bruno es Cardiaco con FC 108, Moderado. Inicio Progresivo, va a Sala Vigilada. Si fuera Súbito iría a Urgencias Médicas, pero Progresivo significa Vigilada.",
     "exp_selection_en":"Bruno goes fourth. He is Cardiac Moderate (HR 108 — Abnormal). Not Critical: Cardiac Critical requires HR>130 (his is 108) or HR Abnormal AND BP Abnormal simultaneously — his BP (125) is Normal. His SpO2 (92% — Abnormal) is a distractor: SpO2 does not affect Cardiac risk. Among Moderate patients, his Progressive onset places him below Ingrid (Sudden) and above Felix (Recurring).",
     "exp_processes_en":"No additional processes. No Rapid Response: Cardiac qualifies on condition but requires Critical risk — Bruno is Moderate. No Interpreter: Accompanied and Cooperative — social criteria not met. No Companion Bay: Accompanied but Bruno is Moderate, not Stable.",
     "exp_destination_en":"Monitored Ward (Cardiac Moderate with Progressive onset). Risk Ward would apply only if his onset were Sudden.",
     "exp_selection_es":"Bruno va cuarto. Es Cardiaco Moderado (FC 108 — Anormal). No es Crítico: Cardiaco Crítico requiere FC>130 (la suya es 108) o FC Anormal Y TA Anormal simultáneamente — su TA (125) es Normal. Su SpO2 (92% — Anormal) es un distractor: la SpO2 no afecta el riesgo Cardiaco. Entre los Moderados, su inicio Progresivo lo sitúa por debajo de Ingrid (Súbito) y por encima de Felix (Recurrente).",
     "exp_processes_es":"Sin procesos adicionales. No Respuesta Rápida: Cardiaco cumple el criterio de condición pero requiere riesgo Crítico — Bruno es Moderado. No Intérprete: Acompañado y Cooperativo — criterios sociales no cumplidos. No Sala de Acompañante: Acompañado pero Bruno es Moderado, no Estable.",
     "exp_destination_es":"Sala Vigilada (Cardiaco Moderado con inicio Progresivo). La Sala de Riesgo aplicaría solo si su inicio fuera Súbito."},

    {"pid":"P09","name":"Felix, 69M","group":2,
     "condition":"Pulmonary","hr":84,"bp":118,"spo2":92,"rr":22,"temp":38.8,
     "alertness":"Oriented","onset":"Recurring","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Felix is Pulmonary with SpO2 92% — Moderate. Recurring onset ranks him after Bruno. He needs Interpreter support since he is Agitated and Unaccompanied.",
     "explanation_es":"Felix es Pulmonar con SpO2 92%, Moderado. Inicio Recurrente lo sitúa después de Bruno. Necesita Intérprete por estar Agitado y Sin Acompañante.",
     "exp_selection_en":"Felix goes last. He is Pulmonary Moderate (SpO2 92% — Abnormal AND RR 22/min — Abnormal; either alone is sufficient for Moderate). Not Critical: Pulmonary Critical requires SpO2<80% (his is 92%) or SpO2 Abnormal AND RR Critical (>30) — his RR is 22, only Abnormal. Among Moderate patients his Recurring onset places him last.",
     "exp_processes_en":"Interpreter (Pulmonary, Moderate, Agitated, Unaccompanied — all four criteria met). No Rapid Response: Pulmonary qualifies on condition but requires Critical risk — Felix is Moderate.",
     "exp_destination_en":"Monitored Ward (Pulmonary Moderate always goes there regardless of onset).",
     "exp_selection_es":"Felix P. es Pulmonar Moderado (RR 22/min (Abnormal)). Inicio Recurrente, conciencia Orientado.",
     "exp_processes_es":"Intérprete (Pulmonar, Moderado, Agitado, Sin Acompañante — los cuatro criterios cumplidos). No Respuesta Rápida: Pulmonar cumple el criterio de condición pero requiere riesgo Crítico — Felix es Moderado.",
     "exp_destination_es":"Sala Vigilada (Pulmonar Moderado siempre va allí independientemente del inicio)."},

    {"pid":"P10","name":"Ingrid, 50F","group":2,
     "condition":"Neurological","hr":126,"bp":138,"spo2":96,"rr":14,"temp":37.2,
     "alertness":"Confused","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Ingrid is Neurological and Confused — Moderate. Sudden onset ranks her first among Moderate patients. Important: even though she is Agitated and Unaccompanied, Neurological patients do not get Interpreter support.",
     "explanation_es":"Ingrid es Neurológica y Confusa, Moderada. Inicio Súbito la coloca primera entre Moderados. Importante: aunque esté Agitada y Sin Acompañante, los Neurológicos no reciben Intérprete.",
     "exp_selection_en":"Ingrid goes third. She is Neurological Moderate (Alertness Confused). Not Critical: Neurological Critical requires Lethargic — she is Confused. Among the three Moderate patients, her Sudden onset places her ahead of Bruno (Progressive) and Felix (Recurring).",
     "exp_processes_en":"No additional processes. No Interpreter: Ingrid is Agitated and Unaccompanied — the social criteria are met — but Interpreter requires Cardiac, Pulmonary, or Infectious condition. Neurological does not qualify.",
     "exp_destination_en":"Monitored Ward (Neurological Moderate always goes there regardless of onset).",
     "exp_selection_es":"Ingrid L. es Neurológico Moderado (Alertness: Confused (Abnormal)). Inicio Súbito, conciencia Confuso.",
     "exp_processes_es":"Sin procesos adicionales. No Intérprete: Ingrid está Agitada y Sin Acompañante — los criterios sociales se cumplen — pero el Intérprete requiere condición Cardiaca, Pulmonar o Infecciosa. Neurológico no cumple.",
     "exp_destination_es":"Sala Vigilada (Neurológico Moderado siempre va allí independientemente del inicio)."},

    # GROUP 3
    {"pid":"P11","name":"Rashid, 39M","group":3,
     "condition":"Trauma","hr":118,"bp":95,"spo2":96,"rr":20,"temp":38.9,
     "alertness":"Oriented","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Rashid is Trauma with HR 118 and Non-Ambulatory — both conditions together make him Critical. Sudden onset places him first. He needs a Stretcher and goes to Surgical Bay.",
     "explanation_es":"Rashid es Traumático con FC 118 y No Ambulatorio, ambas condiciones juntas lo hacen Crítico. Inicio Súbito lo coloca primero. Necesita Camilla y va a Quirófano.",
     "exp_selection_en":"Rashid goes first. He is Trauma Critical (HR 118 — Abnormal AND Non-Ambulatory — both required simultaneously). He is the only Critical patient in this group. All Critical patients rank above Moderate (Amara, Mia) and Stable (Priya, Carlos) regardless of onset or alertness.",
     "exp_processes_en":"Stretcher (Trauma Critical and Non-Ambulatory). No Rapid Response: Trauma does not qualify — Rapid Response is restricted to Cardiac and Pulmonary Critical only.",
     "exp_destination_en":"Surgical Bay (Trauma Critical always goes there).",
     "exp_selection_es":"Rashid va primero. Es Trauma Crítico (FC 118 — Anormal Y No Ambulatorio — ambos requeridos simultáneamente). Es el único paciente Crítico del grupo. Todos los Críticos tienen prioridad sobre Moderados (Amara, Mia) y Estables (Priya, Carlos) independientemente del inicio o la conciencia.",
     "exp_processes_es":"Camilla (Trauma Crítico y No Ambulatorio). No Respuesta Rápida: Trauma no cumple el criterio — la Respuesta Rápida está restringida a Cardiaco y Pulmonar Crítico.",
     "exp_destination_es":"Quirófano (Trauma Crítico siempre va allí)."},

    {"pid":"P12","name":"Amara, 23F","group":3,
     "condition":"Trauma","hr":88,"bp":112,"spo2":91,"rr":15,"temp":36.9,
     "alertness":"Oriented","onset":"Progressive","mobility":"Non-Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Amara is Trauma and Non-Ambulatory with normal HR — that is Moderate, not Critical. She still needs a Stretcher because Trauma Moderate Non-Ambulatory qualifies. Progressive onset places her second.",
     "explanation_es":"Amara es Traumática y No Ambulatoria con FC normal, Moderada. Sigue necesitando Camilla porque Trauma Moderado No Ambulatorio califica. Inicio Progresivo, segunda.",
     "exp_selection_en":"Amara goes second. She is Trauma Moderate (Non-Ambulatory). Not Critical: Trauma Critical requires HR Abnormal AND Non-Ambulatory simultaneously — her HR is 88 (Normal). Among the two Moderate patients, her Progressive onset places her above Mia's Recurring onset.",
     "exp_processes_en":"Stretcher (Trauma Moderate and Non-Ambulatory). No Companion Bay: Accompanied but Amara is Moderate, not Stable — Stable risk is required.",
     "exp_destination_en":"Surgical Bay (Trauma Moderate always goes there, same as Critical).",
     "exp_selection_es":"Amara va segunda. Es Trauma Moderada (No Ambulatoria). No es Crítica: Trauma Crítico requiere FC Anormal Y No Ambulatoria simultáneamente — su FC es 88 (Normal). Entre los dos Moderados, su inicio Progresivo la sitúa por encima del Recurrente de Mia.",
     "exp_processes_es":"Camilla (Trauma Moderado y No Ambulatoria). No Sala de Acompañante: Acompañada pero Amara es Moderada, no Estable — se requiere riesgo Estable.",
     "exp_destination_es":"Quirófano (Trauma Moderado siempre va allí, igual que el Crítico)."},

    {"pid":"P13","name":"Priya, 47F","group":3,
     "condition":"Neurological","hr":78,"bp":132,"spo2":96,"rr":32,"temp":36.8,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Priya is Neurological, Alert with normal BP — Stable. But Sudden onset for a Stable Neurological patient means Monitored Ward, not General Ward. She ranks before Mia because Stable Sudden beats Moderate Recurring.",
     "explanation_es":"Priya es Neurológica, Alerta con TA normal, Estable. Pero inicio Súbito para un Neurológico Estable significa Sala Vigilada. Va antes que Mia porque Estable Súbito supera Moderado Recurrente.",
     "exp_selection_en":"Priya goes fourth. She is Neurological Stable. Not Critical: Neurological Critical requires Lethargic — she is Oriented. Not Moderate: requires Confused alertness (she is Oriented) or BP>140 (hers is 132 — Normal). Her RR (32/min — Critical) is a strong distractor but does not affect Neurological risk. As a Stable patient she ranks below all Critical and Moderate patients.",
     "exp_processes_en":"No additional processes. No Companion Bay: Unaccompanied. Neurological patients are also explicitly excluded from Companion Bay.",
     "exp_destination_en":"Monitored Ward (Neurological Stable with Sudden onset). General Ward applies only with Progressive or Recurring onset.",
     "exp_selection_es":"Priya va cuarta. Es Neurológica Estable. No es Crítica: Neurológico Crítico requiere Letárgico — está Orientada. No es Moderada: requiere conciencia Confusa (está Orientada) o TA>140 (la suya es 132 — Normal). Su FR (32/min — Crítica) es un fuerte distractor pero no afecta el riesgo Neurológico. Como paciente Estable está por debajo de todos los Críticos y Moderados.",
     "exp_processes_es":"Sin procesos adicionales. No Sala de Acompañante: Sin Acompañante. Los pacientes Neurológicos también están explícitamente excluidos de la Sala de Acompañante.",
     "exp_destination_es":"Sala Vigilada (Neurológico Estable con inicio Súbito). La Planta General aplica solo con inicio Progresivo o Recurrente."},

    {"pid":"P14","name":"Carlos, 55M","group":3,
     "condition":"Cardiac","hr":88,"bp":125,"spo2":97,"rr":15,"temp":39.0,
     "alertness":"Oriented","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Carlos is Cardiac with normal HR and BP — Stable. Sudden onset means Monitored Ward. He is Agitated and Unaccompanied, so he needs Interpreter support.",
     "explanation_es":"Carlos es Cardiaco con FC y TA normales, Estable. Inicio Súbito significa Sala Vigilada. Está Agitado y Sin Acompañante, por lo que necesita Intérprete.",
     "exp_selection_en":"Carlos goes last. He is Cardiac Stable (HR 88 — Normal, BP 125 — Normal). Not Moderate: Cardiac Moderate requires HR Abnormal OR BP Abnormal — neither applies. His temperature (39.0°C) appears Critical at first glance, but the threshold is strictly >39°C — 39.0 is not above 39. Temperature does not affect Cardiac risk in any case.",
     "exp_processes_en":"Interpreter (Cardiac, Stable, Agitated, Unaccompanied — all four criteria met). No Rapid Response: Cardiac qualifies on condition but requires Critical risk — Carlos is Stable. No Companion Bay: Unaccompanied — Companion Bay requires Accompanied.",
     "exp_destination_en":"General Ward (Cardiac Stable with Progressive onset). Monitored Ward applies to Cardiac Stable only with Sudden onset.",
     "exp_selection_es":"Carlos va último. Es Cardiaco Estable (FC 88 — Normal, TA 125 — Normal). No es Moderado: Cardiaco Moderado requiere FC Anormal O TA Anormal — ninguna aplica. Su temperatura (39.0°C) parece Crítica a primera vista, pero el umbral es estrictamente >39°C — 39.0 no supera 39. La temperatura no afecta el riesgo Cardiaco en ningún caso.",
     "exp_processes_es":"Intérprete (Cardiaco, Estable, Agitado, Sin Acompañante — los cuatro criterios cumplidos). No Respuesta Rápida: Cardiaco cumple el criterio de condición pero requiere riesgo Crítico — Carlos es Estable. No Sala de Acompañante: Sin Acompañante — la Sala de Acompañante requiere Acompañado.",
     "exp_destination_es":"Planta General (Cardiaco Estable con inicio Progresivo). La Sala Vigilada aplica a Cardiaco Estable solo con inicio Súbito."},

    {"pid":"P15","name":"Mia, 66F","group":3,
     "condition":"Infectious","hr":82,"bp":148,"spo2":96,"rr":16,"temp":38.4,
     "alertness":"Oriented","onset":"Recurring","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Mia is Infectious with Temp 38.4 — Moderate. Recurring onset places her last. Moderate Infectious goes to General Ward.",
     "explanation_es":"Mia es Infecciosa con Temp 38.4, Moderada. Inicio Recurrente la coloca última. Infecciosa Moderada va a Planta General.",
     "exp_selection_en":"Mia goes third. She is Infectious Moderate (Temp 38.4°C — Abnormal, 38–39°C). Not Critical: Infectious Critical requires HR Abnormal AND Temp Critical (>39°C) — her HR is 82 (Normal) and temperature is only Abnormal. Her BP (148 — Abnormal) is a distractor: BP does not affect Infectious risk. Among Moderate patients, her Recurring onset places her below Amara (Progressive).",
     "exp_processes_en":"No additional processes. No Companion Bay: Accompanied, but Companion Bay explicitly excludes Infectious patients. No Interpreter: Cooperative.",
     "exp_destination_en":"General Ward (Infectious Moderate always goes there). Monitored Ward applies to Infectious Critical, not Moderate.",
     "exp_selection_es":"Mia va tercera. Es Infecciosa Moderada (Temp 38.4°C — Anormal, 38–39°C). No es Crítica: Infeccioso Crítico requiere FC Anormal Y Temp Crítica (>39°C) — su FC es 82 (Normal) y la temperatura es solo Anormal. Su TA (148 — Anormal) es un distractor: la TA no afecta el riesgo Infeccioso. Entre los Moderados, su inicio Recurrente la sitúa por debajo de Amara (Progresivo).",
     "exp_processes_es":"Sin procesos adicionales. No Sala de Acompañante: Acompañada, pero la Sala de Acompañante excluye explícitamente a los pacientes Infecciosos. No Intérprete: Cooperativa.",
     "exp_destination_es":"Planta General (Infeccioso Moderado siempre va allí). La Sala Vigilada aplica a Infeccioso Crítico, no Moderado."},
]

PATIENTS_B = [
    # GROUP 1
    {"pid":"P01","name":"James, 49M","group":1,
     "condition":"Cardiac","hr":138,"bp":105,"spo2":95,"rr":17,"temp":39.3,
     "alertness":"Lethargic","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"James is Cardiac with HR 138 — Critical. He is Lethargic with Sudden onset, placing him first. He needs Rapid Response and a Stretcher.",
     "explanation_es":"James es Cardiaco con FC 138, Crítico. Letárgico con inicio Súbito, primero en el orden. Necesita Respuesta Rápida y Camilla.",
     "exp_selection_en":"James goes first. He is Cardiac Critical (HR 138 — above the Critical threshold of 130). Among the three Critical patients, James and Fatima share Sudden onset. Between them, James is Lethargic while Fatima is Oriented — Lethargic takes priority. Thomas has Progressive onset and ranks third. His temperature (39.3°C — Critical) is a strong distractor but does not affect Cardiac risk.",
     "exp_processes_en":"Rapid Response (Cardiac Critical). Stretcher (Cardiac Critical and Non-Ambulatory). No Interpreter: Unaccompanied but Cooperative — Agitated is required. Also Interpreter only applies to Stable or Moderate patients.",
     "exp_destination_en":"Risk Ward (Cardiac Critical always goes there).",
     "exp_selection_es":"James va primero. Es Cardiaco Crítico (FC 138 — por encima del umbral Crítico de 130). Entre los tres Críticos, James y Fatima comparten inicio Súbito. Entre ellos, James es Letárgico y Fatima está Orientada — Letárgico tiene prioridad. Thomas tiene inicio Progresivo y queda tercero. Su temperatura (39.3°C — Crítica) es un fuerte distractor pero no afecta el riesgo Cardiaco.",
     "exp_processes_es":"Respuesta Rápida (Cardiaco Crítico). Camilla (Cardiaco Crítico y No Ambulatorio). No Intérprete: Sin Acompañante pero Cooperativo — se requiere Agitado. Además el Intérprete solo aplica a pacientes Estables o Moderados.",
     "exp_destination_es":"Sala de Riesgo (Cardiaco Crítico siempre va allí)."},

    {"pid":"P02","name":"Fatima, 38F","group":1,
     "condition":"Pulmonary","hr":128,"bp":118,"spo2":77,"rr":19,"temp":36.7,
     "alertness":"Oriented","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Fatima is Pulmonary with SpO2 88% — Critical. Alert with Sudden onset, she goes second after James. She needs Rapid Response and a Stretcher.",
     "explanation_es":"Fatima es Pulmonar con SpO2 88%, Crítica. Alerta con inicio Súbito, segunda después de James. Necesita Respuesta Rápida y Camilla.",
     "exp_selection_en":"Fatima goes second. She is Pulmonary Critical (SpO2 77% — below the Critical threshold of 80%). Among the Critical trio, Fatima and James share Sudden onset. James goes first because he is Lethargic; Fatima is Oriented. Thomas ranks third with Progressive onset.",
     "exp_processes_en":"Rapid Response (Pulmonary Critical). Stretcher (Critical and Non-Ambulatory). No Companion Bay: Accompanied but Critical — Companion Bay requires Stable risk.",
     "exp_destination_en":"Risk Ward (Pulmonary Critical always goes there).",
     "exp_selection_es":"Fatima va segunda. Es Pulmonar Crítica (SpO2 77% — por debajo del umbral Crítico del 80%). Entre los tres Críticos, Fatima y James comparten inicio Súbito. James va primero por ser Letárgico; Fatima está Orientada. Thomas queda tercero con inicio Progresivo.",
     "exp_processes_es":"Respuesta Rápida (Pulmonar Crítica). Camilla (Crítica y No Ambulatoria). No Sala de Acompañante: Acompañada pero Crítica — la Sala de Acompañante requiere riesgo Estable.",
     "exp_destination_es":"Sala de Riesgo (Pulmonar Crítica siempre va allí)."},

    {"pid":"P03","name":"Luca, 74M","group":1,
     "condition":"Cardiac","hr":114,"bp":122,"spo2":91,"rr":16,"temp":36.8,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Luca is Cardiac with HR 114 — Moderate. Sudden onset means he goes to Risk Ward. He needs Interpreter support.",
     "explanation_es":"Luca es Cardiaco con FC 114, Moderado. Inicio Súbito significa Urgencias Médicas. Necesita Intérprete.",
     "exp_selection_en":"Luca goes fourth. He is Cardiac Moderate (HR 114 — Abnormal). Not Critical: Cardiac Critical requires HR>130 (his is 114) or HR Abnormal AND BP Abnormal simultaneously — his BP (122) is Normal. His SpO2 (91% — exactly at the Normal threshold of ≥91%) does not contribute to any risk. As the only Moderate patient he ranks below all three Critical patients.",
     "exp_processes_en":"Interpreter (Cardiac, Moderate, Agitated, Unaccompanied — all four criteria met). No Rapid Response: Cardiac qualifies on condition but requires Critical risk — Luca is Moderate.",
     "exp_destination_en":"Risk Ward (Cardiac Moderate with Sudden onset). Monitored Ward applies to Cardiac Moderate only with Progressive or Recurring onset.",
     "exp_selection_es":"Luca va cuarto. Es Cardiaco Moderado (FC 114 — Anormal). No es Crítico: Cardiaco Crítico requiere FC>130 (la suya es 114) o FC Anormal Y TA Anormal simultáneamente — su TA (122) es Normal. Su SpO2 (91% — exactamente en el umbral Normal de ≥91%) no contribuye a ningún riesgo. Como único Moderado está por debajo de los tres Críticos.",
     "exp_processes_es":"Intérprete (Cardiaco, Moderado, Agitado, Sin Acompañante — los cuatro criterios cumplidos). No Respuesta Rápida: Cardiaco cumple el criterio de condición pero requiere riesgo Crítico — Luca es Moderado.",
     "exp_destination_es":"Sala de Riesgo (Cardiaco Moderado con inicio Súbito). La Sala Vigilada aplica a Cardiaco Moderado solo con inicio Progresivo o Recurrente."},

    {"pid":"P04","name":"Thomas, 61M","group":1,
     "condition":"Infectious","hr":116,"bp":110,"spo2":96,"rr":33,"temp":39.6,
     "alertness":"Oriented","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Thomas is Infectious with Temp 39.6 and HR 116 — Critical. Progressive onset places him third among Critical patients. No Rapid Response for Infectious — goes to Monitored Ward.",
     "explanation_es":"Thomas es Infeccioso con Temp 39.6 y FC 116, Crítico. Inicio Progresivo, tercero entre Críticos. Sin Respuesta Rápida para Infecciosos, va a Sala Vigilada.",
     "exp_selection_en":"Thomas goes third. He is Infectious Critical (HR 116 — Abnormal AND Temp 39.6°C — Critical). Not Moderate: scenario 1 requires Temp Abnormal (38–39°C) but his temperature is already Critical; scenario 2 requires Normal HR AND Temp Critical — his HR is Abnormal. His RR (33/min — Critical) is a distractor: RR does not affect Infectious risk. Among the Critical trio his Progressive onset places him after James and Fatima (both Sudden).",
     "exp_processes_en":"No additional processes. No Rapid Response: Thomas is Critical, but Rapid Response only applies to Cardiac and Pulmonary Critical — not Infectious. No Stretcher: Ambulatory. No Companion Bay: Accompanied but Critical. Infectious also excluded from Companion Bay.",
     "exp_destination_en":"Monitored Ward — not the Risk Ward. Infectious Critical always goes to the Monitored Ward. Risk Ward is reserved for Cardiac, Pulmonary, and Neurological Critical.",
     "exp_selection_es":"Thomas va tercero. Es Infeccioso Crítico (FC 116 — Anormal Y Temp 39.6°C — Crítica). No es Moderado: el escenario 1 requiere Temp Anormal (38–39°C) pero su temperatura ya es Crítica; el escenario 2 requiere FC Normal Y Temp Crítica — su FC es Anormal. Su FR (33/min — Crítica) es un distractor: la FR no afecta el riesgo Infeccioso. Entre los tres Críticos, su inicio Progresivo lo coloca después de James y Fatima (ambos Súbitos).",
     "exp_processes_es":"Sin procesos adicionales. No Respuesta Rápida: Thomas es Crítico, pero la Respuesta Rápida solo aplica a Cardiaco y Pulmonar Crítico — no a Infeccioso. No Camilla: Ambulatorio. No Sala de Acompañante: Acompañado pero Crítico. Infeccioso también excluido de la Sala de Acompañante.",
     "exp_destination_es":"Sala Vigilada — no la Sala de Riesgo. Infeccioso Crítico siempre va a la Sala Vigilada. La Sala de Riesgo está reservada para Cardiaco, Pulmonar y Neurológico Crítico."},

    {"pid":"P05","name":"Rosa, 41F","group":1,
     "condition":"Neurological","hr":76,"bp":130,"spo2":97,"rr":14,"temp":38.9,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Rosa is Neurological, Alert with normal BP — Stable. Sudden onset for a Stable Neurological patient means Monitored Ward, not General Ward.",
     "explanation_es":"Rosa es Neurológica, Alerta con TA normal, Estable. Inicio Súbito para un Neurológico Estable significa Sala Vigilada, no Planta General.",
     "exp_selection_en":"Rosa goes last. She is Neurological Stable. Not Critical: Neurological Critical requires Lethargic — she is Oriented. Not Moderate: requires Confused alertness (she is Oriented) or BP>140 — her BP is 130 (Normal). Her temperature (38.9°C — Abnormal) is a distractor: temperature does not affect Neurological risk.",
     "exp_processes_en":"No additional processes. No Companion Bay: Rosa is Accompanied and Stable — two criteria met — but Companion Bay explicitly excludes Neurological patients.",
     "exp_destination_en":"Monitored Ward (Neurological Stable with Sudden onset). General Ward applies only with Progressive or Recurring onset.",
     "exp_selection_es":"Rosa va última. Es Neurológica Estable. No es Crítica: Neurológico Crítico requiere Letárgico — está Orientada. No es Moderada: requiere conciencia Confusa (está Orientada) o TA>140 — su TA es 130 (Normal). Su temperatura (38.9°C — Anormal) es un distractor: la temperatura no afecta el riesgo Neurológico.",
     "exp_processes_es":"Sin procesos adicionales. No Sala de Acompañante: Rosa está Acompañada y es Estable — dos criterios cumplidos — pero la Sala de Acompañante excluye explícitamente a los pacientes Neurológicos.",
     "exp_destination_es":"Sala Vigilada (Neurológico Estable con inicio Súbito). La Planta General aplica solo con inicio Progresivo o Recurrente."},

    # GROUP 2
    {"pid":"P06","name":"Yara, 52F","group":2,
     "condition":"Pulmonary","hr":98,"bp":115,"spo2":76,"rr":28,"temp":38.7,
     "alertness":"Oriented","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Yara is Pulmonary with SpO2 87% — Critical. Alert with Sudden onset, she goes second after Ahmed. She needs Rapid Response and a Stretcher.",
     "explanation_es":"Yara es Pulmonar con SpO2 87%, Crítica. Alerta con inicio Súbito, segunda después de Ahmed. Necesita Respuesta Rápida y Camilla.",
     "exp_selection_en":"Yara goes second. She is Pulmonary Critical (SpO2 76% — below the Critical threshold of 80%). Among the Critical pair, both Ahmed and Yara have Sudden onset. Ahmed goes first because he is Lethargic; Yara is Oriented. The three Moderate patients (Vera, Clara, Oscar) all rank below.",
     "exp_processes_en":"Rapid Response (Pulmonary Critical). Stretcher (Critical and Non-Ambulatory). No Companion Bay: Accompanied but Critical — Stable risk is required.",
     "exp_destination_en":"Risk Ward (Pulmonary Critical always goes there).",
     "exp_selection_es":"Yara va segunda. Es Pulmonar Crítica (SpO2 76% — por debajo del umbral Crítico del 80%). Entre los dos Críticos, Ahmed y Yara tienen inicio Súbito. Ahmed va primero por ser Letárgico; Yara está Orientada. Los tres Moderados (Vera, Clara, Oscar) quedan por debajo.",
     "exp_processes_es":"Respuesta Rápida (Pulmonar Crítica). Camilla (Crítica y No Ambulatoria). No Sala de Acompañante: Acompañada pero Crítica — se requiere riesgo Estable.",
     "exp_destination_es":"Sala de Riesgo (Pulmonar Crítica siempre va allí)."},

    {"pid":"P07","name":"Ahmed, 85M","group":2,
     "condition":"Neurological","hr":82,"bp":168,"spo2":95,"rr":16,"temp":39.1,
     "alertness":"Lethargic","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Ahmed is Neurological and Lethargic — Critical regardless of other vitals. Lethargic with Sudden onset puts him first.",
     "explanation_es":"Ahmed es Neurológico y Letárgico, Crítico independientemente de otros signos. Letárgico con inicio Súbito lo coloca primero.",
     "exp_selection_en":"Ahmed goes first. He is Neurological Critical (Lethargic). Among the two Critical patients (Ahmed and Yara), both have Sudden onset — onset does not break the tie. Alertness is checked next: Ahmed is Lethargic, Yara is Oriented — Lethargic takes priority. His BP (168 — Abnormal) would trigger Neurological Moderate, but he is already Critical. Temp (39.1°C — Critical) is a distractor: temperature does not affect Neurological risk.",
     "exp_processes_en":"No additional processes. No Rapid Response: Neurological Critical does not qualify — only Cardiac and Pulmonary Critical. No Stretcher: Ambulatory.",
     "exp_destination_en":"Risk Ward (Neurological Critical always goes there).",
     "exp_selection_es":"Ahmed va primero. Es Neurológico Crítico (Letárgico). Entre los dos Críticos (Ahmed y Yara), ambos tienen inicio Súbito — el inicio no desempata. Se evalúa la conciencia: Ahmed es Letárgico, Yara está Orientada — Letárgico tiene prioridad. Su TA (168 — Anormal) activaría el Neurológico Moderado, pero ya es Crítico. Temp (39.1°C — Crítica) es un distractor: la temperatura no afecta el riesgo Neurológico.",
     "exp_processes_es":"Sin procesos adicionales. No Respuesta Rápida: Neurológico Crítico no cumple el criterio — solo Cardiaco y Pulmonar Crítico. No Camilla: Ambulatorio.",
     "exp_destination_es":"Sala de Riesgo (Neurológico Crítico siempre va allí)."},

    {"pid":"P08","name":"Clara, 44F","group":2,
     "condition":"Cardiac","hr":95,"bp":148,"spo2":96,"rr":31,"temp":36.8,
     "alertness":"Oriented","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Clara is Cardiac with BP 148 — Moderate. Progressive onset means Monitored Ward. Cardiac Moderate with Progressive onset goes to Monitored, not Risk Ward.",
     "explanation_es":"Clara es Cardiaca con TA 148, Moderada. Inicio Progresivo significa Sala Vigilada. Cardiaca Moderada con Progresivo va a Vigilada, no a Urgencias.",
     "exp_selection_en":"Clara goes fourth. She is Cardiac Moderate (BP 148 — Abnormal, above the threshold of 140). Not Critical: Cardiac Critical requires HR>130 (hers is 95 — Normal) or HR Abnormal AND BP Abnormal simultaneously — her HR is Normal. Her RR (31/min — Critical) is a strong distractor: RR does not affect Cardiac risk. Among Moderate patients her Progressive onset places her below Vera (Sudden) and above Oscar (Recurring).",
     "exp_processes_en":"No additional processes. No Rapid Response: Cardiac qualifies on condition but requires Critical risk — Clara is Moderate. No Interpreter: Accompanied and Cooperative — social criteria not met. No Companion Bay: Accompanied but Moderate, not Stable.",
     "exp_destination_en":"Monitored Ward (Cardiac Moderate with Progressive onset). Risk Ward would apply only if her onset were Sudden.",
     "exp_selection_es":"Clara va cuarta. Es Cardiaca Moderada (TA 148 — Anormal, por encima del umbral de 140). No es Crítica: Cardiaco Crítico requiere FC>130 (la suya es 95 — Normal) o FC Anormal Y TA Anormal simultáneamente — su FC es Normal. Su FR (31/min — Crítica) es un fuerte distractor: la FR no afecta el riesgo Cardiaco. Entre los Moderados, su inicio Progresivo la sitúa por debajo de Vera (Súbito) y por encima de Oscar (Recurrente).",
     "exp_processes_es":"Sin procesos adicionales. No Respuesta Rápida: Cardiaco cumple el criterio de condición pero requiere riesgo Crítico — Clara es Moderada. No Intérprete: Acompañada y Cooperativa — criterios sociales no cumplidos. No Sala de Acompañante: Acompañada pero Moderada, no Estable.",
     "exp_destination_es":"Sala Vigilada (Cardiaca Moderada con inicio Progresivo). La Sala de Riesgo aplicaría solo si su inicio fuera Súbito."},

    {"pid":"P09","name":"Oscar, 56M","group":2,
     "condition":"Pulmonary","hr":86,"bp":120,"spo2":91,"rr":23,"temp":39.0,
     "alertness":"Oriented","onset":"Recurring","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Oscar is Pulmonary with SpO2 91% — Moderate. Recurring onset places him last among Moderate patients. He needs Interpreter support.",
     "explanation_es":"Oscar es Pulmonar con SpO2 91%, Moderado. Inicio Recurrente lo coloca último entre Moderados. Necesita Intérprete.",
     "exp_selection_en":"Oscar goes last. He is Pulmonary Moderate (RR 23/min — Abnormal). His SpO2 is exactly 91% — the Normal threshold is ≥91%, so it does not contribute to Pulmonary risk. Not Critical: Pulmonary Critical requires SpO2<80% or SpO2 Abnormal AND RR Critical — SpO2 is Normal so neither scenario applies. His Recurring onset places him last among Moderate patients.",
     "exp_processes_en":"Interpreter (Pulmonary, Moderate, Agitated, Unaccompanied — all four criteria met). No Rapid Response: Pulmonary qualifies on condition but requires Critical risk — Oscar is Moderate.",
     "exp_destination_en":"Monitored Ward (Pulmonary Moderate always goes there regardless of onset).",
     "exp_selection_es":"Oscar va último. Es Pulmonar Moderado (FR 23/min — Anormal). Su SpO2 es exactamente 91% — el umbral Normal es ≥91%, por lo que no contribuye al riesgo Pulmonar. No es Crítico: Pulmonar Crítico requiere SpO2<80% o SpO2 Anormal Y FR Crítica — la SpO2 es Normal por lo que ningún escenario aplica. Su inicio Recurrente lo coloca último entre los Moderados.",
     "exp_processes_es":"Intérprete (Pulmonar, Moderado, Agitado, Sin Acompañante — los cuatro criterios cumplidos). No Respuesta Rápida: Pulmonar cumple el criterio de condición pero requiere riesgo Crítico — Oscar es Moderado.",
     "exp_destination_es":"Sala Vigilada (Pulmonar Moderado siempre va allí independientemente del inicio)."},

    {"pid":"P10","name":"Vera, 27F","group":2,
     "condition":"Neurological","hr":129,"bp":135,"spo2":97,"rr":15,"temp":37.1,
     "alertness":"Confused","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Vera is Neurological and Confused — Moderate. Sudden onset ranks her first among Moderate patients. Even though she is Agitated and Unaccompanied, Neurological patients do not get Interpreter support.",
     "explanation_es":"Vera es Neurológica y Confusa, Moderada. Inicio Súbito la coloca primera entre Moderados. Aunque Agitada y Sin Acompañante, los Neurológicos no reciben Intérprete.",
     "exp_selection_en":"Vera goes third. She is Neurological Moderate (Alertness Confused). Not Critical: Neurological Critical requires Lethargic — she is Confused. Her HR (129 — Abnormal) and BP (135 — Normal) do not affect Neurological risk. Among the three Moderate patients her Sudden onset places her first, above Clara (Progressive) and Oscar (Recurring).",
     "exp_processes_en":"No additional processes. No Interpreter: Vera is Agitated and Unaccompanied — the social criteria are met — but Interpreter requires Cardiac, Pulmonary, or Infectious condition. Neurological does not qualify.",
     "exp_destination_en":"Monitored Ward (Neurological Moderate always goes there).",
     "exp_selection_es":"Vera C. es Neurológico Moderado (Alertness: Confused (Abnormal)). Inicio Súbito, conciencia Confuso.",
     "exp_processes_es":"Sin procesos adicionales. No Intérprete: Vera está Agitada y Sin Acompañante — los criterios sociales se cumplen — pero el Intérprete requiere condición Cardiaca, Pulmonar o Infecciosa. Neurológico no cumple.",
     "exp_destination_es":"Sala Vigilada (Neurológico Moderado siempre va allí)."},

    # GROUP 3
    {"pid":"P11","name":"Paulo, 78M","group":3,
     "condition":"Trauma","hr":122,"bp":98,"spo2":91,"rr":21,"temp":37.0,
     "alertness":"Oriented","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Paulo is Trauma with HR 122 and Non-Ambulatory — Critical. Sudden onset places him first. He needs a Stretcher and goes to Surgical Bay.",
     "explanation_es":"Paulo es Traumático con FC 122 y No Ambulatorio, Crítico. Inicio Súbito, primero. Necesita Camilla y va a Quirófano.",
     "exp_selection_en":"Paulo goes first. He is Trauma Critical (HR 122 — Abnormal AND Non-Ambulatory — both required simultaneously). He is the only Critical patient in this group. All Critical patients rank above Moderate (Hana, Luis) and Stable (Igor, Zara) regardless of onset or alertness.",
     "exp_processes_en":"Stretcher (Trauma Critical and Non-Ambulatory). No Rapid Response: Trauma does not qualify — Rapid Response is restricted to Cardiac and Pulmonary Critical only.",
     "exp_destination_en":"Surgical Bay (Trauma Critical always goes there).",
     "exp_selection_es":"Paulo va primero. Es Trauma Crítico (FC 122 — Anormal Y No Ambulatorio — ambos requeridos simultáneamente). Es el único paciente Crítico del grupo. Todos los Críticos tienen prioridad sobre Moderados (Hana, Luis) y Estables (Igor, Zara) independientemente del inicio o la conciencia.",
     "exp_processes_es":"Camilla (Trauma Crítico y No Ambulatorio). No Respuesta Rápida: Trauma no cumple el criterio — la Respuesta Rápida está restringida a Cardiaco y Pulmonar Crítico.",
     "exp_destination_es":"Quirófano (Trauma Crítico siempre va allí)."},

    {"pid":"P12","name":"Hana, 36F","group":3,
     "condition":"Trauma","hr":85,"bp":118,"spo2":97,"rr":16,"temp":39.2,
     "alertness":"Oriented","onset":"Progressive","mobility":"Non-Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Hana is Trauma Non-Ambulatory with normal HR — Moderate. Non-Ambulatory alone makes Trauma Moderate, and she still needs a Stretcher. Progressive onset places her second.",
     "explanation_es":"Hana es Traumática No Ambulatoria con FC normal, Moderada. No Ambulatoria sola hace Trauma Moderado y sigue necesitando Camilla. Progresivo, segunda.",
     "exp_selection_en":"Hana goes second. She is Trauma Moderate (Non-Ambulatory). Not Critical: Trauma Critical requires HR Abnormal AND Non-Ambulatory simultaneously — her HR is 85 (Normal). Her temperature (39.2°C — Critical) is a distractor: temperature does not affect Trauma risk. Among Moderate patients her Progressive onset places her above Luis (Recurring).",
     "exp_processes_en":"Stretcher (Trauma Moderate and Non-Ambulatory). No Companion Bay: Accompanied but Moderate, not Stable — Stable risk is required.",
     "exp_destination_en":"Surgical Bay (Trauma Moderate always goes there, same as Critical).",
     "exp_selection_es":"Hana va segunda. Es Trauma Moderada (No Ambulatoria). No es Crítica: Trauma Crítico requiere FC Anormal Y No Ambulatoria simultáneamente — su FC es 85 (Normal). Su temperatura (39.2°C — Crítica) es un distractor: la temperatura no afecta el riesgo Trauma. Entre los Moderados, su inicio Progresivo la sitúa por encima de Luis (Recurrente).",
     "exp_processes_es":"Camilla (Trauma Moderado y No Ambulatoria). No Sala de Acompañante: Acompañada pero Moderada, no Estable — se requiere riesgo Estable.",
     "exp_destination_es":"Quirófano (Trauma Moderado siempre va allí, igual que el Crítico)."},

    {"pid":"P13","name":"Igor, 82M","group":3,
     "condition":"Neurological","hr":128,"bp":132,"spo2":96,"rr":15,"temp":36.9,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Igor is Neurological, Alert with BP 132 — Stable. Sudden onset means Monitored Ward. He ranks before Luis because Stable Sudden beats Moderate Recurring.",
     "explanation_es":"Igor es Neurológico, Alerta con TA 132, Estable. Inicio Súbito significa Sala Vigilada. Va antes que Luis porque Estable Súbito supera Moderado Recurrente.",
     "exp_selection_en":"Igor goes fourth. He is Neurological Stable. Not Critical: Neurological Critical requires Lethargic — he is Oriented. Not Moderate: requires Confused alertness (he is Oriented) or BP>140 — his BP is 132 (Normal). His HR (128 — Abnormal) is a distractor: HR does not affect Neurological risk.",
     "exp_processes_en":"No additional processes. No Companion Bay: Unaccompanied. Neurological patients are also explicitly excluded from Companion Bay.",
     "exp_destination_en":"Monitored Ward (Neurological Stable with Sudden onset). General Ward applies only with Progressive or Recurring onset.",
     "exp_selection_es":"Igor va cuarto. Es Neurológico Estable. No es Crítico: Neurológico Crítico requiere Letárgico — está Orientado. No es Moderado: requiere conciencia Confusa (está Orientado) o TA>140 — su TA es 132 (Normal). Su FC (128 — Anormal) es un distractor: la FC no afecta el riesgo Neurológico.",
     "exp_processes_es":"Sin procesos adicionales. No Sala de Acompañante: Sin Acompañante. Los pacientes Neurológicos también están explícitamente excluidos de la Sala de Acompañante.",
     "exp_destination_es":"Sala Vigilada (Neurológico Estable con inicio Súbito). La Planta General aplica solo con inicio Progresivo o Recurrente."},

    {"pid":"P14","name":"Zara, 48F","group":3,
     "condition":"Cardiac","hr":90,"bp":122,"spo2":97,"rr":33,"temp":36.7,
     "alertness":"Oriented","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Zara is Cardiac with normal HR and BP — Stable. Sudden onset means Monitored Ward. She is Agitated and Unaccompanied so she needs Interpreter support.",
     "explanation_es":"Zara es Cardiaca con FC y TA normales, Estable. Inicio Súbito significa Sala Vigilada. Agitada y Sin Acompañante, necesita Intérprete.",
     "exp_selection_en":"Zara goes last. She is Cardiac Stable (HR 90 — Normal, BP 122 — Normal). Not Moderate: Cardiac Moderate requires HR Abnormal OR BP Abnormal — neither applies. Her RR (33/min — Critical) is a strong distractor: RR does not affect Cardiac risk.",
     "exp_processes_en":"Interpreter (Cardiac, Stable, Agitated, Unaccompanied — all four criteria met). No Rapid Response: Cardiac qualifies on condition but requires Critical risk — Zara is Stable. No Companion Bay: Unaccompanied — Companion Bay requires Accompanied.",
     "exp_destination_en":"General Ward (Cardiac Stable with Progressive onset). Monitored Ward applies to Cardiac Stable only with Sudden onset.",
     "exp_selection_es":"Zara va última. Es Cardiaca Estable (FC 90 — Normal, TA 122 — Normal). No es Moderada: Cardiaco Moderado requiere FC Anormal O TA Anormal — ninguna aplica. Su FR (33/min — Crítica) es un fuerte distractor: la FR no afecta el riesgo Cardiaco.",
     "exp_processes_es":"Intérprete (Cardiaco, Estable, Agitada, Sin Acompañante — los cuatro criterios cumplidos). No Respuesta Rápida: Cardiaco cumple el criterio de condición pero requiere riesgo Crítico — Zara es Estable. No Sala de Acompañante: Sin Acompañante — la Sala de Acompañante requiere Acompañado.",
     "exp_destination_es":"Planta General (Cardiaca Estable con inicio Progresivo). La Sala Vigilada aplica a Cardiaco Estable solo con inicio Súbito."},

    {"pid":"P15","name":"Luis, 57M","group":3,
     "condition":"Infectious","hr":125,"bp":115,"spo2":96,"rr":17,"temp":38.6,
     "alertness":"Oriented","onset":"Recurring","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Luis is Infectious with Temp 38.6 — Moderate. Recurring onset places him last. Infectious Moderate goes to General Ward.",
     "explanation_es":"Luis es Infeccioso con Temp 38.6, Moderado. Inicio Recurrente lo coloca último. Infeccioso Moderado va a Planta General.",
     "exp_selection_en":"Luis goes third. He is Infectious Moderate (Temp 38.6°C — Abnormal, 38–39°C). Not Critical: Infectious Critical requires HR Abnormal AND Temp Critical (>39°C) — his temperature is only Abnormal (38.6°C). His HR (125 — Abnormal) meets one of the two Critical criteria, but both must be met simultaneously. Among Moderate patients his Recurring onset places him below Hana (Progressive).",
     "exp_processes_en":"No additional processes. No Companion Bay: Accompanied, but Companion Bay explicitly excludes Infectious patients. No Interpreter: Cooperative.",
     "exp_destination_en":"General Ward (Infectious Moderate always goes there). Monitored Ward applies to Infectious Critical, not Moderate.",
     "exp_selection_es":"Luis va tercero. Es Infeccioso Moderado (Temp 38.6°C — Anormal, 38–39°C). No es Crítico: Infeccioso Crítico requiere FC Anormal Y Temp Crítica (>39°C) — su temperatura es solo Anormal (38.6°C). Su FC (125 — Anormal) cumple uno de los dos criterios Críticos, pero ambos deben darse simultáneamente. Entre los Moderados, su inicio Recurrente lo sitúa por debajo de Hana (Progresivo).",
     "exp_processes_es":"Sin procesos adicionales. No Sala de Acompañante: Acompañado, pero la Sala de Acompañante excluye explícitamente a los pacientes Infecciosos. No Intérprete: Cooperativo.",
     "exp_destination_es":"Planta General (Infeccioso Moderado siempre va allí). La Sala Vigilada aplica a Infeccioso Crítico, no Moderado."},
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
