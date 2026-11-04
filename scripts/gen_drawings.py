# -*- coding: utf-8 -*-
"""
gen_drawings.py — рабочие чертежи 2D (DXF + PDF):
 - детали PSH24/PSH20: 3 вида + изометрия, размеры, отверстия, ТТ;
 - сборочные единицы: виды с взаимным скрытием, позиции, состав.
"""
import os, sys, math, time, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D
from sheetlib import Sheet, pick_scale
from views import hlr_view, bbox2d, view_project

from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDF import TDF_LabelSequence, TDF_Label
from OCP.TDataStd import TDataStd_Name
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE
from OCP.TopoDS import TopoDS
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

import glob as _glob

OUT_DXF = os.path.join(D.ROOT, '01_Чертежи_2D', 'DXF')
OUT_PDF = os.path.join(D.ROOT, '01_Чертежи_2D', 'PDF')
os.makedirs(OUT_DXF, exist_ok=True)
os.makedirs(OUT_PDF, exist_ok=True)

# ------------------------------------------------------------------ STEP
def label_name(label):
    n = TDataStd_Name()
    if not label.FindAttribute(TDataStd_Name.GetID_s(), n):
        return ''
    s = n.Get()
    try:
        return ''.join(s.Value(i) for i in range(1, s.Length() + 1))
    except Exception:
        return str(s)

_READER_KEEPALIVE = []   # ридер должен жить всё время работы с shapes!

def load_step():
    f = _glob.glob(os.path.join(D.ROOT, '..', 'drive_model', '**', '*.stp'), recursive=True)
    if not f:
        f = _glob.glob(os.path.join(D.ROOT, '05_Модель', '*.stp'))
    reader = STEPCAFControl_Reader()
    _READER_KEEPALIVE.append(reader)
    reader.SetNameMode(True)
    reader.ReadFile(f[0])
    doc = TDocStd_Document(TCollection_ExtendedString("d"))
    _READER_KEEPALIVE.append(doc)
    reader.Transfer(doc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    free = TDF_LabelSequence()
    st.GetFreeShapes(free)
    return st, free.Value(1)

SHAPES = {}    # canonical name -> shape (prototype coords)
ASM_LABELS = {}  # canonical name -> label (for components walk)

def walk_collect(st, label, path=(), depth=0):
    global _WALK_N
    _WALK_N += 1
    if _WALK_N % 500 == 0:
        print(f"  walk #{_WALK_N} depth={depth} name={label_name(label)!r}", flush=True)
    name = label_name(label)
    ref = TDF_Label()
    is_ref = st.GetReferredShape_s(label, ref)
    target = ref if (is_ref and not ref.IsNull()) else label
    tname = D.canonical(label_name(target) or name)
    if tname in path:
        return
    if tname in SHAPES and st.IsAssembly_s(target):
        return  # уже обойдено
    if st.IsAssembly_s(target):
        SHAPES[tname] = st.GetShape_s(target)
        ASM_LABELS[tname] = target
        comps = TDF_LabelSequence()
        st.GetComponents_s(target, comps)
        for i in range(1, comps.Length() + 1):
            walk_collect(st, comps.Value(i), path + (tname,), depth + 1)
    else:
        SHAPES[tname] = st.GetShape_s(target)

_WALK_N = 0

def component_centers(st, asm_label):
    """{имя детали: центр массы в координатах сборки} для позиционных обозначений."""
    comps = TDF_LabelSequence()
    st.GetComponents_s(asm_label, comps)
    out = {}
    for i in range(1, comps.Length() + 1):
        lab = comps.Value(i)
        ref = TDF_Label()
        is_ref = st.GetReferredShape_s(lab, ref)
        target = ref if (is_ref and not ref.IsNull()) else lab
        nm = D.canonical(label_name(target) or label_name(lab))
        sh = st.GetShape_s(lab)   # с учётом размещения
        box = Bnd_Box()
        BRepBndLib.Add_s(sh, box, True)
        if box.IsVoid():
            continue
        x0, y0, z0, x1, y1, z1 = box.Get()
        c = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
        if nm not in out:
            out[nm] = c
    return out

def filtered_shape(st, asm_label, max_mass_kg=0.25):
    """Облегчённая копия сборки для HLR: без мелкого крепежа (гайки/шайбы).
    Существенно снижает расход памяти при построении скрытых линий."""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    from OCP.TDF import TDF_LabelSequence, TDF_Label
    builder = BRep_Builder()
    comp = TopoDS_Compound()
    builder.MakeCompound(comp)
    comps = TDF_LabelSequence()
    st.GetComponents_s(asm_label, comps)
    for i in range(1, comps.Length() + 1):
        lab = comps.Value(i)
        ref = TDF_Label()
        is_ref = st.GetReferredShape_s(lab, ref)
        target = ref if (is_ref and not ref.IsNull()) else lab
        nm = D.canonical(label_name(target) or label_name(lab))
        if D.is_purchased(nm) and D.part_mass_kg(nm) < max_mass_kg:
            continue  # мелкий крепёж не показываем
        builder.Add(comp, st.GetShape_s(lab))
    return comp

# ------------------------------------------------------------------ отверстия
def hole_groups(shape):
    """Группы цилиндрических отверстий: [{d, axis, count, centers}] — по уникальным осям.

    Центр отверстия — проекция центра масс цилиндрической грани на её ось:
    Location() геометрии цилиндра лежит на оси в произвольной точке (часто
    далеко за пределами грани), из-за чего проекция уходила за рамку листа.
    """
    holes = {}
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current())
        ad = BRepAdaptor_Surface(f)
        if ad.GetType() == GeomAbs_Cylinder:
            cy = ad.Cylinder()
            r = cy.Radius()
            if 0.5 < r <= 60:
                ax = cy.Axis().Direction()
                v = (abs(ax.X()), abs(ax.Y()), abs(ax.Z()))
                dom = v.index(max(v))
                # центр масс грани -> проекция на ось цилиндра
                props = GProp_GProps()
                BRepGProp.SurfaceProperties_s(f, props)
                com = props.CentreOfMass()
                loc = cy.Axis().Location()
                t = ((com.X() - loc.X()) * ax.X() +
                     (com.Y() - loc.Y()) * ax.Y() +
                     (com.Z() - loc.Z()) * ax.Z())
                pos = [loc.X() + t * ax.X(),
                       loc.Y() + t * ax.Y(),
                       loc.Z() + t * ax.Z()]
                cross = tuple(round(pos[i], 1) for i in range(3) if i != dom)
                key = (round(2 * r, 1), dom, cross)
                if key not in holes:
                    holes[key] = dict(d=round(2 * r, 1), axis=dom,
                                      center=tuple(pos))
        ex.Next()
    groups = {}
    for (d, dom, cross), info in holes.items():
        g = groups.setdefault((d, dom), dict(d=d, axis=dom, count=0, centers=[]))
        g['count'] += 1
        g['centers'].append(info['center'])
    return list(groups.values())

