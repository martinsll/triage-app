"""
Triage Game — Patient Card Generator
=====================================
Generates A4 patient cards for all 30 patients (Set A + Set B, 15 each).
Data is read directly from design_patients.py — no separate data to maintain.

Each card includes:
  - Header with SET label, patient ID and ArUco ID
  - Full patient info (vitals + patient variables)
  - 3 process card slots (2-column grid, left-aligned)
  - ArUco marker (max size) with patient ID in the 4th slot (bottom-right)

ArUco ID allocation (DICT_4X4_100):
  Set A: P01→10, P02→11, ... P15→24
  Set B: P01→30, P02→31, ... P15→44

Output: patient_cards/set_a/ and patient_cards/set_b/
Print at ACTUAL SIZE (100%, no scaling) on A4 paper.

Requirements:
    pip install opencv-contrib-python pillow
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from design_patients import PATIENTS_A, PATIENTS_B, derive_risk

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DPI          = 300
MM_TO_PX     = DPI / 25.4
CARD_W       = int(210 * MM_TO_PX)   # A4 width  2480px
CARD_H       = int(297 * MM_TO_PX)   # A4 height 3508px
MARGIN       = int(8   * MM_TO_PX)

DICT_ID      = cv2.aruco.DICT_4X4_100
OUTPUT_DIR   = "patient_cards"
SET_A_BASE   = 10
SET_B_BASE   = 30

# ─── COLOURS ──────────────────────────────────────────────────────────────────
COL_NAVY     = (31,  56, 100)
COL_WHITE    = (255, 255, 255)
COL_LIGHT    = (240, 243, 248)
COL_BORDER   = (180, 190, 210)
COL_CRIT_BG  = (255, 224, 224)
COL_CRIT_TX  = (163,  45,  45)
COL_MOD_BG   = (255, 242, 204)
COL_MOD_TX   = (133, 100,  11)
COL_STAB_BG  = (226, 239, 218)
COL_STAB_TX  = ( 55,  86,  35)
COL_PROC_BG  = (234, 240, 251)
COL_PROC_TX  = ( 31,  56, 100)
COL_SET_A    = ( 31,  56, 100)
COL_SET_B    = ( 80,  80,  80)

# ─── VITAL THRESHOLDS (matching rules_engine) ─────────────────────────────────
def vital_level(key, val):
    """Return 'critical', 'abnormal', or 'normal' for a numeric vital."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return 'normal'
    if key == 'hr':
        if v > 130 or v < 40:  return 'critical'
        if v > 100:             return 'abnormal'
    elif key == 'bp':
        if v > 140 or v < 90:  return 'abnormal'
    elif key == 'spo2':
        if v < 80:   return 'critical'
        if v < 91:   return 'abnormal'
    elif key == 'rr':
        if v > 30:   return 'critical'
        if v > 20:   return 'abnormal'
    elif key == 'temp':
        if v > 39 or v < 35:  return 'critical'
        if v > 38:             return 'abnormal'
    return 'normal'

def alertness_level(val):
    if val == 'Lethargic': return 'critical'
    if val == 'Confused':  return 'abnormal'
    return 'normal'

def level_colors(level, risk_bg, risk_tx):
    if level == 'critical': return COL_CRIT_BG, COL_CRIT_TX
    if level == 'abnormal': return COL_MOD_BG,  COL_MOD_TX
    return COL_LIGHT, (60, 60, 60)

def risk_colors(risk):
    if risk == 'Critical': return COL_CRIT_BG, COL_CRIT_TX
    if risk == 'Moderate': return COL_MOD_BG,  COL_MOD_TX
    return COL_STAB_BG, COL_STAB_TX

# ─── FONT HELPER ──────────────────────────────────────────────────────────────
def get_font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial Bold.ttf" if bold else "/System/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()

# ─── ARUCO ────────────────────────────────────────────────────────────────────
aruco_dict = cv2.aruco.getPredefinedDictionary(DICT_ID)

