"""
Triage Game — Patient Card Generator v2
=========================================
Redesigned to match game.html card aesthetic:
  - Colour-coded vitals (red=Critical, orange=Abnormal)
  - Rounded corners throughout
  - Patient ArUco (centred) below vitals
  - Destination ArUco placeholder (same size) below patient ArUco
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from design_patients import PATIENTS_A, PATIENTS_B, derive_risk

# ── CONFIG ────────────────────────────────────────────────────────────────────
DPI       = 300
MM        = DPI / 25.4
W         = int(210 * MM)
H         = int(297 * MM)
MAR       = int(10 * MM)

DICT_ID   = cv2.aruco.DICT_4X4_100
OUT_DIR   = "patient_cards_v2"
SET_A_BASE = 10
SET_B_BASE = 30

# ── COLOURS ───────────────────────────────────────────────────────────────────
WHITE      = (255, 255, 255)
BG         = (245, 244, 240)      # #f5f4f0
NAVY       = ( 31,  56, 100)
BORDER_COL = (200, 195, 185)      # subtle border
LABEL_COL  = (160, 155, 148)      # grey label

CRIT_BG    = (252, 235, 235)      # #FCEBEB
CRIT_TX    = (163,  45,  45)      # #A32D2D
MOD_BG     = (250, 238, 218)      # #FAEEDA
MOD_TX     = (133,  79,  11)      # #854F0B
NORM_BG    = (240, 243, 248)      # #F0F3F8
NORM_TX    = ( 60,  60,  60)

COND_COLORS = {
    'Cardiac':      ((254, 236, 236), (180,  50,  50)),
    'Pulmonary':    ((232, 242, 253), ( 40,  80, 160)),
    'Neurological': ((238, 237, 251), ( 80,  70, 180)),
    'Trauma':       ((253, 243, 227), (150,  90,  20)),
    'Infectious':   ((227, 245, 238), ( 30, 120,  80)),
}

RISK_COLORS = {
    'Critical': (CRIT_BG, CRIT_TX),
    'Moderate': (MOD_BG,  MOD_TX),
    'Stable':   ((226, 239, 218), (55, 86, 35)),
}

# ── VITAL THRESHOLDS ─────────────────────────────────────────────────────────
def vital_level(key, val):
    try: v = float(val)
    except: return 'normal'
    if key == 'hr':
        if v > 130 or v < 40: return 'critical'
        if v > 100:            return 'abnormal'
    elif key == 'bp':
        if v > 140 or v < 90: return 'abnormal'
    elif key == 'spo2':
        if v < 80:  return 'critical'
        if v < 91:  return 'abnormal'
    elif key == 'rr':
        if v > 30:  return 'critical'
        if v > 20:  return 'abnormal'
    elif key == 'temp':
        if v > 39 or v < 35: return 'critical'
        if v > 38:            return 'abnormal'
    return 'normal'

def alertness_level(a):
    if a == 'Lethargic': return 'critical'
    if a == 'Confused':  return 'abnormal'
    return 'normal'

def level_colors(level):
    if level == 'critical': return CRIT_BG, CRIT_TX
    if level == 'abnormal': return MOD_BG,  MOD_TX
    return NORM_BG, NORM_TX

# ── FONTS ─────────────────────────────────────────────────────────────────────
def font(size_mm, bold=False):
    paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in paths:
        try: return ImageFont.truetype(p, int(size_mm * MM))
        except OSError: pass
    return ImageFont.load_default()

# ── ARUCO ─────────────────────────────────────────────────────────────────────
aruco_dict = cv2.aruco.getPredefinedDictionary(DICT_ID)

def make_aruco(mid, size_px):
    img = np.zeros((size_px, size_px), dtype=np.uint8)
    cv2.aruco.generateImageMarker(aruco_dict, mid, size_px, img, 1)
    return Image.fromarray(img).convert("RGB")

# ── DRAW HELPERS ──────────────────────────────────────────────────────────────
def rr(draw, xy, r, fill, outline=None, lw=1):
    draw.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=lw)

def text_w(draw, text, f):
    bb = draw.textbbox((0,0), text, font=f)
    return bb[2] - bb[0]

def text_h(draw, text, f):
    bb = draw.textbbox((0,0), text, font=f)
    return bb[3] - bb[1]

# ── CARD ─────────────────────────────────────────────────────────────────────
def make_card(p, aruco_id, set_label, set_color):
    card = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(card)

    risk = derive_risk(p)
    risk_bg, risk_tx = RISK_COLORS[risk]
    cond_bg, cond_tx = COND_COLORS.get(p['condition'], (NORM_BG, NORM_TX))

    f_big   = font(7,   bold=True)
    f_med   = font(4.5, bold=True)
    f_sm    = font(3.5)
    f_smbold= font(3.5, bold=True)
    f_xs    = font(3.0)
    f_label = font(2.8)

    pad  = int(3 * MM)
    gap  = int(3 * MM)
    y    = MAR

    # ── Header card: name + condition + risk ─────────────────────────────────
    header_h = int(22 * MM)
    rr(draw, [MAR, y, W-MAR, y+header_h], int(4*MM),
       fill=tuple(NAVY), outline=tuple(BORDER_COL), lw=2)

    # Condition badge (top-left) — white pill on navy
    cond_text = p['condition']
    cw = text_w(draw, cond_text, f_xs) + int(5*MM)
    ch = int(5 * MM)
    rr(draw, [MAR+pad, y+pad, MAR+pad+cw, y+pad+ch], int(2*MM),
       fill=(255,255,255,60), outline=(255,255,255), lw=1)
    draw.text((MAR+pad + int(2.5*MM), y+pad + int(0.5*MM)),
              cond_text, font=f_xs, fill=WHITE)

    # Patient name + ID — white on navy header
    name_text = f"{p['pid']}  {p['name']}"
    draw.text((MAR + pad, y + int(9*MM)),
              name_text, font=f_big, fill=WHITE)

    # Set badge top-right
    set_text = set_label
    sw = text_w(draw, set_text, f_xs) + int(4*MM)
    rr(draw, [W-MAR-pad-sw, y+pad, W-MAR-pad, y+pad+ch],
       int(2*MM), fill=None, outline=WHITE, lw=1)
    draw.text((W-MAR-pad-sw + int(2*MM), y+pad + int(0.5*MM)),
              set_text, font=f_xs, fill=WHITE)

    # Group
    grp_text = f"Group {p['group']}"
    draw.text((W - MAR - pad - text_w(draw, grp_text, f_label),
               y + header_h - int(5*MM)),
              grp_text, font=f_label, fill=(200, 210, 230))

    y += header_h + gap

    # ── Vitals grid (2 cols × 3 rows = 5 vitals + alertness) ─────────────────
    n_cols   = 2
    cell_h   = int(13 * MM)
    cell_gap = int(2  * MM)
    cell_w   = (W - 2*MAR - cell_gap) // n_cols

    vitals = [
        ('hr',   'HR / FC',   p['hr'],   'bpm'),
        ('bp',   'BP / TA',   p['bp'],   'mmHg'),
        ('spo2', 'SpO2',      p['spo2'], '%'),
        ('rr',   'RR / FR',   p['rr'],   '/min'),
        ('temp', 'Temp',      p['temp'], '°C'),
    ]

    for vi, (key, label, val, unit) in enumerate(vitals):
        col = vi % n_cols
        row = vi // n_cols
        x0 = MAR + col * (cell_w + cell_gap)
        y0 = y + row * (cell_h + cell_gap)
        x1 = x0 + cell_w
        y1 = y0 + cell_h

        lv = vital_level(key, val) if key else alertness_level(val)
        bg, tx = level_colors(lv)

        rr(draw, [x0, y0, x1, y1], int(3*MM),
           fill=tuple(bg), outline=tuple(BORDER_COL), lw=1)

        # Label (small, grey)
        draw.text((x0 + pad, y0 + int(2*MM)),
                  label, font=f_label, fill=tuple(LABEL_COL))
        # Value (larger, coloured)
        val_str = f"{val}{unit}"
        draw.text((x0 + pad, y0 + int(6*MM)),
                  val_str, font=f_med, fill=tuple(tx))

    y += 3 * (cell_h + cell_gap) + gap

    # ── Categorical variables (3 rows) ───────────────────────────────────────
    cat_h = int(9 * MM)
    cats  = [
        ('Onset',     p['onset']),
        ('Alertness', p['alertness']),
        ('Mobility',  p['mobility']),
    ]
    for label, val in cats:
        # Colour alertness cell by level
        if label == 'Alertness':
            lv = alertness_level(val)
            cbg, ctx = level_colors(lv)
        else:
            cbg, ctx = WHITE, NAVY
        rr(draw, [MAR, y, W-MAR, y+cat_h], int(3*MM),
           fill=tuple(cbg), outline=tuple(BORDER_COL), lw=1)
        draw.text((MAR + pad, y + int(1*MM)),
                  label, font=f_label, fill=tuple(LABEL_COL))
        draw.text((MAR + pad, y + int(4.5*MM)),
                  val, font=f_smbold, fill=tuple(ctx))
        y += cat_h + cell_gap

    y += gap

    # ── Separator line ────────────────────────────────────────────────────────
    #draw.line([MAR, y, W-MAR, y], fill=tuple(BORDER_COL), width=2)
    #y += int(2 * MM)

    # ── Patient ArUco (centred) ───────────────────────────────────────────────
    remaining = H - MAR - y
    aruco_zone_h = remaining // 2 - int(4*MM)

    border_px  = int(3 * MM)
    marker_px  = int(75 * MM)   # 7.5cm at 300dpi
    total_m    = marker_px + 2 * border_px

    # Patient ArUco label
    #pat_label = f"Patient ID — ArUco {aruco_id}"
    #draw.text(((W - text_w(draw, pat_label, f_smbold)) // 2, y),
    #          pat_label, font=f_smbold, fill=tuple(NAVY))
    #y += int(6 * MM)

    # ArUco image with white border
    aruco_img = make_aruco(aruco_id, marker_px)
    bordered  = Image.new("RGB", (total_m, total_m), WHITE)
    bordered.paste(aruco_img, (border_px, border_px))
    ax = (W - total_m) // 2
    # Rounded white box behind aruco
    rr(draw, [ax - int(4*MM), y - int(3*MM),
              ax + total_m + int(4*MM), y + total_m + int(3*MM)],
       int(4*MM), fill=WHITE, outline=tuple(BORDER_COL), lw=2)
    card.paste(bordered, (ax, y))
    # Label to the right of the aruco
    draw.text((ax + total_m + int(4*MM), y + total_m // 2),
              f"ArUco {aruco_id}", font=f_smbold, fill=tuple(NAVY), anchor="lm")
    y += total_m + int(4 * MM)

    # ── Destination ArUco placeholder (same size) ─────────────────────────────
    dest_label = "Destination"
    draw.text(((W - text_w(draw, dest_label, f_smbold)) // 2, y),
              dest_label, font=f_smbold, fill=tuple(LABEL_COL))
    y += int(3 * MM)

    # Dashed-border placeholder box same size as patient aruco box
    dest_box_w = total_m + int(8*MM)
    dest_box_h = total_m + int(6*MM)
    dx = (W - dest_box_w) // 2

    # Draw dashed rectangle manually
    rr(draw, [dx, y, dx+dest_box_w, y+dest_box_h],
       int(4*MM), fill=(250,250,250), outline=tuple(BORDER_COL), lw=2)

    # Dashed inner border effect
    rr(draw, [dx+int(3*MM), y+int(3*MM),
              dx+dest_box_w-int(3*MM), y+dest_box_h-int(3*MM)],
       int(3*MM), fill=None, outline=(210,205,200), lw=1)

    # Placeholder text
    ph = "Place destination card here"
    draw.text(((W - text_w(draw, ph, f_label)) // 2,
               y + dest_box_h // 2 - int(2*MM)),
              ph, font=f_label, fill=tuple(LABEL_COL))

    # Outer card border
    rr(draw, [2, 2, W-3, H-3], int(5*MM),
       fill=None, outline=tuple(BORDER_COL), lw=3)

    return card


# ── MAIN ─────────────────────────────────────────────────────────────────────
print("=" * 60)
print("TRIAGE GAME — Patient Card Generator v2")
print(f"Card size: A4 ({W}x{H}px at {DPI}dpi)")
print(f"Source: design_patients.py ({len(PATIENTS_A)} + {len(PATIENTS_B)} patients)")
print("=" * 60)

for set_label, patients, base_id, set_color, folder in [
    ("SET A", PATIENTS_A, SET_A_BASE, (31, 56, 100), "set_a"),
    ("SET B", PATIENTS_B, SET_B_BASE, (80, 80, 80),  "set_b"),
]:
    out_dir = os.path.join(OUT_DIR, folder)
    os.makedirs(out_dir, exist_ok=True)
    print(f"\n[{set_label}] Generating {len(patients)} cards...")
    for i, p in enumerate(patients):
        aruco_id = base_id + i
        card = make_card(p, aruco_id, set_label, set_color)
        slug = p['name'].split(',')[0].replace(' ', '_')
        fname = os.path.join(out_dir, f"{p['pid']}_{slug}.png")
        card.save(fname, dpi=(DPI, DPI))
        print(f"  {p['pid']} {p['name']:<25} ArUco {aruco_id:02d}  ->  {fname}")

print("\n" + "=" * 60)
print(f"Done. Cards saved in: {OUT_DIR}/")
print(f"  Set A: P01=ArUco{SET_A_BASE} ... P15=ArUco{SET_A_BASE+14}")
print(f"  Set B: P01=ArUco{SET_B_BASE} ... P15=ArUco{SET_B_BASE+14}")
print("Print at ACTUAL SIZE (100%) on A4 paper.")
print("=" * 60)