# ------------------------------------------------------------------ техтребования
TECH = {
    'plate': [
        '1. Общие требования — по ГОСТ 2.312-72.',
        '2. Неуказанные предельные отклонения размеров — по ГОСТ 25058-2016.',
        '3. Резка лазерная/плазменная по контуру (DXF, масштаб 1:1); допуск ±0,5 мм.',
        '4. Заусенцы и острые кромки — по ГОСТ 14637-89 (не более R0,5).',
        '5. Покрытие лакокрасочное — по ГОСТ 9.401-91, перед сборкой.',
    ],
    'bent': [
        '1. Общие требования — по ГОСТ 2.312-72.',
        '2. Неуказанные предельные отклонения размеров — по ГОСТ 25058-2016.',
        '3. Заготовка — лист, раскрой по DXF; гибка на листогибочном прессе.',
        '4. Радиусы гибов и положение линий гиба — по данному чертежу.',
        '5. Покрытие — по ГОСТ 9.401-91.',
    ],
    'tube': [
        '1. Общие требования — по ГОСТ 2.312-72.',
        '2. Неуказанные предельные отклонения размеров — по ГОСТ 25058-2016.',
        '3. Распиловка в размер на ленточнопильном станке; снятие фасок 1×45°.',
        '4. Отклонение торцов от перпендикулярности — не более 0,5 мм.',
        '5. Покрытие — по ГОСТ 9.401-91.',
    ],
    'shaft': [
        '1. Общие требования — по ГОСТ 2.312-72.',
        '2. Неуказанные предельные отклонения размеров — по ГОСТ 25058-2016.',
        '3. Неуказанная шероховатость поверхности — Ra 12,5 (ГОСТ 2789-2015).',
        '4. Снятие фасок 1×45°, притупление кромок до R0,5.',
    ],
    'profile': [
        '1. Общие требования — по ГОСТ 2.312-72.',
        '2. Неуказанные предельные отклонения размеров — по ГОСТ 25058-2016.',
        '3. Распиловка в размер; торцы обработать, снять заусенцы.',
    ],
    'other': [
        '1. Общие требования — по ГОСТ 2.312-72.',
        '2. Неуказанные предельные отклонения размеров — по ГОСТ 25058-2016.',
        '3. Неуказанная шероховатость — Ra 12,5 (ГОСТ 2789-2015).',
        '4. Снятие заусенцев и острых кромок.',
    ],
    'assembly': [
        '1. Сборку и сварку выполнять по данному чертежу.',
        '2. Швы сварные — по ГОСТ 14771-2005 / ГОСТ 5264-80; контроль по ГОСТ 3242-79.',
        '3. Отклонения при сборке — по ГОСТ 25058-2016, класс точности Н.',
        '4. Покрытие лакокрасочное — по ГОСТ 9.401-91 (цвет по согласованию).',
        '5. Трущиеся поверхности смазать ЛИТОЛ-24 (ГОСТ 21150-2018).',
    ],
}

