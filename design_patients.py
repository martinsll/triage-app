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
     "explanation_en":"Marco is critical because he is Cardiac with Heart Rate 142. He has Sudden onset and is Alert, so he goes second among the Critical patients.",
     "explanation_es":"Marco es crítico porque es cardíaco con una frecuencia cardíaca de 142. Tiene inicio Súbito y está orientado, por lo que va segundo entre los pacientes críticos.",
     "exp_selection_en":"Marco is cardiac critical because he has a heart rate of 142. Among critical patients, Marta and Yuki, he goes second because he is Sudden onset, so compared to Yuki, who is progressive, he has more priority. He has less than Marta because Marco is Oriented.",
     "exp_processes_en":"Rapid Response (Cardiac Critical). No Stretcher: Cardiac Critical qualifies on risk, but Marco is Ambulatory — both conditions must be met. No Interpreter: Marco is Agitated and Unaccompanied, which fulfils the social criteria, but Interpreter only applies to Stable or Moderate patients — Marco is Critical.",
     "exp_destination_en":"Marco goes to Risk Ward, since he is Cardiac Critical.",
     "exp_selection_es":"Marco es cardíaco crítico porque tiene una frecuencia cardíaca de 142. Entre los pacientes críticos, Marta y Yuki, va en segundo lugar porque su condición es de inicio súbito, por lo que, en comparación con Yuki, cuya condición es progresiva, tiene mayor prioridad. Tiene menos prioridad que Marta porque Marco está orientado.",
     "exp_processes_es":"Respuesta Rápida (Cardiaco Crítico). No Camilla: el riesgo Crítico Cardiaco cumple el criterio de riesgo, pero Marco es Ambulatorio — ambas condiciones son necesarias. No Intérprete: Marco está Agitado y Sin Acompañante, lo que cumple el criterio social, pero el Intérprete solo aplica a pacientes Estables o Moderados — Marco es Crítico.",
     "exp_destination_es":"Marco va a la Sala de Riesgo, ya que es un paciente Cardíaco Crítico.",},

    {"pid":"P02","name":"Marta, 28F","group":1,
     "condition":"Pulmonary","hr":92,"bp":115,"spo2":76,"rr":24,"temp":39.1,
     "alertness":"Lethargic","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Marta is Pulmonary with Oxygen Saturation87%, so she is Critical. She is Lethargic with Sudden onset, which puts her first among all patients. She also needs a Stretcher and Rapid Response.",
     "explanation_es":"Marta es Pulmonar con SpO2 87%, por lo que es Crítica. Está Letárgica con inicio Súbito, lo que la pone primera. También necesita Camilla y Respuesta Rápida.",
     "exp_selection_en":"Marta is pulmonary critical, becuase of Oxygen Saturation 76%. Among critical patients, Marco and Yuki, she has more priority since she is Sudden with Lethargic alert.",
     "exp_processes_en":"Rapid Response (Pulmonary Critical). Stretcher (Critical and Non-Ambulatory). Although she is Accompanied, Companion Bay requires Stable risk — Marta is Critical.",
     "exp_destination_en":"Marta goes to Risk Ward, since she is Pulmonary Critical.",
     "exp_selection_es": "Marta es pulmonar crítica debido a una saturación de oxígeno del 76%. Entre los pacientes críticos, Marco y Yuki, tiene mayor prioridad porque presenta un inicio súbito con estado de alerta letárgico.",
     "exp_processes_es":"Respuesta Rápida (Pulmonar Crítico). Camilla (Crítico y No Ambulatoria). Aunque está Acompañada, la Sala de Acompañante requiere riesgo Estable — Marta es Crítica.",
     "exp_destination_es":"Marta va a la Sala de Riesgo, ya que es una paciente pulmonar crítica.",},

    {"pid":"P03","name":"Elena, 42F","group":1,
     "condition":"Cardiac","hr":115,"bp":118,"spo2":95,"rr":32,"temp":37.0,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Elena is Cardiac with heart rate 115, which makes her Moderate. With Sudden onset, Cardiac Moderate goes to Risk Ward. She also needs Interpreter support.",
     "explanation_es":"Elena es Cardiaca con frecuencia cardíaca 115, por lo que es Moderada. Con inicio Súbito, Cardiaca Moderada va a Urgencias Médicas. También necesita Intérprete.",
     "exp_selection_en":"Elena goes fourth since she is Cardiac Moderate, because of her abnormal heart rate. She ranks below the three critical patients but above David, who is stable. ",
     "exp_processes_en":"Interpreter (Cardiac, Moderate risk, Agitated, Unaccompanied — all four criteria met). No Rapid Response: Cardiac qualifies on condition, but Rapid Response requires Critical risk — Elena is Moderate.",
     "exp_destination_en":"Elena goes to Risk Ward, because she is Cardiac Moderate with Sudden onset.",
     "exp_selection_es": "Elena va en cuarto lugar ya que es Cardíaca Moderada debido a su frecuencia cardíaca anormal. Se ubica por debajo de los tres pacientes críticos, pero por encima de David, que está estable.",
     "exp_processes_es":"Intérprete (Cardiaco, riesgo Moderado, Agitada, Sin Acompañante — los cuatro criterios cumplidos). No Respuesta Rápida: Cardiaco cumple el criterio de condición, pero la Respuesta Rápida requiere riesgo Crítico — Elena es Moderada.",
     "exp_destination_es":"Elena va a la Sala de Riesgo porque es Cardíaca Moderada con inicio súbito.",},

    {"pid":"P04","name":"Yuki, 61F","group":1,
     "condition":"Infectious","hr":112,"bp":148,"spo2":95,"rr":18,"temp":39.4,
     "alertness":"Oriented","onset":"Progressive","mobility":"Non-Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Yuki is Infectious with Temperature 39.4 and Heart Rate 112, so she is Critical. Progressive onset places her third among Critical patients. Important: no Rapid Response for Infectious — that only applies to Cardiac and Pulmonary.",
     "explanation_es":"Yuki es Infecciosa con Temperatura 39.4 y frecuencia cardíaca 112, ambos umbrales Críticos. Inicio Progresivo la coloca tercera. Importante: no hay Respuesta Rápida para Infecciosos.",
     "exp_selection_en":"Yuki goes third because she is Infectious Critical, since she has an abnormal heart rate and a critical temperature. Her progressive onset ranks her below Marta and Marco.",
     "exp_processes_en":"Stretcher (Infectious Critical and Non-Ambulatory). No Rapid Response: Yuki is Critical, but Rapid Response only applies to Cardiac and Pulmonary Critical — not Infectious.",
     "exp_destination_en":"Yuki goes to Monitored Ward, because she is Infectious Critical. Do not assume Critical always means Risk Ward.",
     "exp_selection_es":"Yuki va en tercer lugar porque es Infecciosa Crítica, ya que tiene una frecuencia cardíaca anormal y una temperatura crítica. Su inicio progresivo la coloca por debajo de Marta y Marco.",
     "exp_processes_es":"Camilla (Infecciosa Crítica y No Ambulatoria). No Respuesta Rápida: Yuki es Crítica, pero la Respuesta Rápida solo aplica a Cardiaco y Pulmonar Crítico — no a Infeccioso.",
     "exp_destination_es":"Yuki va a la Sala Monitorizada porque es Infecciosa Crítica. No asumas que Crítico siempre significa Sala de Riesgo."},

    {"pid":"P05","name":"David, 58M","group":1,
     "condition":"Neurological","hr":128,"bp":128,"spo2":97,"rr":14,"temp":36.9,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"David is Neurological, Alert with normal blood pressure, that is Stable. However his onset is Sudden, so a Stable Neurological patient with Sudden onset goes to Monitored Ward, not General Ward.",
     "explanation_es":"David es Neurológico, Alerta con Tensión arterial normal, es Estable. Pero con inicio Súbito, un Neurológico Estable va a Sala Vigilada, no a Planta General.",
     "exp_selection_en":"David goes last because he is neurological stable, since he is alertness oriented, and his blood pressure is normal. Heart rate does not affect neurological patients.",
     "exp_processes_en":"No additional processes. No Companion Bay: David is Accompanied and Stable — two of the required criteria — but Companion Bay explicitly excludes Neurological patients.",
     "exp_destination_en":"David goes to Monitored Ward, because he is Neurological Stable with Sudden onset.",
     "exp_selection_es":"David va al final porque es neurológico estable, ya que está orientado en su estado de alerta y su tensión arterial es normal. La frecuencia cardíaca no afecta a los pacientes neurológicos.",
     "exp_processes_es":"Sin procesos adicionales. No Sala de Acompañante: David está Acompañado y es Estable — dos de los criterios necesarios — pero la Sala de Acompañante excluye explícitamente a los pacientes Neurológicos.",
     "exp_destination_es":"David va a la Sala Vigilada porque es Neurológico Estable con inicio súbito."},

    # GROUP 2
    {"pid":"P06","name":"Leo, 83M","group":2,
     "condition":"Pulmonary","hr":96,"bp":122,"spo2":88,"rr":32,"temp":39.2,
     "alertness":"Oriented","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Leo is Pulmonary with Oxygen Saturation88% and Respiratory Rate 32, both Critical. He is Alert with Sudden onset, placing him second. He needs Rapid Response and a Stretcher.",
     "explanation_es":"Leo es Pulmonar con SpO2 88% y Frecuencia Respiratoria 32, ambos Críticos. Alerta con inicio Súbito, segundo en el orden. Necesita Respuesta Rápida y Camilla.",
     "exp_selection_en": "Leo goes first because he is pulmonary critical as he has abnormal oxygen saturation with critical respiratory rate. Among the critical patients, Leo is more prior because he has sudden onset while Nora's is progressive.",
     "exp_processes_en":"Rapid Response (Pulmonary Critical). Stretcher (Critical and Non-Ambulatory). No Interpreter: Leo is Unaccompanied but Cooperative — Agitated is required.",
     "exp_destination_en":"Leo goes to Risk Ward as he is Pulmonary Critical.",
     "exp_selection_es":"Leo va primero porque es Pulmonar Crítico, ya que tiene una saturación de oxígeno anormal junto con una frecuencia respiratoria crítica. Entre los pacientes críticos, Leo tiene mayor prioridad porque su condición es de inicio súbito, mientras que la de Nora es progresiva.",
     "exp_processes_es":"Respuesta Rápida (Pulmonar Crítico). Camilla (Crítico y No Ambulatorio). No Intérprete: Leo está Sin Acompañante pero es Cooperativo — se requiere Agitado.",
     "exp_destination_es":"Leo va a la Sala de Riesgo porque es Pulmonar Crítico."},

    {"pid":"P07","name":"Nora, 35F","group":2,
     "condition":"Neurological","hr":134,"bp":162,"spo2":95,"rr":15,"temp":37.0,
     "alertness":"Lethargic","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Nora is Neurological and Lethargic, that alone makes her Critical. Progressive onset places her after Leo. She goes to Risk Ward.",
     "explanation_es":"Nora es Neurológica y Letárgica, lo que por sí solo la hace Crítica. Inicio Progresivo la coloca después de Leo. Va a Urgencias Médicas.",
     "exp_selection_en":"Nora is a critical patient since she is Lethargic, which for neurological patients is enough to be considered critical. Her progressive onset ranks her right after Leo, who is sudden.",
     "exp_processes_en":"No additional processes. No Rapid Response: Neurological Critical does not qualify — Rapid Response is restricted to Cardiac and Pulmonary Critical only. No Stretcher: Ambulatory.",
     "exp_destination_en":"Nora goes to Risk Ward because she is Neurological Critical.",
     "exp_selection_es":"Nora es paciente crítica porque está letárgica, lo cual, para pacientes neurológicos, es suficiente para ser considerada crítica. Su inicio progresivo la coloca justo después de Leo, cuya condición es súbita.",
     "exp_processes_es":"Sin procesos adicionales. No Respuesta Rápida: Neurológico Crítico no cumple el criterio — la Respuesta Rápida está restringida a Cardiaco y Pulmonar Crítico. No Camilla: Ambulatoria.",
     "exp_destination_es":"Nora va a la Sala de Riesgo porque es Neurológica Crítica."},

    {"pid":"P08","name":"Bruno, 77M","group":2,
     "condition":"Cardiac","hr":108,"bp":125,"spo2":92,"rr":16,"temp":36.7,
     "alertness":"Oriented","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Bruno is Cardiac with Heart Rate108, which isModerate. His onset is Progressive, so he goes to Monitored Ward, not Risk Ward. Cardiac Moderate with Sudden onset would go to Risk Ward, but Progressive means Monitored.",
     "explanation_es":"Bruno es Cardiaco con frecuencia cardíaca 108, Moderado. Inicio Progresivo, va a Sala Vigilada. Si fuera Súbito iría a Urgencias Médicas, pero Progresivo significa Vigilada.",
     "exp_selection_en":"Bruno goes fourth because he is cardiac with abnormal heart rate, which makes him moderate. He would be critical if his blood pressure was abnormal, but it’s normal. Oxygen Saturation does not affect Cardiac patients. Among Moderate patients, his Progressive onset places him below Ingrid, who is Sudden, and above Felix who is recurring.",
     "exp_processes_en":"No additional processes. No Rapid Response: Cardiac qualifies on condition but requires Critical risk — Bruno is Moderate. No Interpreter: Accompanied and Cooperative — social criteria not met. No Companion Bay: Accompanied but Bruno is Moderate, not Stable.",
     "exp_destination_en":"Bruno goes to Monitored Ward, because he is Cardiac Moderate with Progressive onset.",
     "exp_selection_es":"Bruno va en cuarto lugar porque es cardíaco con frecuencia cardíaca anormal, lo que lo convierte en moderado. Sería crítico si su Tensión Arterial fuera anormal, pero es normal. La saturación de oxígeno no afecta a los pacientes cardíacos. Entre los pacientes moderados, su inicio progresivo lo coloca por debajo de Ingrid, que es súbita, y por encima de Felix, que es recurrente.",
     "exp_processes_es":"Sin procesos adicionales. No Respuesta Rápida: Cardiaco cumple el criterio de condición pero requiere riesgo Crítico — Bruno es Moderado. No Intérprete: Acompañado y Cooperativo — criterios sociales no cumplidos. No Sala de Acompañante: Acompañado pero Bruno es Moderado, no Estable.",
     "exp_destination_es":"Bruno va a la Sala vigilada porque es Cardíaco Moderado con inicio progresivo.",},

    {"pid":"P09","name":"Felix, 69M","group":2,
     "condition":"Pulmonary","hr":84,"bp":118,"spo2":92,"rr":22,"temp":38.8,
     "alertness":"Oriented","onset":"Recurring","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Felix is Pulmonary with Oxygen Saturation 92%, Moderate. Recurring onset ranks him after Bruno. He needs Interpreter support since he is Agitated and Unaccompanied.",
     "explanation_es":"Felix es Pulmonar con SpO2 92%, Moderado. Inicio Recurrente lo sitúa después de Bruno. Necesita Intérprete por estar Agitado y Sin Acompañante.",
     "exp_selection_en":"Felix goes last because he is pulmonary moderate with abnormal oxygen saturation and abnormal respiratory rate. Each of the conditions alone would make him moderate. Among Moderate patients his Recurring onset places him last.",
     "exp_processes_en":"Interpreter (Pulmonary, Moderate, Agitated, Unaccompanied — all four criteria met). No Rapid Response: Pulmonary qualifies on condition but requires Critical risk — Felix is Moderate.",
     "exp_destination_en":"Felix is Pulmonary Moderate so he goes to Monitored Ward.",
     "exp_selection_es":"Felix va al final porque es Pulmonar Moderado con saturación de oxígeno anormal y frecuencia respiratoria anormal. Cada una de las condiciones por sí sola lo convierte en moderado. Entre los pacientes moderados, su inicio recurrente lo coloca en último lugar.",
     "exp_processes_es":"Intérprete (Pulmonar, Moderado, Agitado, Sin Acompañante — los cuatro criterios cumplidos). No Respuesta Rápida: Pulmonar cumple el criterio de condición pero requiere riesgo Crítico — Felix es Moderado.",
     "exp_destination_es":"Felix es Pulmonar Moderado, por lo que va a la Sala vigilada."},

    {"pid":"P10","name":"Ingrid, 50F","group":2,
     "condition":"Neurological","hr":126,"bp":138,"spo2":96,"rr":14,"temp":37.2,
     "alertness":"Confused","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Ingrid is Neurological and Confused, Moderate. Sudden onset ranks her first among Moderate patients. Important: even though she is Agitated and Unaccompanied, Neurological patients do not get Interpreter support.",
     "explanation_es":"Ingrid es Neurológica y Confusa, Moderada. Inicio Súbito la coloca primera entre Moderados. Importante: aunque esté Agitada y Sin Acompañante, los Neurológicos no reciben Intérprete.",
     "exp_selection_en":"Ingrid goes third. She is Neurological Moderate because of her Alertness Confused. Among the three Moderate patients, her Sudden onset places her ahead of Bruno  and Felix.",
     "exp_processes_en":"No additional processes. No Interpreter: Ingrid is Agitated and Unaccompanied — the social criteria are met — but Interpreter requires Cardiac, Pulmonary, or Infectious condition. Neurological does not qualify.",
     "exp_destination_en":"Ingrid is Neurological Moderate so she goes to Monitored Ward.",
     "exp_selection_es":"Ingrid va en tercer lugar. Es Neurológica Moderada debido a su estado de alerta confuso. Entre los tres pacientes moderados, su inicio súbito la coloca por delante de Bruno y Felix.",
     "exp_processes_es":"Sin procesos adicionales. No Intérprete: Ingrid está Agitada y Sin Acompañante — los criterios sociales se cumplen — pero el Intérprete requiere condición Cardiaca, Pulmonar o Infecciosa. Neurológico no cumple.",
     "exp_destination_es":"Ingrid es Neurológica Moderada, por lo que va a la Sala vigilada."},

    # GROUP 3
    {"pid":"P11","name":"Rashid, 39M","group":3,
     "condition":"Trauma","hr":118,"bp":95,"spo2":96,"rr":20,"temp":38.9,
     "alertness":"Oriented","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Rashid is Trauma with Heart Rate 118 and Non-Ambulatory, both conditions together make him Critical. Sudden onset places him first. He needs a Stretcher and goes to Surgical Bay.",
     "explanation_es":"Rashid es Traumático con frecuencia cardíaca 118 y No Ambulatorio, ambas condiciones juntas lo hacen Crítico. Inicio Súbito lo coloca primero. Necesita Camilla y va a Quirófano.",
     "exp_selection_en":"Rashid goes first. He is Trauma Critical because his heart rate is abnormal and he is non-ambulatory. He is the only Critical patient in this group, making him the most prior patient.",
     "exp_processes_en":"Stretcher (Trauma Critical and Non-Ambulatory). No Rapid Response: Trauma does not qualify — Rapid Response is restricted to Cardiac and Pulmonary Critical only.",
     "exp_destination_en":"Rashid is Trauma Critical so he goes to Surgical Bay.",
     "exp_selection_es":"Rashid va primero. Es Trauma Crítico porque su frecuencia cardíaca es anormal y es no ambulatorio. Es el único paciente crítico en este grupo, lo que lo convierte en el paciente con mayor prioridad.",
     "exp_processes_es":"Camilla (Trauma Crítico y No Ambulatorio). No Respuesta Rápida: Trauma no cumple el criterio — la Respuesta Rápida está restringida a Cardiaco y Pulmonar Crítico.",
     "exp_destination_es":"Rashid es Trauma Crítico, por lo que va al Quirófano."},

    {"pid":"P12","name":"Amara, 23F","group":3,
     "condition":"Trauma","hr":88,"bp":112,"spo2":91,"rr":15,"temp":36.9,
     "alertness":"Oriented","onset":"Progressive","mobility":"Non-Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Amara is Trauma and Non-Ambulatory with normal heart rate, that is Moderate, not Critical. She still needs a Stretcher because Trauma Moderate Non-Ambulatory qualifies. Progressive onset places her second.",
     "explanation_es":"Amara es Traumática y No Ambulatoria con frecuencia cardíaca normal, Moderada. Sigue necesitando Camilla porque Trauma Moderado No Ambulatorio califica. Inicio Progresivo, segunda.",
     "exp_selection_en":"Amara goes second because she is Trauma Moderate since she is non-ambulatory with normal heart rate. Among the two Moderate patients, her progressive onset places her above Mia's recurring onset.",
     "exp_processes_en":"Stretcher (Trauma Moderate and Non-Ambulatory). No Companion Bay: Accompanied but Amara is Moderate, not Stable — Stable risk is required.",
     "exp_destination_en":"Amara goes to Surgical Bay because she is Trauma Moderate.",
     "exp_selection_es":"Amara va en segundo lugar porque es Trauma Moderado, ya que es no ambulatorio pero tiene una frecuencia cardíaca normal. Entre los dos pacientes moderados, su inicio progresivo la coloca por encima del inicio recurrente de Mia.",
     "exp_processes_es":"Camilla (Trauma Moderado y No Ambulatoria). No Sala de Acompañante: Acompañada pero Amara es Moderada, no Estable — se requiere riesgo Estable.",
     "exp_destination_es":"Amara va al Área Quirúrgica porque es Trauma Moderado."},

    {"pid":"P13","name":"Priya, 47F","group":3,
     "condition":"Neurological","hr":78,"bp":132,"spo2":96,"rr":32,"temp":36.8,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Priya is Neurological, Alert with normal blood pressure, she is Stable. But Sudden onset for a Stable Neurological patient means Monitored Ward, not General Ward. She ranks before Mia because Stable Sudden beats Moderate Recurring.",
     "explanation_es":"Priya es Neurológica, Alerta con Tensión arterial normal, es Estable. Pero inicio Súbito para un Neurológico Estable significa Sala Vigilada. Va antes que Mia porque Estable Súbito supera Moderado Recurrente.",
     "exp_selection_en":"Priya goes fourth. She is Neurological Stable because she is oriented with normal blood pressure. Respiratory rate does not affect Neurological risk. As a Stable patient she ranks below all Critical and Moderate patients. She has sudden onset, which puts her before Carlos, who is progressive.",
     "exp_processes_en":"No additional processes. No Companion Bay: Unaccompanied. Neurological patients are also explicitly excluded from Companion Bay.",
     "exp_destination_en":"Priya is Neurological Stable with Sudden onset, so she goes to Monitored Ward.",
     "exp_selection_es":"Priya va en cuarto lugar. Es Neurológica Estable porque está orientada y su Tensión Arterial es normal. La frecuencia respiratoria no afecta el riesgo neurológico. Como paciente estable, se ubica por debajo de todos los pacientes críticos y moderados. Tiene un inicio súbito, lo que la coloca antes que Carlos, cuya condición es progresiva.",
     "exp_processes_es":"Sin procesos adicionales. No Sala de Acompañante: Sin Acompañante. Los pacientes Neurológicos también están explícitamente excluidos de la Sala de Acompañante.",
     "exp_destination_es":"Priya es Neurológica Estable con inicio súbito, por lo que va a la Sala vigilada."},

    {"pid":"P14","name":"Carlos, 55M","group":3,
     "condition":"Cardiac","hr":88,"bp":125,"spo2":97,"rr":15,"temp":39.0,
     "alertness":"Oriented","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Carlos is Cardiac with normal Heart Rate and blood pressure, Stable. Sudden onset means Monitored Ward. He is Agitated and Unaccompanied, so he needs Interpreter support.",
     "explanation_es":"Carlos es Cardiaco con frecuencia cardíaca y tensión arterial normales, Estable. Inicio Súbito significa Sala Vigilada. Está Agitado y Sin Acompañante, por lo que necesita Intérprete.",
     "exp_selection_en":"Carlos goes last, because he is Cardiac Stable, with normal heart rate and blood pressure. Temperature does not affect Cardiac risk in any case. His progressive onset puts him last.",
     "exp_processes_en":"Interpreter (Cardiac, Stable, Agitated, Unaccompanied — all four criteria met). No Rapid Response: Cardiac qualifies on condition but requires Critical risk — Carlos is Stable. No Companion Bay: Unaccompanied — Companion Bay requires Accompanied.",
     "exp_destination_en":"Carlos goes to General Ward because he is Cardiac Stable with progressive onset.",
     "exp_selection_es":"Carlos va al final porque es Cardíaco Estable, con frecuencia cardíaca y Tensión Arterial normales. La temperatura no afecta el riesgo cardíaco en ningún caso. Su inicio progresivo lo coloca al final.",
     "exp_processes_es":"Intérprete (Cardiaco, Estable, Agitado, Sin Acompañante — los cuatro criterios cumplidos). No Respuesta Rápida: Cardiaco cumple el criterio de condición pero requiere riesgo Crítico — Carlos es Estable. No Sala de Acompañante: Sin Acompañante — la Sala de Acompañante requiere Acompañado.",
     "exp_destination_es":"Carlos va a Planta General porque es Cardíaco Estable con inicio progresivo."},

    {"pid":"P15","name":"Mia, 66F","group":3,
     "condition":"Infectious","hr":82,"bp":148,"spo2":96,"rr":16,"temp":38.4,
     "alertness":"Oriented","onset":"Recurring","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Mia is Infectious with Temp 38.4, so she is Moderate. Recurring onset places her last. Moderate Infectious goes to General Ward.",
     "explanation_es":"Mia es Infecciosa con Temp 38.4, es Moderada. Inicio Recurrente la coloca última. Infecciosa Moderada va a Planta General.",
     "exp_selection_en":"Mia goes third. She is Infectious Moderate because of her abnormal temperature. Blood pressure does not affect Infectious risk. Among Moderate patients, her Recurring onset places her below Amara, who is Progressive.",
     "exp_processes_en":"No additional processes. No Companion Bay: Accompanied, but Companion Bay explicitly excludes Infectious patients. No Interpreter: Cooperative.",
     "exp_destination_en":"Mia is Infectious Moderate, so she goes to General Ward.",
     "exp_selection_es":"Mia va en tercer lugar. Es Infecciosa Moderada debido a su temperatura anormal. La Tensión Arterial no afecta el riesgo infeccioso. Entre los pacientes moderados, su inicio recurrente la coloca por debajo de Amara, cuya condición es progresiva.",
     "exp_processes_es":"Sin procesos adicionales. No Sala de Acompañante: Acompañada, pero la Sala de Acompañante excluye explícitamente a los pacientes Infecciosos. No Intérprete: Cooperativa.",
     "exp_destination_es":"Mia es Infecciosa Moderada, por lo que va a Planta General."},
]

