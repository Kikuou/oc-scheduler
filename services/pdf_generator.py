"""reportlabによるPDF帳票生成"""
import os
from io import BytesIO
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    PageBreak, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from db.database import SessionLocal
from db.models import Occasion, Event, EventAssignment, Staff, OccasionProgramLane

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_PATH = os.path.join(BASE_DIR, "fonts", "ipaexg.ttf")

_font_name = "Helvetica"


def _register_font():
    global _font_name
    if os.path.exists(FONT_PATH):
        try:
            pdfmetrics.registerFont(TTFont("IPAex", FONT_PATH))
            _font_name = "IPAex"
            return
        except Exception:
            pass
    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
        _font_name = "HeiseiKakuGo-W5"
    except Exception:
        _font_name = "Helvetica"


def _font():
    return _font_name


SLOT_MIN = 10
LANE_COLORS_PDF = [
    colors.Color(0.83, 0.93, 0.99),  # 0: 青
    colors.Color(1.00, 0.91, 0.80),  # 1: オレンジ
    colors.Color(0.85, 0.94, 0.85),  # 2: 緑
    colors.Color(0.94, 0.85, 0.94),  # 3: 紫
    colors.Color(0.94, 0.94, 0.85),  # 4: 黄緑
]
COLOR_HEADER = colors.Color(0.2, 0.24, 0.28)