# ------------------------------------------------------------------ отрисовка видов
def draw_polys(sheet, polys, ox, oy, s, col='outline', lw='thick', dash=None):
    for pl in polys:
        pts = [(x * s + ox, y * s + oy) for x, y in pl]
        for a, b in zip(pts, pts[1:]):
            sheet.line(a, b, col=col, lw=lw, dash=dash)

def place_view(polys, ox, oy, s):
    x0, y0, x1, y1 = bbox2d(polys)
    return (x0 * s + ox, y0 * s + oy, x1 * s + ox, y1 * s + oy)

# ------------------------------------------------------------------ вспомогательное
def _fit(s, max_w, size):
    """Обрезка строки под ширину max_w мм (≈0.62*size на знак)."""
    if not s:
        return s
    if 0.62 * size * len(s) <= max_w:
        return s
    n = int(max_w / (0.62 * size))
    return (s[:max(n - 1, 1)] + '…') if n >= 2 else s[:1]


def _chain_segs(coords, min_len=7.0):
    """Цепочка по координатам (на листе): слияние сегментов короче min_len."""
    segs = []
    for a, b in zip(coords, coords[1:]):
        if b - a <= 1e-9:
            continue
        if segs and (segs[-1][1] - segs[-1][0]) < min_len:
            segs[-1] = (segs[-1][0], b)
        else:
            segs.append((a, b))
    if len(segs) > 1 and (segs[-1][1] - segs[-1][0]) < min_len:
        a, b = segs.pop()
        segs[-1] = (segs[-1][0], b)
    return segs


def _chain_groups(segs, s, fmt, text_size=3.0):
    """Группировка одинаковых сегментов в 'N×L'; при нехватке места — поштучно."""
    out = []
    i = 0
    while i < len(segs):
        j = i
        while j + 1 < len(segs) and abs((segs[j + 1][1] - segs[j + 1][0]) -
                                        (segs[j][1] - segs[j][0])) < 0.3:
            j += 1
        n = j - i + 1
        unit = (segs[i][1] - segs[i][0]) / s
        x0, x1 = segs[i][0], segs[j][1]
        if n == 1:
            out.append((x0, x1, fmt(unit)))
        else:
            lab = f"{n}×{fmt(unit)}"
            if 0.62 * text_size * len(lab) + 3 <= (x1 - x0):
                out.append((x0, x1, lab))
            else:
                for k in range(i, j + 1):
                    out.append((segs[k][0], segs[k][1],
                                fmt((segs[k][1] - segs[k][0]) / s)))
        i = j + 1
    return out


def _draw_chain(sheet, edge, edge_from, feats, line_pos, s, fmt,
                horiz=True, text_size=3.0):
    """Цепочка размеров от базовой грани до точек (координаты на листе).
    edge - координата базовой грани; edge_from - вторая координата угла грани;
    feats - [(координата точки, начало выносной линии)]."""
    coords = sorted({round(c, 2) for c, _ in feats if c > edge + 0.5})
    if not coords:
        return
    segs = _chain_segs([edge] + coords)
    if not segs:
        return
    for (a, b, lab) in _chain_groups(segs, s, fmt, text_size):
        p1 = (a, line_pos) if horiz else (line_pos, a)
        p2 = (b, line_pos) if horiz else (line_pos, b)
        sheet.dim_linear(p1, p2, 0, text=lab, text_size=text_size)
    # выносные линии от точек к цепочке
    for c, st in feats:
        if abs(c - edge) < 0.5:
            continue
        if horiz:
            sheet.line((c, st), (c, line_pos + 1), col='dim', lw='thin')
        else:
            sheet.line((st, c), (line_pos - 1, c), col='dim', lw='thin')
    # продолжение базовой грани до цепочки
    if horiz:
        sheet.line((edge, edge_from), (edge, line_pos + 1), col='dim', lw='thin')
    else:
        sheet.line((edge_from, edge), (line_pos - 1, edge), col='dim', lw='thin')