def make_aruco(marker_id, size_px):
    img = np.zeros((size_px, size_px), dtype=np.uint8)
    cv2.aruco.generateImageMarker(aruco_dict, marker_id, size_px, img, 1)
    return Image.fromarray(img).convert("RGB")

# ─── DRAWING HELPER ───────────────────────────────────────────────────────────
def draw_rounded_rect(draw, xy, radius, fill, outline=None, width=1):
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius,
                            fill=fill, outline=outline, width=width)

# ─── CARD GENERATOR ───────────────────────────────────────────────────────────
def make_patient_card(p, aruco_id, set_label, set_color):
    """Generate one A4 patient card from a design_patients dict."""
    card  = Image.new("RGB", (CARD_W, CARD_H), COL_WHITE)
    draw  = ImageDraw.Draw(card)
    M     = MARGIN
    y     = M

    risk        = derive_risk(p)
    risk_bg, risk_tx = risk_colors(risk)

    pid         = p['pid']
    name        = p['name']
    condition   = p['condition']

    f_name  = get_font(int(7   * MM_TO_PX), bold=True)
    f_cond  = get_font(int(5.5 * MM_TO_PX), bold=True)
    f_sec   = get_font(int(4   * MM_TO_PX), bold=True)
    f_label = get_font(int(3.5 * MM_TO_PX), bold=True)
    f_val   = get_font(int(3.5 * MM_TO_PX))
    f_set   = get_font(int(3   * MM_TO_PX), bold=True)

    # ── Set badge (top-right) ─────────────────────────────────────────────────
    stb = draw.textbbox((0, 0), set_label, font=f_set)
    sw  = stb[2] - stb[0] + int(4 * MM_TO_PX)
    sh  = stb[3] - stb[1] + int(2 * MM_TO_PX)
    sx  = CARD_W - M - sw
    draw_rounded_rect(draw, [sx, M, sx+sw, M+sh], radius=4, fill=set_color)
    draw.text((sx + int(2*MM_TO_PX), M + int(1*MM_TO_PX)),
              set_label, font=f_set, fill=COL_WHITE)

    # ── Patient name + condition badge ────────────────────────────────────────
    name_text = f"{pid} — {name}"
    nb  = draw.textbbox((0, 0), name_text, font=f_name)
    draw.text((M, y), name_text, font=f_name, fill=tuple(COL_NAVY))

    cb  = draw.textbbox((0, 0), condition, font=f_cond)
    cbw = cb[2]-cb[0] + int(6*MM_TO_PX)
    cbh = cb[3]-cb[1] + int(3*MM_TO_PX)
    cx  = M + (nb[2]-nb[0]) + int(5*MM_TO_PX)
    cy  = y + ((nb[3]-nb[1]) - cbh) // 2
    draw_rounded_rect(draw, [cx, cy, cx+cbw, cy+cbh], radius=6,
                      fill=tuple(COL_LIGHT), outline=tuple(COL_BORDER), width=2)
    draw.text((cx + int(3*MM_TO_PX), cy + int(1.5*MM_TO_PX)),
              condition, font=f_cond, fill=tuple(COL_NAVY))

    y += max(nb[3]-nb[1], cbh) + int(5 * MM_TO_PX)

    # ── Vitals (2 narrow cols) + Patient Variables (3rd col) ──────────────────
    vitals_col_w = int(52  * MM_TO_PX)
    cell_gap     = int(3   * MM_TO_PX)
    row_h        = int(14  * MM_TO_PX)
    pad          = int(2.5 * MM_TO_PX)
    vars_x       = M + 2 * (vitals_col_w + cell_gap)
    vars_w       = CARD_W - M - vars_x

    draw.text((M,      y), "VITAL SIGNS",       font=f_sec, fill=tuple(COL_NAVY))
    draw.text((vars_x, y), "PATIENT VARIABLES", font=f_sec, fill=tuple(COL_NAVY))
    y += int(6 * MM_TO_PX)

    # Vitals: key, display_label, value, unit
    vitals = [
        ('hr',   'Heart Rate',   p['hr'],   'bpm'),
        ('bp',   'Blood Press.', p['bp'],   'mmHg'),
        ('spo2', 'SpO2',         p['spo2'], '%'),
        ('rr',   'Resp. Rate',   p['rr'],   '/min'),
        ('temp', 'Temperature',  p['temp'], '°C'),
        (None,   'Alertness',    p['alertness'], ''),
    ]

    for vi, (key, label, val, unit) in enumerate(vitals):
        col = vi % 2
        row = vi // 2
        x0  = M + col * (vitals_col_w + cell_gap)
        y0  = y + row * row_h
        x1  = x0 + vitals_col_w
        y1  = y0 + row_h - cell_gap

        bg, tx = COL_LIGHT, (60, 60, 60)

        draw_rounded_rect(draw, [x0, y0, x1, y1], radius=4,
                          fill=bg, outline=tuple(COL_BORDER), width=1)
        draw.text((x0 + pad, y0 + pad), label,
                  font=f_label, fill=tuple(COL_NAVY))
        val_str = f"{val}{unit}"
        draw.text((x0 + pad, y0 + int(7*MM_TO_PX)),
                  val_str, font=f_val, fill=tuple(tx))

    # ── Patient variables column ───────────────────────────────────────────────
    vars_data = [
        ('Onset',       p['onset']),
        ('Mobility',    p['mobility']),
        ('Companion',   p['companion']),
        ('Cooperation', p['cooperation']),
    ]
    vars_tot  = 3 * row_h
    var_row_h = vars_tot // len(vars_data)

    for vi, (label, val) in enumerate(vars_data):
        vx0 = vars_x
        vy0 = y + vi * var_row_h
        vx1 = vars_x + vars_w - cell_gap
        vy1 = vy0 + var_row_h - cell_gap

        draw_rounded_rect(draw, [vx0, vy0, vx1, vy1], radius=4,
                          fill=tuple(COL_LIGHT), outline=tuple(COL_BORDER), width=1)
        draw.text((vx0 + pad, vy0 + (var_row_h - cell_gap) // 2),
                  f"{label}: {val}", font=f_val, fill=(40, 40, 40), anchor="lm")

    y += 3 * row_h + int(6 * MM_TO_PX)

    # ── Group info ────────────────────────────────────────────────────────────
    f_group = get_font(int(3.2 * MM_TO_PX))
    draw.text((M, y), f"Group {p['group']}",
              font=f_group, fill=(150, 150, 150))
    y += int(6 * MM_TO_PX)

    # ── Separator ─────────────────────────────────────────────────────────────
    draw.line([M, y, CARD_W-M, y], fill=tuple(COL_BORDER), width=2)
    y += int(4 * MM_TO_PX)

    draw.text((M, y), "ADDITIONAL PROCESSES", font=f_sec, fill=tuple(COL_PROC_TX))
    y += int(6 * MM_TO_PX)

    # ── Process slots (2×2 grid: slots 1–3 + ArUco) ──────────────────────────
    slot_gap = int(8  * MM_TO_PX)
    slot_w   = (CARD_W - 2 * M - slot_gap) // 2
    slot_h   = (CARD_H - M - y - slot_gap) // 2

    f_proc = get_font(int(5   * MM_TO_PX), bold=True)
    f_hint = get_font(int(3.5 * MM_TO_PX))

    for i, label in enumerate(["Process 1", "Process 2", "Process 3"]):
        row = i // 2
        col = i % 2
        sx  = M + col * (slot_w + slot_gap)
        sy  = y + row * (slot_h + slot_gap)

        draw_rounded_rect(draw, [sx, sy, sx+slot_w, sy+slot_h], radius=8,
                          fill=tuple(COL_PROC_BG),
                          outline=tuple(COL_PROC_TX), width=2)
        draw.text((sx + int(4*MM_TO_PX), sy + int(4*MM_TO_PX)),
                  label, font=f_proc, fill=tuple(COL_PROC_TX))
        draw.text((sx + slot_w//2, sy + slot_h//2),
                  "Attach process card here",
                  font=f_hint, fill=(150, 170, 210), anchor="mm")

    # ── ArUco slot (row 2, col 2) ─────────────────────────────────────────────
    ax = M + slot_w + slot_gap
    ay = y + slot_h + slot_gap

    draw_rounded_rect(draw, [ax, ay, ax+slot_w, ay+slot_h], radius=8,
                      fill=tuple(COL_WHITE), outline=tuple(COL_NAVY), width=2)

    border    = int(3 * MM_TO_PX)
    marker_px = min(slot_w, slot_h) - 2 * border
    total_m   = marker_px + 2 * border
    aruco_img = make_aruco(aruco_id, marker_px)
    bordered  = Image.new("RGB", (total_m, total_m), COL_WHITE)
    bordered.paste(aruco_img, (border, border))

    f_id    = get_font(int(4 * MM_TO_PX), bold=True)
    id_text = f"{pid}  |  ArUco {aruco_id}"
    ib      = draw.textbbox((0, 0), id_text, font=f_id)
    id_h    = ib[3] - ib[1]

    group_h = total_m + int(2*MM_TO_PX) + id_h
    mx      = ax + (slot_w - total_m) // 2
    my      = ay + (slot_h - group_h) // 2
    card.paste(bordered, (mx, my))

    draw.text((ax + slot_w//2, my + total_m + int(2*MM_TO_PX)),
              id_text, font=f_id, fill=tuple(COL_NAVY), anchor="mt")

    draw.rectangle([0, 0, CARD_W-1, CARD_H-1],
                   outline=tuple(COL_BORDER), width=3)
    return card

# ─── MAIN ─────────────────────────────────────────────────────────────────────
print("=" * 60)
print("TRIAGE GAME — Patient Card Generator")
print(f"Card size: A4 ({CARD_W}×{CARD_H}px at {DPI}dpi)")
print(f"Source:    design_patients.py ({len(PATIENTS_A)} + {len(PATIENTS_B)} patients)")
print("=" * 60)

for set_label, patients, base_id, set_color, folder in [
    ("SET A", PATIENTS_A, SET_A_BASE, COL_SET_A, "set_a"),
    ("SET B", PATIENTS_B, SET_B_BASE, COL_SET_B, "set_b"),
]:
    out_dir = os.path.join(OUTPUT_DIR, folder)
    os.makedirs(out_dir, exist_ok=True)
    print(f"\n[{set_label}] Generating {len(patients)} cards...")

    for i, p in enumerate(patients):
        aruco_id = base_id + i
        card = make_patient_card(p, aruco_id, set_label, tuple(set_color))
        slug = p['name'].split(',')[0].replace(' ', '_')
        fname = os.path.join(out_dir, f"{p['pid']}_{slug}.png")
        card.save(fname, dpi=(DPI, DPI))
        print(f"  {p['pid']} {p['name']:<25} ArUco {aruco_id:02d}  →  {fname}")

print("\n" + "=" * 60)
print(f"Done. Cards saved in: {OUTPUT_DIR}/")
print()
print("ArUco ID reference:")
print(f"  Set A: P01={SET_A_BASE}, P02={SET_A_BASE+1}, ... P15={SET_A_BASE+14}")
print(f"  Set B: P01={SET_B_BASE}, P02={SET_B_BASE+1}, ... P15={SET_B_BASE+14}")
print()
print("Print at ACTUAL SIZE (100%) on A4 paper.")
print("=" * 60)