PATIENTS_B = [
    # GROUP 1
    {"pid":"P01","name":"Alex, 49M","group":1,
     "condition":"Cardiac","hr":138,"bp":105,"spo2":95,"rr":17,"temp":39.3,
     "alertness":"Lethargic","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Alex is Cardiac with HR 138 — Critical. He is Lethargic with Sudden onset, placing him first. He needs Rapid Response and a Stretcher.",
     "explanation_es":"Alex es Cardiaco con FC 138, Crítico. Letárgico con inicio Súbito, primero en el orden. Necesita Respuesta Rápida y Camilla.",
     "exp_selection_en":"Slot 1: Alex — Cardiac Critical — Sudden — Lethargic",
     "exp_processes_en":"Rapid Response (Cardiac Critical). Stretcher (Cardiac Critical and Non-Ambulatory). No Interpreter: Unaccompanied but Cooperative — Agitated is required. Also Interpreter only applies to Stable or Moderate patients.",
     "exp_destination_en":"Cardiac Critical → Risk Ward",
     "exp_selection_es":"Ranura 1: Alex — Cardiaco Crítico — Súbito — Letárgico",
     "exp_processes_es":"Respuesta Rápida (Cardiaco Crítico). Camilla (Cardiaco Crítico y No Ambulatorio). No Intérprete: Sin Acompañante pero Cooperativo — se requiere Agitado. Además el Intérprete solo aplica a pacientes Estables o Moderados.",
     "exp_destination_es":"Cardiaco Crítico → Sala de Riesgo"},

    {"pid":"P02","name":"Fatima, 38F","group":1,
     "condition":"Pulmonary","hr":128,"bp":118,"spo2":77,"rr":19,"temp":36.7,
     "alertness":"Oriented","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Fatima is Pulmonary with SpO2 88% — Critical. Alert with Sudden onset, she goes second after Alex. She needs Rapid Response and a Stretcher.",
     "explanation_es":"Fatima es Pulmonar con SpO2 88%, Crítica. Alerta con inicio Súbito, segunda después de Alex. Necesita Respuesta Rápida y Camilla.",
     "exp_selection_en":"Slot 2: Fatima — Pulmonary Critical — Sudden — Oriented",
     "exp_processes_en":"Rapid Response (Pulmonary Critical). Stretcher (Critical and Non-Ambulatory). No Companion Bay: Accompanied but Critical — Companion Bay requires Stable risk.",
     "exp_destination_en":"Pulmonary Critical → Risk Ward",
     "exp_selection_es":"Ranura 2: Fatima — Pulmonar Crítico — Súbito — Orientada",
     "exp_processes_es":"Respuesta Rápida (Pulmonar Crítica). Camilla (Crítica y No Ambulatoria). No Sala de Acompañante: Acompañada pero Crítica — la Sala de Acompañante requiere riesgo Estable.",
     "exp_destination_es":"Pulmonar Crítico → Sala de Riesgo"},

    {"pid":"P03","name":"Luca, 74M","group":1,
     "condition":"Cardiac","hr":114,"bp":122,"spo2":91,"rr":16,"temp":36.8,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Luca is Cardiac with HR 114 — Moderate. Sudden onset means he goes to Risk Ward. He needs Interpreter support.",
     "explanation_es":"Luca es Cardiaco con FC 114, Moderado. Inicio Súbito significa Urgencias Médicas. Necesita Intérprete.",
     "exp_selection_en":"Slot 4: Luca — Cardiac Moderate — Sudden — Oriented",
     "exp_processes_en":"Interpreter (Cardiac, Moderate, Agitated, Unaccompanied — all four criteria met). No Rapid Response: Cardiac qualifies on condition but requires Critical risk — Luca is Moderate.",
     "exp_destination_en":"Cardiac Moderate — Sudden onset → Risk Ward",
     "exp_selection_es":"Ranura 4: Luca — Cardiaco Moderado — Súbito — Orientado",
     "exp_processes_es":"Intérprete (Cardiaco, Moderado, Agitado, Sin Acompañante — los cuatro criterios cumplidos). No Respuesta Rápida: Cardiaco cumple el criterio de condición pero requiere riesgo Crítico — Luca es Moderado.",
     "exp_destination_es":"Cardiaco Moderado — inicio Súbito → Sala de Riesgo"},

    {"pid":"P04","name":"Thomas, 61M","group":1,
     "condition":"Infectious","hr":116,"bp":110,"spo2":96,"rr":33,"temp":39.6,
     "alertness":"Oriented","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Thomas is Infectious with Temp 39.6 and HR 116 — Critical. Progressive onset places him third among Critical patients. No Rapid Response for Infectious — goes to Monitored Ward.",
     "explanation_es":"Thomas es Infeccioso con Temp 39.6 y FC 116, Crítico. Inicio Progresivo, tercero entre Críticos. Sin Respuesta Rápida para Infecciosos, va a Sala Vigilada.",
     "exp_selection_en":"Slot 3: Thomas — Infectious Critical — Progressive — Oriented",
     "exp_processes_en":"No additional processes. No Rapid Response: Thomas is Critical, but Rapid Response only applies to Cardiac and Pulmonary Critical — not Infectious. No Stretcher: Ambulatory. No Companion Bay: Accompanied but Critical. Infectious also excluded from Companion Bay.",
     "exp_destination_en":"Infectious Critical → Monitored Ward",
     "exp_selection_es":"Ranura 3: Thomas — Infeccioso Crítico — Progresivo — Orientado",
     "exp_processes_es":"Sin procesos adicionales. No Respuesta Rápida: Thomas es Crítico, pero la Respuesta Rápida solo aplica a Cardiaco y Pulmonar Crítico — no a Infeccioso. No Camilla: Ambulatorio. No Sala de Acompañante: Acompañado pero Crítico. Infeccioso también excluido de la Sala de Acompañante.",
     "exp_destination_es":"Infeccioso Crítico → Sala Vigilada"},

    {"pid":"P05","name":"Rosa, 41F","group":1,
     "condition":"Neurological","hr":76,"bp":130,"spo2":97,"rr":14,"temp":38.9,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Rosa is Neurological, Alert with normal BP — Stable. Sudden onset for a Stable Neurological patient means Monitored Ward, not General Ward.",
     "explanation_es":"Rosa es Neurológica, Alerta con TA normal, Estable. Inicio Súbito para un Neurológico Estable significa Sala Vigilada, no Planta General.",
     "exp_selection_en":"Slot 5: Rosa — Neurological Stable — Sudden — Oriented",
     "exp_processes_en":"No additional processes. No Companion Bay: Rosa is Accompanied and Stable — two criteria met — but Companion Bay explicitly excludes Neurological patients.",
     "exp_destination_en":"Neurological Stable — Sudden onset → Monitored Ward",
     "exp_selection_es":"Ranura 5: Rosa — Neurológico Estable — Súbito — Orientada",
     "exp_processes_es":"Sin procesos adicionales. No Sala de Acompañante: Rosa está Acompañada y es Estable — dos criterios cumplidos — pero la Sala de Acompañante excluye explícitamente a los pacientes Neurológicos.",
     "exp_destination_es":"Neurológico Estable — inicio Súbito → Sala Vigilada"},

    # GROUP 2
    {"pid":"P06","name":"Yara, 52F","group":2,
     "condition":"Pulmonary","hr":98,"bp":115,"spo2":76,"rr":28,"temp":38.7,
     "alertness":"Oriented","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Yara is Pulmonary with SpO2 87% — Critical. Alert with Sudden onset, she goes second after Ahmed. She needs Rapid Response and a Stretcher.",
     "explanation_es":"Yara es Pulmonar con SpO2 87%, Crítica. Alerta con inicio Súbito, segunda después de Ahmed. Necesita Respuesta Rápida y Camilla.",
     "exp_selection_en":"Slot 2: Yara — Pulmonary Critical — Sudden — Oriented",
     "exp_processes_en":"Rapid Response (Pulmonary Critical). Stretcher (Critical and Non-Ambulatory). No Companion Bay: Accompanied but Critical — Stable risk is required.",
     "exp_destination_en":"Pulmonary Critical → Risk Ward",
     "exp_selection_es":"Ranura 2: Yara — Pulmonar Crítico — Súbito — Orientada",
     "exp_processes_es":"Respuesta Rápida (Pulmonar Crítica). Camilla (Crítica y No Ambulatoria). No Sala de Acompañante: Acompañada pero Crítica — se requiere riesgo Estable.",
     "exp_destination_es":"Pulmonar Crítico → Sala de Riesgo"},

    {"pid":"P07","name":"Ahmed, 85M","group":2,
     "condition":"Neurological","hr":82,"bp":168,"spo2":95,"rr":16,"temp":39.1,
     "alertness":"Lethargic","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Ahmed is Neurological and Lethargic — Critical regardless of other vitals. Lethargic with Sudden onset puts him first.",
     "explanation_es":"Ahmed es Neurológico y Letárgico, Crítico independientemente de otros signos. Letárgico con inicio Súbito lo coloca primero.",
     "exp_selection_en":"Slot 1: Ahmed — Neurological Critical — Sudden — Lethargic",
     "exp_processes_en":"No additional processes. No Rapid Response: Neurological Critical does not qualify — only Cardiac and Pulmonary Critical. No Stretcher: Ambulatory.",
     "exp_destination_en":"Neurological Critical → Risk Ward",
     "exp_selection_es":"Ranura 1: Ahmed — Neurológico Crítico — Súbito — Letárgico",
     "exp_processes_es":"Sin procesos adicionales. No Respuesta Rápida: Neurológico Crítico no cumple el criterio — solo Cardiaco y Pulmonar Crítico. No Camilla: Ambulatorio.",
     "exp_destination_es":"Neurológico Crítico → Sala de Riesgo"},

    {"pid":"P08","name":"Clara, 44F","group":2,
     "condition":"Cardiac","hr":95,"bp":148,"spo2":96,"rr":31,"temp":36.8,
     "alertness":"Oriented","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Clara is Cardiac with BP 148 — Moderate. Progressive onset means Monitored Ward. Cardiac Moderate with Progressive onset goes to Monitored, not Risk Ward.",
     "explanation_es":"Clara es Cardiaca con TA 148, Moderada. Inicio Progresivo significa Sala Vigilada. Cardiaca Moderada con Progresivo va a Vigilada, no a Urgencias.",
     "exp_selection_en":"Slot 4: Clara — Cardiac Moderate — Progressive — Oriented",
     "exp_processes_en":"No additional processes. No Rapid Response: Cardiac qualifies on condition but requires Critical risk — Clara is Moderate. No Interpreter: Accompanied and Cooperative — social criteria not met. No Companion Bay: Accompanied but Moderate, not Stable.",
     "exp_destination_en":"Cardiac Moderate — Progressive onset → Monitored Ward",
     "exp_selection_es":"Ranura 4: Clara — Cardiaco Moderado — Progresivo — Orientada",
     "exp_processes_es":"Sin procesos adicionales. No Respuesta Rápida: Cardiaco cumple el criterio de condición pero requiere riesgo Crítico — Clara es Moderada. No Intérprete: Acompañada y Cooperativa — criterios sociales no cumplidos. No Sala de Acompañante: Acompañada pero Moderada, no Estable.",
     "exp_destination_es":"Cardiaco Moderado — inicio Progresivo → Sala Vigilada"},

    {"pid":"P09","name":"Oscar, 56M","group":2,
     "condition":"Pulmonary","hr":86,"bp":120,"spo2":91,"rr":23,"temp":39.0,
     "alertness":"Oriented","onset":"Recurring","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Oscar is Pulmonary with SpO2 91% — Moderate. Recurring onset places him last among Moderate patients. He needs Interpreter support.",
     "explanation_es":"Oscar es Pulmonar con SpO2 91%, Moderado. Inicio Recurrente lo coloca último entre Moderados. Necesita Intérprete.",
     "exp_selection_en":"Slot 5: Oscar — Pulmonary Moderate — Recurring — Oriented",
     "exp_processes_en":"Interpreter (Pulmonary, Moderate, Agitated, Unaccompanied — all four criteria met). No Rapid Response: Pulmonary qualifies on condition but requires Critical risk — Oscar is Moderate.",
     "exp_destination_en":"Pulmonary Moderate → Monitored Ward",
     "exp_selection_es":"Ranura 5: Oscar — Pulmonar Moderado — Recurrente — Orientado",
     "exp_processes_es":"Intérprete (Pulmonar, Moderado, Agitado, Sin Acompañante — los cuatro criterios cumplidos). No Respuesta Rápida: Pulmonar cumple el criterio de condición pero requiere riesgo Crítico — Oscar es Moderado.",
     "exp_destination_es":"Pulmonar Moderado → Sala Vigilada"},

    {"pid":"P10","name":"Sofia, 27F","group":2,
     "condition":"Neurological","hr":129,"bp":135,"spo2":97,"rr":15,"temp":37.1,
     "alertness":"Confused","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Sofia is Neurological and Confused — Moderate. Sudden onset ranks her first among Moderate patients. Even though she is Agitated and Unaccompanied, Neurological patients do not get Interpreter support.",
     "explanation_es":"Sofia es Neurológica y Confusa, Moderada. Inicio Súbito la coloca primera entre Moderados. Aunque Agitada y Sin Acompañante, los Neurológicos no reciben Intérprete.",
     "exp_selection_en":"Slot 3: Sofia — Neurological Moderate — Sudden — Confused",
     "exp_processes_en":"No additional processes. No Interpreter: Sofia is Agitated and Unaccompanied — the social criteria are met — but Interpreter requires Cardiac, Pulmonary, or Infectious condition. Neurological does not qualify.",
     "exp_destination_en":"Neurological Moderate → Monitored Ward",
     "exp_selection_es":"Ranura 3: Sofia — Neurológico Moderado — Súbito — Confusa",
     "exp_processes_es":"Sin procesos adicionales. No Intérprete: Sofia está Agitada y Sin Acompañante — los criterios sociales se cumplen — pero el Intérprete requiere condición Cardiaca, Pulmonar o Infecciosa. Neurológico no cumple.",
     "exp_destination_es":"Neurológico Moderado → Sala Vigilada"},

    # GROUP 3
    {"pid":"P11","name":"Paulo, 78M","group":3,
     "condition":"Trauma","hr":122,"bp":98,"spo2":91,"rr":21,"temp":37.0,
     "alertness":"Oriented","onset":"Sudden","mobility":"Non-Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Paulo is Trauma with HR 122 and Non-Ambulatory — Critical. Sudden onset places him first. He needs a Stretcher and goes to Surgical Bay.",
     "explanation_es":"Paulo es Traumático con FC 122 y No Ambulatorio, Crítico. Inicio Súbito, primero. Necesita Camilla y va a Quirófano.",
     "exp_selection_en":"Slot 1: Paulo — Trauma Critical — Sudden — Oriented",
     "exp_processes_en":"Stretcher (Trauma Critical and Non-Ambulatory). No Rapid Response: Trauma does not qualify — Rapid Response is restricted to Cardiac and Pulmonary Critical only.",
     "exp_destination_en":"Trauma Critical → Surgical Bay",
     "exp_selection_es":"Ranura 1: Paulo — Trauma Crítico — Súbito — Orientado",
     "exp_processes_es":"Camilla (Trauma Crítico y No Ambulatorio). No Respuesta Rápida: Trauma no cumple el criterio — la Respuesta Rápida está restringida a Cardiaco y Pulmonar Crítico.",
     "exp_destination_es":"Trauma Crítico → Quirófano"},

    {"pid":"P12","name":"Ana, 36F","group":3,
     "condition":"Trauma","hr":85,"bp":118,"spo2":97,"rr":16,"temp":39.2,
     "alertness":"Oriented","onset":"Progressive","mobility":"Non-Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Ana is Trauma Non-Ambulatory with normal HR — Moderate. Non-Ambulatory alone makes Trauma Moderate, and she still needs a Stretcher. Progressive onset places her second.",
     "explanation_es":"Ana es Traumática No Ambulatoria con FC normal, Moderada. No Ambulatoria sola hace Trauma Moderado y sigue necesitando Camilla. Progresivo, segunda.",
     "exp_selection_en":"Slot 2: Ana — Trauma Moderate — Progressive — Oriented",
     "exp_processes_en":"Stretcher (Trauma Moderate and Non-Ambulatory). No Companion Bay: Accompanied but Moderate, not Stable — Stable risk is required.",
     "exp_destination_en":"Trauma Moderate → Surgical Bay",
     "exp_selection_es":"Ranura 2: Ana — Trauma Moderado — Progresivo — Orientada",
     "exp_processes_es":"Camilla (Trauma Moderado y No Ambulatoria). No Sala de Acompañante: Acompañada pero Moderada, no Estable — se requiere riesgo Estable.",
     "exp_destination_es":"Trauma Moderado → Quirófano"},

    {"pid":"P13","name":"Igor, 82M","group":3,
     "condition":"Neurological","hr":128,"bp":132,"spo2":96,"rr":15,"temp":36.9,
     "alertness":"Oriented","onset":"Sudden","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Cooperative",
     "explanation_en":"Igor is Neurological, Alert with BP 132 — Stable. Sudden onset means Monitored Ward. He ranks before Luis because Stable Sudden beats Moderate Recurring.",
     "explanation_es":"Igor es Neurológico, Alerta con TA 132, Estable. Inicio Súbito significa Sala Vigilada. Va antes que Luis porque Estable Súbito supera Moderado Recurrente.",
     "exp_selection_en":"Slot 4: Igor — Neurological Stable — Sudden — Oriented",
     "exp_processes_en":"No additional processes. No Companion Bay: Unaccompanied. Neurological patients are also explicitly excluded from Companion Bay.",
     "exp_destination_en":"Neurological Stable — Sudden onset → Monitored Ward",
     "exp_selection_es":"Ranura 4: Igor — Neurológico Estable — Súbito — Orientado",
     "exp_processes_es":"Sin procesos adicionales. No Sala de Acompañante: Sin Acompañante. Los pacientes Neurológicos también están explícitamente excluidos de la Sala de Acompañante.",
     "exp_destination_es":"Neurológico Estable — inicio Súbito → Sala Vigilada"},

    {"pid":"P14","name":"Eva, 48F","group":3,
     "condition":"Cardiac","hr":90,"bp":122,"spo2":97,"rr":33,"temp":36.7,
     "alertness":"Oriented","onset":"Progressive","mobility":"Ambulatory",
     "companion":"Unaccompanied","cooperation":"Agitated",
     "explanation_en":"Eva is Cardiac with normal HR and BP — Stable. Sudden onset means Monitored Ward. She is Agitated and Unaccompanied so she needs Interpreter support.",
     "explanation_es":"Eva es Cardiaca con FC y TA normales, Estable. Inicio Súbito significa Sala Vigilada. Agitada y Sin Acompañante, necesita Intérprete.",
     "exp_selection_en":"Slot 5: Eva — Cardiac Stable — Progressive — Oriented",
     "exp_processes_en":"Interpreter (Cardiac, Stable, Agitated, Unaccompanied — all four criteria met). No Rapid Response: Cardiac qualifies on condition but requires Critical risk — Eva is Stable. No Companion Bay: Unaccompanied — Companion Bay requires Accompanied.",
     "exp_destination_en":"Cardiac Stable — Progressive onset → General Ward",
     "exp_selection_es":"Ranura 5: Eva — Cardiaco Estable — Progresivo — Orientada",
     "exp_processes_es":"Intérprete (Cardiaco, Estable, Agitada, Sin Acompañante — los cuatro criterios cumplidos). No Respuesta Rápida: Cardiaco cumple el criterio de condición pero requiere riesgo Crítico — Eva es Estable. No Sala de Acompañante: Sin Acompañante — la Sala de Acompañante requiere Acompañado.",
     "exp_destination_es":"Cardiaco Estable — inicio Progresivo → Planta General"},

    {"pid":"P15","name":"Luis, 57M","group":3,
     "condition":"Infectious","hr":125,"bp":115,"spo2":96,"rr":17,"temp":38.6,
     "alertness":"Oriented","onset":"Recurring","mobility":"Ambulatory",
     "companion":"Accompanied","cooperation":"Cooperative",
     "explanation_en":"Luis is Infectious with Temp 38.6 — Moderate. Recurring onset places him last. Infectious Moderate goes to General Ward.",
     "explanation_es":"Luis es Infeccioso con Temp 38.6, Moderado. Inicio Recurrente lo coloca último. Infeccioso Moderado va a Planta General.",
     "exp_selection_en":"Slot 3: Luis — Infectious Moderate — Recurring — Oriented",
     "exp_processes_en":"No additional processes. No Companion Bay: Accompanied, but Companion Bay explicitly excludes Infectious patients. No Interpreter: Cooperative.",
     "exp_destination_en":"Infectious Moderate → General Ward",
     "exp_selection_es":"Ranura 3: Luis — Infeccioso Moderado — Recurrente — Orientado",
     "exp_processes_es":"Sin procesos adicionales. No Sala de Acompañante: Acompañado, pero la Sala de Acompañante excluye explícitamente a los pacientes Infecciosos. No Intérprete: Cooperativo.",
     "exp_destination_es":"Infeccioso Moderado → Planta General"},
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