def _rect_in(r, x, y, pad=0.0):
    return (r[0] - pad <= x <= r[2] + pad) and (r[1] - pad <= y <= r[3] + pad)


# ------------------------------------------------------------------ чертёж детали
def make_part_drawing(name, shape):
    kind = D.part_kind(name)
    g = D.geom_of(name)
    if not g or 'error' in g:
        return None

    axes = {'x': g['dx'], 'y': g['dy'], 'z': g['dz']}
    h_ax = max(axes, key=axes.get)
    rest = [a for a in axes if a != h_ax]
    v_ax = max(rest, key=lambda a: axes[a])
    d_ax = [a for a in rest if a != v_ax][0]
    AXV = {'x': (1, 0, 0), 'y': (0, 1, 0), 'z': (0, 0, 1)}
    AXI = {'x': 0, 'y': 1, 'z': 2}

    views = [
        ('main', d_ax, v_ax),
        ('top', v_ax, d_ax),
        ('left', h_ax, v_ax),
    ]
    proj = {}
    for key, da, ua in views:
        v, h = hlr_view(shape, AXV[da], AXV[ua])
        proj[key] = (v, h)
    # изометрия — длинная ось горизонтальна
    hv, vv, dv = AXV[h_ax], AXV[v_ax], AXV[d_ax]
    iso_dir = tuple(-(0.8 * hv[i] + 1.0 * dv[i] + 0.62 * vv[i]) for i in range(3))
    iso_v, _ = hlr_view(shape, iso_dir, vv)

    sheet = Sheet('A3', True, designation=name, name=D.part_name(name),
                  material=D.part_material_ru(name).split(' (')[0],
                  mass=f"{D.part_mass_kg(name):.2f} кг", scale_text='')
    ax0, ay0, ax1, ay1 = sheet.frame_inner
    # поле чертежа (без зоны ТТ внизу)
    fx0, fy0, fx1, fy1 = ax0 + 26, ay0 + 76, ax1 - 6, ay1 - 18
    FW, FH = fx1 - fx0, fy1 - fy0

    fmt = lambda val: (f"{val:.1f}".rstrip('0').rstrip('.')
                       if abs(val - round(val)) > 0.05 else f"{int(round(val))}")

    bb = {k: bbox2d(v) for k, (v, h) in proj.items()}
    bb['iso'] = bbox2d(iso_v)
    wm, hm = bb['main'][2] - bb['main'][0], bb['main'][3] - bb['main'][1]
    wt, ht = bb['top'][2] - bb['top'][0], bb['top'][3] - bb['top'][1]
    ws, hs = bb['left'][2] - bb['left'][0], bb['left'][3] - bb['left'][1]
    wi, hi = bb['iso'][2] - bb['iso'][0], bb['iso'][3] - bb['iso'][1]

    # ---- подбор масштаба (проверка размещения всех видов) ----
    place = None
    for den in (1, 2, 5, 10, 20, 50, 100):
        s = 1.0 / den
        Wm, Hm = wm * s, hm * s
        Ws, Hs = ws * s, hs * s
        Ht = ht * s
        if 19 + Wm + 26 + max(Ws, 4) > FW:      # поле слева + главный + зазор под Y-цепочку + боковой
            continue
        if 17 + Hm + 26 + 2 + Ht > FH:          # размер сверху + главный + цепочка + верхний
            continue
        mx0 = fx0 + 19
        my1 = fy1 - 17
        my0 = my1 - Hm
        if my0 - 26 - Ht < fy0 + 2:
            continue
        place = (den, s, mx0, my0, my1, Wm, Hm, Ws, Hs, Ht)
        break
    if place is None:                            # запасной вариант
        den = 100
        s = 0.01
        Wm, Hm, Ws, Hs, Ht = wm * s, hm * s, ws * s, hs * s, ht * s
        mx0 = fx0 + 19
        my1 = fy1 - 17
        my0 = my1 - Hm
    den, s, mx0, my0, my1, Wm, Hm, Ws, Hs, Ht = place or (
        den, s, mx0, my0, my1, Wm, Hm, Ws, Hs, Ht)
    sheet.scale_text = f"1:{den}" if den >= 1 else f"{den}:1"
    mx1 = mx0 + Wm

    # ---- размещение видов ----
    origins = {'main': (mx0 - bb['main'][0] * s, my0 - bb['main'][1] * s)}
    ty1 = my0 - 26
    origins['top'] = (mx0 - bb['top'][0] * s, ty1 - bb['top'][3] * s)
    sx0 = mx1 + 26
    origins['left'] = (sx0 - bb['left'][0] * s, my1 - bb['left'][3] * s)

    for key in ('main', 'top', 'left'):
        v, h = proj[key]
        tx, ty = origins[key]
        draw_polys(sheet, v, tx, ty, s, 'outline', 'thick')
        draw_polys(sheet, h, tx, ty, s, 'hidden', 'thin', 'hidden')
        proj[key] = (v, h, tx, ty, place_view(v, tx, ty, s))

    # ---- изометрия: первая свободная зона ----
    ty0 = ty1 - Ht
    zones = [
        (mx1 + 26, ty1),                    # справа-снизу (под боковым видом)
        (sx0 + max(Ws, 4) + 10, my1),       # справа от бокового вида
        (fx0, ty0),                         # под видом сверху, во всю ширину поля
    ]
    iso_rect = None
    for cand_s in (s, s / 2, s / 4, s / 5, s / 10):
        Wi, Hi = wi * cand_s, hi * cand_s
        for zx, ztop in zones:
            if zx + Wi <= fx1 and ztop - Hi >= fy0:
                iso_rect = (zx, ztop - Hi, zx + Wi, ztop)
                iso_s = cand_s
                break
        if iso_rect:
            break
    if iso_rect:
        iso_lbl = ('Вид изометрический' if abs(iso_s - s) < 1e-9 else
                   f"Вид изометрический (1:{int(round(1 / iso_s))})")
        ox = iso_rect[0] - bb['iso'][0] * iso_s
        oy = iso_rect[3] - bb['iso'][3] * iso_s
        draw_polys(sheet, iso_v, ox, oy, iso_s, 'outline', 'thin')
        lw_ = 0.62 * 3.5 * len(iso_lbl)
        if iso_rect[2] + 6 + lw_ <= fx1:
            sheet.text((iso_rect[2] + 6, iso_rect[1] + 4), iso_lbl,
                       size=3.5, col='text')
        elif iso_rect[0] - 6 - lw_ >= fx0:
            sheet.text((iso_rect[0] - 6, iso_rect[1] + 4), iso_lbl,
                       size=3.5, ha='right', col='text')
        elif iso_rect[1] - 5 >= fy0:
            sheet.text((iso_rect[0], iso_rect[1] - 5), iso_lbl,
                       size=3.5, col='text')
        else:
            sheet.text((iso_rect[0], iso_rect[3] + 5), iso_lbl,
                       size=3.5, col='text')

    # ---- размеры главного вида ----
    x0, y0, x1, y1 = proj['main'][4]
    sheet.dim_linear((x0, y1), (x1, y1), 12, text=fmt(axes[h_ax]))
    sheet.dim_linear((x0, y0), (x0, y1), 14, text=fmt(axes[v_ax]))
    # глубина - на виде сверху (слева)
    a0, b0, a1, b1 = proj['top'][4]
    sheet.dim_linear((a0, b0), (a0, b1), 10, text=fmt(axes[d_ax]))

    # ---- отверстия ----
    all_holes = hole_groups(shape)
    holes = [hg for hg in all_holes if hg['axis'] == AXI[d_ax]]
    agg = {}
    for hg in all_holes:
        agg[hg['d']] = agg.get(hg['d'], 0) + hg['count']
    note = [f"Ø{d:g} — {c} шт." for d, c in sorted(agg.items(), key=lambda kv: -kv[0])]
    if note:
        sheet.text((ax0 + 5, ay0 + 68),
                   _fit('Отверстия: ' + '; '.join(note[:8]), ax1 - ax0 - 12, 3.2),
                   size=3.2, col='note')
    if holes:
        tx_, ty_ = origins['main']
        feats = []
        for hg in holes:
            for c in hg['centers']:
                vx, vy = view_project(c, AXV[d_ax], AXV[v_ax])
                feats.append((vx * s + tx_, vy * s + ty_,
                              hg['d'] / 2 * s))
        # центровые оси (концы не выходят за рамку листа)
        L, B, R, T = ax0 + 0.5, ay0 + 0.5, ax1 - 0.5, ay1 - 0.5
        for (cx_, cy_, r_) in feats:
            m = max(r_ + 1.5, 2.0)
            if B <= cy_ <= T and cx_ - m < cx_ + m:
                sheet.line((max(L, cx_ - m), cy_), (min(R, cx_ + m), cy_),
                           col='center', lw='hair', dash='center')
            if L <= cx_ <= R and cy_ - m < cy_ + m:
                sheet.line((cx_, max(B, cy_ - m)), (cx_, min(T, cy_ + m)),
                           col='center', lw='hair', dash='center')
        # цепочка X (под главным видом) и Y (справа от главного вида),
        # замкнутая на дальнюю грань вида — суммы сходятся с общими размерами
        _draw_chain(sheet, x0, y0,
                    [(fx, cy - r_ - 2) for fx, cy, r_ in feats] + [(x1, y0)],
                    y0 - 16, s, fmt, horiz=True)
        _draw_chain(sheet, y0, x1,
                    [(fy, cx + r_ + 2) for cx, fy, r_ in feats] + [(y1, x1)],
                    x1 + 16, s, fmt, horiz=False)
        # вызовный размер на самое крупное отверстие
        big = max(holes, key=lambda hg: hg['d'])
        c = big['centers'][0]
        vx, vy = view_project(c, AXV[d_ax], AXV[v_ax])
        px, py = vx * s + tx_, vy * s + ty_
        txt = (f"{big['count']}×Ø{big['d']:g}" if big['count'] > 1
               else f"Ø{big['d']:g}")
        if py < y1 - 25:
            right = px < (fx0 + fx1) / 2
            ang = 45 if right else 135
        else:  # у верхнего края — горизонтальная полка внутрь вида
            right = px < fx1 - 60
            ang = 0 if right else 180
        sheet.dim_diameter((px, py), big['d'] / 2 * s, ang, text=txt,
                           shelf_dir=1 if right else -1)

    # ---- технические требования ----
    yy = ay0 + 58
    sheet.text((ax0 + 5, yy), 'Технические требования:', size=3.5, col='text')
    for i, t in enumerate(TECH.get(kind, TECH['other'])):
        sheet.text((ax0 + 5, yy - 6 - i * 5), _fit(t, ax1 - 185 - ax0 - 10, 3.0),
                   size=3.0, col='text')
    return sheet

