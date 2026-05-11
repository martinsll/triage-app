"""
Triage Game — ArUco Marker Generator (Full Set)
================================================
Generates all non-patient ArUco markers needed for the game.

ID allocation (DICT_4X4_100):
    0– 3  : Selection board corners  (TL, TR, BL, BR)
    4– 7  : Destination board corners (TL, TR, BL, BR)
   10–29  : Set A patient cards      (generated separately)
   30–49  : Set B patient cards      (generated separately)
   50–53  : Additional process cards (4 processes)

Output:
    aruco_output/selection_board/   — 4 corner markers + print sheet
    aruco_output/destination_board/ — 4 corner markers + print sheet
    aruco_output/processes/         — 4 process markers + print sheet

Print all print_sheet.png at ACTUAL SIZE (100%, no scaling).
Recommended print size: 10cm × 10cm per marker.

Requirements:
    pip install opencv-contrib-python pillow
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import os

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DICT_ID      = cv2.aruco.DICT_4X4_100
OUTPUT_DIR   = "aruco_output"
DPI          = 200
MM_TO_PX     = DPI / 25.4

MARKER_PX    = int(78 * MM_TO_PX)   # 7.8cm marker (matches process cards at 9cm total)
BORDER_PX    = int(3  * MM_TO_PX)   # 3mm white border around marker

A5_W         = int(148 * MM_TO_PX)
A5_H         = int(210 * MM_TO_PX)

# ─── COLOURS ──────────────────────────────────────────────────────────────────
COL_NAVY     = (31,  56, 100)
COL_WHITE    = (255, 255, 255)
COL_LIGHT    = (240, 243, 248)
COL_BORDER   = (180, 190, 210)
COL_SEL_BG   = (31,  56, 100)
COL_DEST_BG  = (80,  80,  80)
COL_PROC_BG  = (31, 100,  60)

# ─── ID MAP ───────────────────────────────────────────────────────────────────
SELECTION_CORNERS = {
    0: ("TOP-LEFT",     "Place at top-left corner of selection board"),
    1: ("TOP-RIGHT",    "Place at top-right corner of selection board"),
    2: ("BOTTOM-LEFT",  "Place at bottom-left corner of selection board"),
    3: ("BOTTOM-RIGHT", "Place at bottom-right corner of selection board"),
}

DESTINATION_CORNERS = {
    4: ("TOP-LEFT",     "Place at top-left corner of destination board"),
    5: ("TOP-RIGHT",    "Place at top-right corner of destination board"),
    6: ("BOTTOM-LEFT",  "Place at bottom-left corner of destination board"),
    7: ("BOTTOM-RIGHT", "Place at bottom-right corner of destination board"),
}

PROCESSES = {
    50: ("Call Rapid Response",
         "Cardiac OR Pulmonary AND Critical.\nInfectious Critical does NOT trigger this."),
    51: ("Request Stretcher",
         "Non-Ambulatory AND\n(Critical OR Trauma Moderate)."),
    52: ("Companion to Waiting Bay",
         "Accompanied AND Stable.\nNot Neurological or Infectious."),
    53: ("Request Interpreter",
         "Cardiac/Pulmonary/Infectious\nAND Agitated AND Unaccompanied\nAND (Stable or Moderate)."),
}

# ─── HELPERS ──────────────────────────────────────────────────────────────────
aruco_dict = cv2.aruco.getPredefinedDictionary(DICT_ID)

def get_font(size, bold=False):
    for path in [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()

def make_aruco_img(marker_id, size_px):
    raw = np.zeros((size_px, size_px), dtype=np.uint8)
    cv2.aruco.generateImageMarker(aruco_dict, marker_id, size_px, raw, 1)
    return Image.fromarray(raw).convert("RGB")

def paste_marker_centred(card, marker_id, y, marker_px=None):
    """Paste ArUco marker with white border, centred horizontally. Returns new y."""
    if marker_px is None:
        marker_px = MARKER_PX
    total    = marker_px + BORDER_PX * 2
    aruco    = make_aruco_img(marker_id, marker_px)
    bordered = Image.new("RGB", (total, total), COL_WHITE)
    bordered.paste(aruco, (BORDER_PX, BORDER_PX))
    x = (A5_W - total) // 2
    card.paste(bordered, (x, y))
    return y + total

def draw_header(draw, text, color, header_h):
    draw.rectangle([0, 0, A5_W, header_h], fill=color)
    f = get_font(int(5.5 * MM_TO_PX), bold=True)
    draw.text((A5_W // 2, header_h // 2), text,
              font=f, fill=COL_WHITE, anchor="mm")

# ─── CORNER MARKER CARD ───────────────────────────────────────────────────────
def make_corner_card(marker_id, short_label, description, header_color):
    card  = Image.new("RGB", (A5_W, A5_H), COL_WHITE)
    draw  = ImageDraw.Draw(card)
    M     = int(8 * MM_TO_PX)

    header_h = int(20 * MM_TO_PX)
    draw_header(draw, f"BOARD CORNER — {short_label}", header_color, header_h)
    y = header_h + M

    y = paste_marker_centred(card, marker_id, y)
    y += int(3 * MM_TO_PX)

    # ID label
    f_id = get_font(int(3.2 * MM_TO_PX))
    draw.text((A5_W // 2, y), f"ArUco ID: {marker_id}  |  DICT_4X4_100",
              font=f_id, fill=(150, 150, 150), anchor="mt")
    y += int(9 * MM_TO_PX)

    # Divider
    draw.line([M, y, A5_W - M, y], fill=tuple(COL_BORDER), width=2)
    y += int(5 * MM_TO_PX)

    # Placement
    f_sec = get_font(int(4 * MM_TO_PX), bold=True)
    f_bod = get_font(int(3.5 * MM_TO_PX))
    draw.text((M, y), "PLACEMENT", font=f_sec, fill=tuple(COL_NAVY))
    y += int(6 * MM_TO_PX)
    draw.text((M, y), description, font=f_bod, fill=(60, 60, 60))
    y += int(10 * MM_TO_PX)

    # Mini board diagram
    diag_h = int(30 * MM_TO_PX)
    diag_w = A5_W - 2 * M
    draw.rectangle([M, y, M + diag_w, y + diag_h],
                   outline=tuple(COL_BORDER), width=2)

    f_diag = get_font(int(3 * MM_TO_PX), bold=True)
    corner_coords = {
        0: (M + 4,              y + 4),
        1: (M + diag_w - 45,   y + 4),
        2: (M + 4,              y + diag_h - 18),
        3: (M + diag_w - 45,   y + diag_h - 18),
        4: (M + 4,              y + 4),
        5: (M + diag_w - 45,   y + 4),
        6: (M + 4,              y + diag_h - 18),
        7: (M + diag_w - 45,   y + diag_h - 18),
    }
    for cid, (cx, cy) in corner_coords.items():
        txt   = f"★ ID{marker_id}" if cid == marker_id else f"ID{cid}"
        color = tuple(header_color) if cid == marker_id else tuple(COL_BORDER)
        draw.text((cx, cy), txt, font=f_diag, fill=color)

    # Slot dividers
    f_slot = get_font(int(2.5 * MM_TO_PX))
    n = 5
    sw = diag_w // n
    for s in range(n):
        sx = M + s * sw + sw // 2
        draw.text((sx, y + diag_h // 2), f"Slot {s+1}",
                  font=f_slot, fill=tuple(COL_BORDER), anchor="mm")
        if s < n - 1:
            draw.line([M + (s+1)*sw, y+18, M + (s+1)*sw, y+diag_h-18],
                      fill=tuple(COL_BORDER), width=1)

    draw.rectangle([0, 0, A5_W-1, A5_H-1], outline=tuple(COL_BORDER), width=3)
    return card

# ─── PROCESS CARD ─────────────────────────────────────────────────────────────
def make_process_card(marker_id, process_name, trigger_text):
    card  = Image.new("RGB", (A5_W, A5_H), COL_WHITE)
    draw  = ImageDraw.Draw(card)
    M     = int(8 * MM_TO_PX)

    header_h = int(20 * MM_TO_PX)
    draw_header(draw, "ADDITIONAL PROCESS CARD", COL_PROC_BG, header_h)
    y = header_h + M

    # Process name — compute marker size so name + ArUco = 9cm
    f_name  = get_font(int(5 * MM_TO_PX), bold=True)
    lines   = process_name.split("\n")
    lb0     = draw.textbbox((0, 0), lines[0], font=f_name)
    text_h  = (lb0[3] - lb0[1] + int(1 * MM_TO_PX)) * len(lines)
    local_marker_px = int(90 * MM_TO_PX) - text_h - 2 * BORDER_PX

    for line in lines:
        lb = draw.textbbox((0, 0), line, font=f_name)
        draw.text(((A5_W - (lb[2]-lb[0])) // 2, y),
                  line, font=f_name, fill=tuple(COL_NAVY))
        y += (lb[3] - lb[1]) + int(1 * MM_TO_PX)

    y = paste_marker_centred(card, marker_id, y, marker_px=local_marker_px)
    y += int(3 * MM_TO_PX)

    f_id = get_font(int(3 * MM_TO_PX))
    draw.text((A5_W // 2, y), f"ArUco ID: {marker_id}",
              font=f_id, fill=(150, 150, 150), anchor="mt")
    y += int(8 * MM_TO_PX)

    draw.line([M, y, A5_W - M, y], fill=tuple(COL_BORDER), width=2)
    y += int(5 * MM_TO_PX)

    f_sec  = get_font(int(3.5 * MM_TO_PX), bold=True)
    f_trig = get_font(int(3.2 * MM_TO_PX))
    draw.text((M, y), "TRIGGER CONDITIONS", font=f_sec, fill=tuple(COL_NAVY))
    y += int(6 * MM_TO_PX)

    lines      = trigger_text.split("\n")
    trigger_h  = int(8 * MM_TO_PX) * len(lines) + int(8 * MM_TO_PX)
    draw.rounded_rectangle([M, y, A5_W-M, y+trigger_h],
                           radius=6, fill=tuple(COL_LIGHT),
                           outline=tuple(COL_BORDER), width=1)
    pad = int(4 * MM_TO_PX)
    for li, line in enumerate(lines):
        draw.text((M + pad, y + pad + li * int(8 * MM_TO_PX)),
                  line, font=f_trig, fill=(50, 50, 50))

    draw.rectangle([0, 0, A5_W-1, A5_H-1], outline=tuple(COL_BORDER), width=3)
    return card

# ─── PRINT SHEET (2×2 markers at actual size) ────────────────────────────────
def make_print_sheet(marker_items, title, header_color, marker_px=None,
                     name_above_mm=None):
    """2×2 grid of markers at their actual physical size.
    marker_items: list of (marker_id, label) tuples.
    name_above_mm: if set, draws the label above the marker at that font size (mm).
    """
    if marker_px is None:
        marker_px = MARKER_PX

    total_m  = marker_px + BORDER_PX * 2
    M        = int(8 * MM_TO_PX)
    gap      = int(8 * MM_TO_PX)
    title_h  = int(12 * MM_TO_PX)
    label_h  = int(9  * MM_TO_PX)

    f_lbl    = get_font(int(3 * MM_TO_PX))
    f_name   = get_font(int(name_above_mm * MM_TO_PX), bold=True) if name_above_mm else None
    name_h   = 0
    if f_name:
        tmp = Image.new("RGB", (1, 1))
        nb  = ImageDraw.Draw(tmp).textbbox((0, 0), "Ag", font=f_name)
        name_h = nb[3] - nb[1] + int(2 * MM_TO_PX)

    cell_h   = name_h + total_m + label_h
    sheet_w  = 2 * total_m + gap + 2 * M
    sheet_h  = title_h + 2 * cell_h + gap + 2 * M
    sheet    = Image.new("RGB", (sheet_w, sheet_h), COL_WHITE)
    draw     = ImageDraw.Draw(sheet)

    draw.rectangle([0, 0, sheet_w, title_h], fill=header_color)
    f_t = get_font(int(4 * MM_TO_PX), bold=True)
    draw.text((sheet_w // 2, title_h // 2), title,
              font=f_t, fill=COL_WHITE, anchor="mm")

    for idx, (mid, label) in enumerate(marker_items):
        col = idx % 2
        row = idx // 2
        x   = M + col * (total_m + gap)
        y   = title_h + M + row * (cell_h + gap)

        if f_name:
            nb  = draw.textbbox((0, 0), label, font=f_name)
            nx  = x + (total_m - (nb[2] - nb[0])) // 2
            draw.text((nx, y), label, font=f_name, fill=tuple(COL_NAVY))
        y += name_h

        aruco    = make_aruco_img(mid, marker_px)
        bordered = Image.new("RGB", (total_m, total_m), COL_WHITE)
        bordered.paste(aruco, (BORDER_PX, BORDER_PX))
        sheet.paste(bordered, (x, y))

        lbl_text = f"ID {mid}"
        lb  = draw.textbbox((0, 0), lbl_text, font=f_lbl)
        lx  = x + (total_m - (lb[2] - lb[0])) // 2
        draw.text((lx, y + total_m + int(1 * MM_TO_PX)),
                  lbl_text, font=f_lbl, fill=(150, 150, 150))

    return sheet

# ─── MAIN ─────────────────────────────────────────────────────────────────────
print("=" * 60)
print("TRIAGE GAME — ArUco Marker Generator")
print(f"Dictionary : DICT_4X4_100")
print(f"Marker size: 10cm  ({MARKER_PX}px at {DPI}dpi)")
print("=" * 60)

sets = [
    ("1/3", "Selection Board Corners (IDs 0–3)",
     SELECTION_CORNERS, "selection_board", COL_SEL_BG,
     "SELECTION BOARD — Corner Markers (IDs 0–3)"),
    ("2/3", "Destination Board Corners (IDs 4–7)",
     DESTINATION_CORNERS, "destination_board", COL_DEST_BG,
     "DESTINATION BOARD — Corner Markers (IDs 4–7)"),
]

for step, desc, marker_map, folder, color, sheet_title in sets:
    print(f"\n[{step}] {desc}")
    out_dir = os.path.join(OUTPUT_DIR, folder)
    os.makedirs(out_dir, exist_ok=True)
    cards = {}
    for mid, (label, placement) in marker_map.items():
        card = make_corner_card(mid, label, placement, color)
        fname = os.path.join(out_dir, f"ID{mid:02d}_{label.replace('-','_').replace(' ','')}.png")
        card.save(fname, dpi=(DPI, DPI))
        cards[mid] = card
        print(f"  ID {mid:02d}  {label}")
    items = [(mid, label) for mid, (label, _) in marker_map.items()]
    sheet = make_print_sheet(items, sheet_title, color)
    sheet.save(os.path.join(out_dir, "print_sheet.png"), dpi=(DPI, DPI))
    print(f"  → print_sheet.png saved")

print("\n[3/3] Additional Process Cards (IDs 50–53)")
proc_dir = os.path.join(OUTPUT_DIR, "processes")
os.makedirs(proc_dir, exist_ok=True)
proc_cards = {}
proc_slugs = {50:"call_rapid_response", 51:"request_stretcher",
              52:"direct_companion",    53:"request_interpreter"}
for mid, (name, trigger) in PROCESSES.items():
    card = make_process_card(mid, name, trigger)
    fname = os.path.join(proc_dir, f"ID{mid:02d}_{proc_slugs[mid]}.png")
    card.save(fname, dpi=(DPI, DPI))
    proc_cards[mid] = card
    print(f"  ID {mid:02d}  {name.replace(chr(10),' ')}")
proc_items = [(mid, name.replace("\n", " ")) for mid, (name, _) in PROCESSES.items()]
sheet = make_print_sheet(proc_items, "ADDITIONAL PROCESS CARDS (IDs 50–53)", COL_PROC_BG,
                         name_above_mm=6)
sheet.save(os.path.join(proc_dir, "print_sheet.png"), dpi=(DPI, DPI))
print(f"  → print_sheet.png saved")

print("\n" + "=" * 60)
print(f"All markers saved in: {OUTPUT_DIR}/")
print()
print("FULL ID REFERENCE:")
print("   0– 3  Selection board corners")
print("   4– 7  Destination board corners")
print("  10–29  Set A patient cards (generated by generate_patient_cards.py)")
print("  30–49  Set B patient cards (generated by generate_patient_cards.py)")
print("  50–53  Additional process cards")
print()
print("Print all print_sheet.png at ACTUAL SIZE (100%, no scaling).")
print("Tip: laminate corner markers and process cards for durability.")
print("=" * 60)