def _to_min(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m


def _from_min(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _lane_color(lane_id, lane_ids_ordered):
    if lane_id in lane_ids_ordered:
        return LANE_COLORS_PDF[lane_ids_ordered.index(lane_id) % 5]
    return colors.Color(0.93, 0.93, 0.93)


# ─── 全体スケジュール PDF（時間×実施枠） ──────────────────────
def generate_schedule_pdf(occasion_id: int) -> BytesIO:
    _register_font()
    db = SessionLocal()
    o = db.get(Occasion, occasion_id)
    events = db.query(Event).filter(Event.occasion_id == occasion_id).order_by(Event.start_time).all()

    # 開催の実施枠を取得
    opl_list = (db.query(OccasionProgramLane)
                .filter(OccasionProgramLane.occasion_id == occasion_id)
                .order_by(OccasionProgramLane.sort_order).all())
    lanes_map = {opl.program_lane_id: opl.program_lane for opl in opl_list}
    lane_ids_ordered = [opl.program_lane_id for opl in opl_list]

    # イベントが属する実施枠のみに絞る
    used_lane_ids = {e.program_lane_id for e in events if e.program_lane_id in lane_ids_ordered}
    lane_ids = [lid for lid in lane_ids_ordered if lid in used_lane_ids]
    lanes = [lanes_map[lid] for lid in lane_ids if lid in lanes_map]

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                             leftMargin=10*mm, rightMargin=10*mm,
                             topMargin=12*mm, bottomMargin=10*mm)

    fn = _font()
    cell_style = ParagraphStyle("cell", fontName=fn, fontSize=7, leading=9)
    title_style = ParagraphStyle("title", fontName=fn, fontSize=12, leading=16)
    story = []

    for period, label in [("am", "午前"), ("pm", "午後")]:
        period_events = [e for e in events if (
            period == "am" and e.start_time < "12:00" or
            period == "pm" and e.end_time > "12:00"
        )]
        if not period_events:
            continue

        s_min = min(_to_min(e.start_time) for e in period_events)
        e_min = max(_to_min(e.end_time) for e in period_events)
        s_min = (s_min // SLOT_MIN) * SLOT_MIN
        e_min = ((e_min + SLOT_MIN - 1) // SLOT_MIN) * SLOT_MIN
        slots = [_from_min(t) for t in range(s_min, e_min, SLOT_MIN)]

        header_row = [Paragraph("時間", cell_style)]
        header_row += [Paragraph(lanes_map[lid].name, cell_style) for lid in lane_ids if lid in lanes_map]

        cells_map: dict[str, dict[int, dict | None]] = {s: {lid: None for lid in lane_ids} for s in slots}
        for e in period_events:
            if e.program_lane_id not in lane_ids:
                continue
            e_start = _to_min(e.start_time)
            e_end = _to_min(e.end_time)
            rowspan = (e_end - e_start) // SLOT_MIN
            slot_key = _from_min((e_start // SLOT_MIN) * SLOT_MIN)
            if slot_key not in cells_map:
                continue
            assignments = [(a.role.name, a.staff.name) for a in e.assignments]
            cells_map[slot_key][e.program_lane_id] = {
                "event": e, "rowspan": rowspan, "assignments": assignments
            }
            for i in range(1, rowspan):
                nk = _from_min(e_start + i * SLOT_MIN)
                if nk in cells_map:
                    cells_map[nk][e.program_lane_id] = {"skip": True}

        table_data = [header_row]
        span_cmds = []
        bg_cmds = []

        for row_idx, slot in enumerate(slots):
            r = row_idx + 1
            row = [Paragraph(slot, cell_style)]
            for col_idx, lid in enumerate(lane_ids):
                c = col_idx + 1
                cell = cells_map[slot][lid]
                if cell is None:
                    row.append("")
                elif cell.get("skip"):
                    row.append("")
                else:
                    ev = cell["event"]
                    rs = cell["rowspan"]
                    lines = [ev.title]
                    if ev.venue:
                        lines.append(f"📍{ev.venue.name}")
                    for role, name in cell["assignments"]:
                        lines.append(f"{role}：{name}")
                    if ev.note:
                        lines.append(f"（{ev.note}）")
                    lines.append(f"{ev.start_time}-{ev.end_time}")
                    row.append(Paragraph("\n".join(lines), cell_style))
                    if rs > 1:
                        span_cmds.append(("SPAN", (c, r), (c, r + rs - 1)))
                    bg = _lane_color(ev.program_lane_id, lane_ids_ordered)
                    bg_cmds.append(("BACKGROUND", (c, r), (c, r + rs - 1), bg))
            table_data.append(row)

        n_lanes = len(lane_ids)
        if n_lanes == 0:
            continue
        col_widths = [15*mm] + [int((landscape(A4)[0] - 20*mm - 15*mm) / n_lanes) for _ in lane_ids]

        tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
        style_cmds = [
            ("FONTNAME", (0, 0), (-1, -1), fn),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_HEADER),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (0, -1), [colors.Color(0.96, 0.96, 0.96), colors.white]),
        ] + span_cmds + bg_cmds
        tbl.setStyle(TableStyle(style_cmds))

        title_text = f"旭川市立大学 オープンキャンパス スケジュール　{o.year}年度 {o.name}（{o.date}）　{label}"
        story.append(Paragraph(title_text, title_style))
        story.append(Spacer(1, 3*mm))
        story.append(tbl)
        story.append(PageBreak())

    if not story:
        story.append(Paragraph("イベントがありません", title_style))

    db.close()
    doc.build(story)
    buf.seek(0)
    return buf


# ─── 属性別担当一覧 PDF ───────────────────────────────────────
def generate_stafflist_pdf(occasion_id: int) -> BytesIO:
    _register_font()
    db = SessionLocal()
    o = db.get(Occasion, occasion_id)
    assignments = (db.query(EventAssignment)
                   .join(Event).join(Staff)
                   .filter(Event.occasion_id == occasion_id)
                   .order_by(Staff.staff_type, Staff.department, Staff.grade, Staff.name,
                             Event.start_time)
                   .all())
    db.close()

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                             leftMargin=15*mm, rightMargin=15*mm,
                             topMargin=15*mm, bottomMargin=12*mm)
    fn = _font()
    title_style = ParagraphStyle("title", fontName=fn, fontSize=11, leading=15)
    section_style = ParagraphStyle("section", fontName=fn, fontSize=9, leading=12,
                                   backColor=colors.Color(0.2, 0.24, 0.28),
                                   textColor=colors.white, spaceBefore=4, leftIndent=2)
    person_style = ParagraphStyle("person", fontName=fn, fontSize=8.5, leading=12,
                                  spaceBefore=4, fontWeight="bold")
    event_style = ParagraphStyle("event", fontName=fn, fontSize=8, leading=11, leftIndent=12)

    story = []
    story.append(Paragraph(
        f"担当者一覧　{o.year}年度 {o.name}（{o.date}）", title_style))
    story.append(Spacer(1, 4*mm))

    from collections import defaultdict
    groups = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    staff_info: dict[int, Staff] = {}

    for a in assignments:
        s = a.staff
        staff_info[s.id] = s
        key = (s.department or "", s.grade or 0)
        groups[s.staff_type][key][s.id].append(a)

    ORDER = ["教員", "職員", "学生"]
    for staff_type in ORDER:
        if staff_type not in groups:
            continue
        story.append(Paragraph(f"　{staff_type}　", section_style))

        for (dept, grade), staff_events in sorted(groups[staff_type].items(),
                                                   key=lambda x: (x[0][0], x[0][1])):
            if staff_type == "学生":
                sub_label = f"《{dept} {grade}年》" if dept else f"《{grade}年》"
                story.append(Paragraph(sub_label, person_style))

            for sid, evs in sorted(staff_events.items(),
                                    key=lambda x: staff_info[x[0]].name):
                s = staff_info[sid]
                label = s.name
                if staff_type != "学生" and dept:
                    label += f"（{dept}）"
                story.append(Paragraph(f"■ {label}", person_style))

                for a in sorted(evs, key=lambda x: x.event.start_time):
                    ev = a.event
                    lane_name = ev.program_lane.name if ev.program_lane else "未分類"
                    venue_name = ev.venue.name if ev.venue else ""
                    line = (f"{ev.start_time}–{ev.end_time}　"
                            f"[{lane_name}]　{venue_name}　{ev.title}（{a.role.name}）")
                    story.append(Paragraph(line, event_style))

        story.append(Spacer(1, 3*mm))

    doc.build(story)
    buf.seek(0)
    return buf