# ------------------------------------------------------------------ сборочный чертёж
def total_instances(name):
    kids = D.TREE.get(name, {})
    if not kids:
        return 1
    return sum(q * total_instances(ch) for ch, q in kids.items())

def make_asm_drawing(st, name):
    shape = SHAPES[name]
    # для крупных сборок HLR строим по облегчённой копии (без мелкого крепежа)
    hlr_shape = filtered_shape(st, ASM_LABELS[name]) if total_instances(name) > 400 else shape
    sheet = Sheet('A2', True, designation=name, name=D.part_name(name),
                  material='—', mass=f"{D.part_mass_kg(name):.1f} кг", scale_text='')
    ax0, ay0, ax1, ay1 = sheet.frame_inner

    # позиционные обозначения (верхний уровень)
    centers = component_centers(st, ASM_LABELS[name])
    kids = D.TREE.get(name, {})
    pos_list = []
    for i, (ch, q) in enumerate(sorted(kids.items()), 1):
        c = centers.get(ch)
        if c is None:
            continue
        pos_list.append((i, ch, q, c))

    row_h, col_w = 5.0, 132
    n = max(len(pos_list), 1)
    ncols = 2 if n > 28 else 1
    per_col = (n + ncols - 1) // ncols
    table_top = ay0 + 8 + per_col * row_h + 8

    v, h = hlr_view(hlr_shape, (0, -1, 0), (0, 0, 1), with_hidden=False)
    v2, h2 = hlr_view(hlr_shape, (1, 0, 0), (0, 0, 1), with_hidden=False)
    hv, vv, dv = (1, 0, 0), (0, 1, 0), (0, 0, 1)
    iso_dir = tuple(-(0.8 * hv[i] + 1.0 * dv[i] + 0.62 * vv[i]) for i in range(3))
    iso_v, _ = hlr_view(hlr_shape, iso_dir, vv, with_hidden=False)
    bb1, bb2, bbi = bbox2d(v), bbox2d(v2), bbox2d(iso_v)
    w1, h1 = bb1[2] - bb1[0], bb1[3] - bb1[1]
    w2, h2b = bb2[2] - bb2[0], bb2[3] - bb2[1]
    wi, hi = bbi[2] - bbi[0], bbi[3] - bbi[1]

    # область видов (над таблицей и ТТ)
    RX0, RX1 = ax0 + 8, ax1 - 6
    RY0 = max(table_top + 6, ay0 + 114)
    RY1 = ay1 - 10

    # ---- подбор масштаба с проверкой размещения ----
    den, s, front, side, iso_zone, iso_sc = None, None, None, None, None, None
    for cand in (1, 2, 5, 10, 20, 50, 100):
        sc = 1.0 / cand
        W1, H1 = w1 * sc, h1 * sc
        W2, H2 = w2 * sc, h2b * sc
        if H1 > RY1 - RY0 - 2:
            continue
        if RX0 + 4 + W1 + 16 + W2 > RX1:
            continue
        f = (RX0 + 4, RY1 - H1, RX0 + 4 + W1, RY1)
        sd = (f[2] + 16, RY1 - H2, f[2] + 16 + W2, RY1)
        zone, isc = None, None
        for ksc in (sc, sc / 2):                      # изометрия целиком или вполовину
            Wi, Hi = wi * ksc, hi * ksc
            for zx, ztop in ((sd[2] + 16, RY1), (RX0 + 4, f[1] - 16)):
                if zx + Wi <= RX1 and ztop - Hi >= RY0:
                    zone = (zx, ztop - Hi, zx + Wi, ztop)
                    isc = ksc
                    break
            if zone:
                break
        den, s, front, side, iso_zone, iso_sc = cand, sc, f, sd, zone, isc
        break
    if den is None:                                  # запасной вариант
        den, s = 100, 0.01
        W1, H1, W2, H2 = w1 * s, h1 * s, w2 * s, h2b * s
        front = (RX0 + 4, RY1 - H1, RX0 + 4 + W1, RY1)
        side = (front[2] + 16, RY1 - H2, front[2] + 16 + W2, RY1)
        iso_zone, iso_sc = None, None
    sheet.scale_text = f"1:{den}"

    # ---- виды ----
    ox = front[0] - bb1[0] * s
    oy = front[1] - bb1[1] * s
    draw_polys(sheet, v, ox, oy, s, 'outline', 'thick')
    draw_polys(sheet, h, ox, oy, s, 'hidden', 'thin', 'hidden')
    ox2 = side[0] - bb2[0] * s
    oy2 = side[1] - bb2[1] * s
    draw_polys(sheet, v2, ox2, oy2, s, 'outline', 'thick')
    draw_polys(sheet, h2, ox2, oy2, s, 'hidden', 'thin', 'hidden')
    if iso_zone:
        oxi = iso_zone[0] - bbi[0] * iso_sc
        oyi = iso_zone[1] - bbi[1] * iso_sc
        draw_polys(sheet, iso_v, oxi, oyi, iso_sc, 'outline', 'thin')
        lbl = 'Вид изометрический'
        if iso_sc < s:
            lbl += f" (1:{int(round(1 / iso_sc))})"
        lw_ = 0.62 * 3.5 * len(lbl)
        if iso_zone[2] + 6 + lw_ <= RX1:
            sheet.text((iso_zone[2] + 6, iso_zone[1] + 4), lbl, size=3.5)
        elif iso_zone[0] - 6 - lw_ >= RX0:
            sheet.text((iso_zone[0] - 6, iso_zone[1] + 4), lbl, size=3.5, ha='right')
        elif iso_zone[1] - 5 >= RY0:
            sheet.text((iso_zone[0], iso_zone[1] - 5), lbl, size=3.5)
        else:
            sheet.text((iso_zone[0], iso_zone[3] + 5), lbl, size=3.5)

    # ---- выноски-позиции (радиально, без наложений) ----
    tx0, ty0 = ax0 + 5, ay0 + 8
    tbl_rect = (tx0 - 3, ay0 + 4, tx0 + ncols * (col_w + 6) - 9, table_top + 3)
    tt_rect = (ax1 - 194, ay0 + 76, ax1 - 4, ay0 + 123)
    tb_rect = (ax1 - 185, ay0, ax1, ay0 + 55)
    forbidden = [tbl_rect, tt_rect, tb_rect, side]
    if iso_zone:
        forbidden.append(iso_zone)
    cxv = (front[0] + front[2]) / 2
    cyv = (front[1] + front[3]) / 2
    used = []
    for (i, ch, q, c) in pos_list:
        vx, vy = view_project(c, (0, -1, 0), (0, 0, 1))
        px, py = vx * s + ox, vy * s + oy
        dx_, dy_ = px - cxv, py - cyv
        base = (math.atan2(dy_, dx_)
                if math.hypot(dx_, dy_) > 1e-6 else math.radians(45))
        ball = None
        for require_out in (True, False):     # сначала вне главного вида, потом внутри
            for rr in (9, 14, 20, 27, 35, 44, 54, 66, 80):
                for dang in (0, 12, -12, 24, -24, 38, -38, 55, -55, 75, -75):
                    a = base + math.radians(dang)
                    bx, by = px + rr * math.cos(a), py + rr * math.sin(a)
                    if not (ax0 + 6 <= bx <= ax1 - 6 and ay0 + 6 <= by <= ay1 - 6):
                        continue
                    if any(_rect_in(r, bx, by, 1.5) for r in forbidden):
                        continue
                    if any(math.hypot(bx - ux, by - uy) < 9 for ux, uy in used):
                        continue
                    if math.hypot(bx - px, by - py) < 6:
                        continue
                    if require_out and _rect_in(front, bx, by, 1):
                        continue
                    ball = (bx, by)
                    break
                if ball:
                    break
            if ball:
                break
        if not ball:
            continue
        used.append(ball)
        sheet.circle(ball, 3.2, col='dim', lw='thin')
        sheet.text(ball, str(i), size=3.2, ha='center', col='dim')
        ux, uy = px - ball[0], py - ball[1]
        d = math.hypot(ux, uy) or 1.0
        sheet.line((ball[0] + ux / d * 3.6, ball[1] + uy / d * 3.6),
                   (px, py), col='dim', lw='thin')
        sheet.circle((px, py), 0.7, col='dim', lw='thin')

    # ---- таблица состава ----
    sheet.text((tx0, table_top - 2), 'Состав сборки:', size=3.5)
    hdrs = ['Поз.', 'Обозначение', 'Наименование', 'Кол.']
    for cnum in range(ncols):
        base_x = tx0 + cnum * (col_w + 6)
        colx = [base_x, base_x + 10, base_x + 52, base_x + 122]
        for cx, htxt in zip(colx, hdrs):
            sheet.text((cx + 1, ty0 + per_col * row_h + 1.5), htxt, size=2.8)
        sheet.line((base_x, ty0 + per_col * row_h - 1),
                   (base_x + col_w, ty0 + per_col * row_h - 1),
                   col='thin', lw='thin')
        for k in range(per_col):
            idx = cnum * per_col + k
            if idx >= len(pos_list):
                break
            i, ch, q, c = pos_list[idx]
            y = ty0 + (per_col - 1 - k) * row_h
            sheet.text((colx[0] + 2, y), str(i), size=2.8)
            sheet.text((colx[1] + 1, y), _fit(ch, 40, 2.8), size=2.8)
            sheet.text((colx[2] + 1, y), _fit(D.part_name(ch), 67, 2.8), size=2.8)
            sheet.text((colx[3] + 1, y), str(q), size=2.8)
            sheet.line((base_x, y - 2.4), (base_x + col_w, y - 2.4),
                       col='thin', lw='thin')

    # ---- ТТ — справа над основной надписью ----
    yy = ay0 + 112
    sheet.text((ax1 - 190, yy), 'Технические требования:', size=3.5, col='text')
    for i, t in enumerate(TECH['assembly']):
        sheet.text((ax1 - 190, yy - 6 - i * 5), _fit(t, 186, 3.0),
                   size=3.0, col='text')
    return sheet

# ------------------------------------------------------------------ main
def main():
    parts_only = '--parts-only' in sys.argv
    assemblies_only = '--assemblies-only' in sys.argv
    st, root = load_step()
    walk_collect(st, root)
    print(f"shapes collected: {len(SHAPES)}")

    errors = []
    # ---- детали ----
    if not assemblies_only:
        parts = [n for n in sorted(D.TOTALS) if D.is_custom(n) and not D.is_purchased(n) and n not in D.TREE]
        for name in parts:
            try:
                sh = SHAPES.get(name)
                if sh is None:
                    errors.append((name, 'нет геометрии'))
                    continue
                t0 = time.time()
                sheet = make_part_drawing(name, sh)
                if sheet is None:
                    errors.append((name, 'нет геометрии'))
                    continue
                sheet.save_dxf(os.path.join(OUT_DXF, f"{name}.dxf"))
                sheet.save_pdf(os.path.join(OUT_PDF, f"{name}.pdf"))
                print(f"OK  {name}  ({time.time()-t0:.1f}s)")
            except Exception as e:
                errors.append((name, str(e)))
                print(f"ERR {name}: {e}")
                traceback.print_exc()

    # ---- сборки ---- (крупные первыми — HLR на корневой сборке требует много памяти)
    if not parts_only:
        assemblies = sorted((n for n in D.TREE if n.startswith('PSH24-') or n.startswith('PSH20-')),
                            key=lambda n: -total_instances(n))
        for name in assemblies:
            try:
                t0 = time.time()
                sheet = make_asm_drawing(st, name)
                pref = 'ASM_'
                sheet.save_dxf(os.path.join(OUT_DXF, f"{pref}{name}.dxf"))
                sheet.save_pdf(os.path.join(OUT_PDF, f"{pref}{name}.pdf"))
                print(f"OK  {pref}{name}  ({time.time()-t0:.1f}s)")
                del sheet
                import gc
                gc.collect()
            except Exception as e:
                errors.append((name, str(e)))
                print(f"ERR {name}: {e}")
                traceback.print_exc()

    print(f"done. errors: {len(errors)}")
    for n, e in errors:
        print('  ', n, '->', e)

if __name__ == '__main__':
    main()
