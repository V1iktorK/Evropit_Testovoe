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
from views import hlr_view, bbox2d

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

# ------------------------------------------------------------------ отверстия
def hole_groups(shape):
    """Группы цилиндрических отверстий: [{d, axis, count, centers}] — по уникальным осям."""
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
                loc = cy.Location()
                pos = [loc.X(), loc.Y(), loc.Z()]
                cross = tuple(round(pos[i], 1) for i in range(3) if i != dom)
                key = (round(2 * r, 1), dom, cross)
                if key not in holes:
                    holes[key] = dict(d=round(2 * r, 1), axis=dom,
                                      center=(loc.X(), loc.Y(), loc.Z()))
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
    # изометрия — смотрим по диагонали так, чтобы длинная ось была горизонтальна
    hv, vv, dv = AXV[h_ax], AXV[v_ax], AXV[d_ax]
    iso_dir = tuple(-(0.8 * hv[i] + 1.0 * dv[i] + 0.62 * vv[i]) for i in range(3))
    iso_v, _ = hlr_view(shape, iso_dir, vv)

    gap = 18
    bb = {k: bbox2d(v) for k, (v, h) in proj.items()}
    bb['iso'] = bbox2d(iso_v)
    w_main = bb['main'][2] - bb['main'][0]
    h_main = bb['main'][3] - bb['main'][1]
    h_top = bb['top'][3] - bb['top'][1]
    w_left = bb['left'][2] - bb['left'][0]
    h_left = bb['left'][3] - bb['left'][1]
    w_iso = bb['iso'][2] - bb['iso'][0]
    h_iso = bb['iso'][3] - bb['iso'][1]
    total_w = w_main + gap + max(w_left, w_iso)
    total_h = h_main + gap + max(h_top, h_iso)

    sheet = Sheet('A3', True, designation=name, name=D.part_name(name),
                  material=D.part_material_ru(name).split(' (')[0],
                  mass=f"{D.part_mass_kg(name):.2f} кг", scale_text='')
    ax0, ay0, ax1, ay1 = sheet.frame_inner
    # поле видов: верхняя часть листа на всю ширину; нижняя часть — под ТТ
    notes_top = ay0 + 62
    aw = (ax1 - ax0) - 24
    ah = (ay1 - notes_top) - 14
    s, s_text = pick_scale(total_w, total_h, aw, ah)
    sheet.scale_text = s_text

    fmt = lambda val: f"{val:.1f}".rstrip('0').rstrip('.') if abs(val - round(val)) > 0.05 else f"{int(round(val))}"

    # размещение видов (выравнивание по верхней границе)
    top_y = ay1 - 12
    ox = ax0 + 24 - bb['main'][0] * s
    oy = top_y - bb['main'][3] * s
    main_bottom = oy + bb['main'][1] * s
    origins = {
        'main': (ox, oy),
        'top': (ox, (main_bottom - gap * s) - bb['top'][3] * s),
        'left': (ox + (w_main + gap) * s - bb['left'][0] * s, top_y - bb['left'][3] * s),
    }

    for key, da, ua in views:
        v, h = proj[key]
        tx, ty = origins[key]
        draw_polys(sheet, v, tx, ty, s, 'outline', 'thick')
        draw_polys(sheet, h, tx, ty, s, 'hidden', 'thin', 'hidden')
        proj[key] = (v, h, tx, ty, place_view(v, tx, ty, s))

    iso_x = ox + (w_main + gap) * s - bb['iso'][0] * s
    iso_y = (main_bottom - gap * s) - bb['iso'][3] * s
    draw_polys(sheet, iso_v, iso_x, iso_y, s, 'outline', 'thin')
    sheet.text((iso_x + w_iso * s + 8, iso_y + bb['iso'][1] * s + 4), 'Вид изометрический',
               size=3.5, col='text')

    # ---- размеры (значения в мм модели) ----
    v, h, tx, ty, (x0, y0, x1, y1) = proj['main']
    sheet.dim_linear((x0, y0), (x1, y0), -10, text=fmt(axes[h_ax]))
    sheet.dim_linear((x0, y0), (x0, y1), -10, text=fmt(axes[v_ax]))
    v2, h2, tx2, ty2, (a0, b0, a1, b1) = proj['top']
    sheet.dim_linear((a1, b0), (a1, b1), 10, text=fmt(axes[d_ax]))
    v3, h3, tx3, ty3, (c0, d0, c1, d1) = proj['left']
    sheet.dim_linear((c0, d0), (c1, d0), -10, text=fmt(axes[d_ax]))

    # ---- отверстия ----
    holes = [hg for hg in hole_groups(shape) if hg['axis'] == AXI[d_ax]]
    note = []
    for hg in sorted(holes, key=lambda hg: -hg['d']):
        note.append(f"Ø{hg['d']:g} — {hg['count']} шт.")
    if holes:
        big_hole = max(holes, key=lambda hg: hg['d'])
        c = big_hole['centers'][0]
        vx = c[AXI[h_ax]]
        vy = c[AXI[v_ax]]
        px = vx * s + tx
        py = vy * s + ty
        sheet.dim_diameter((px, py), big_hole['d'] / 2 * s, 55,
                           text=f"{big_hole['count']}×Ø{big_hole['d']:g}" if big_hole['count'] > 1
                           else f"Ø{big_hole['d']:g}")
        sheet.text((ax0 + 5, ay0 + 68), 'Отверстия: ' + '; '.join(note[:8]), size=3.2, col='note')

    # ---- технические требования ----
    yy = ay0 + 58
    sheet.text((ax0 + 5, yy), 'Технические требования:', size=3.5, col='text')
    for i, t in enumerate(TECH.get(kind, TECH['other'])):
        sheet.text((ax0 + 5, yy - 6 - i * 5), t, size=3.0, col='text')
    return sheet

# ------------------------------------------------------------------ сборочный чертёж
def make_asm_drawing(st, name):
    shape = SHAPES[name]
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

    row_h = 5.0
    n = max(len(pos_list), 1)
    ncols = 2 if n > 28 else 1
    per_col = (n + ncols - 1) // ncols
    table_h = per_col * row_h + 16

    v, h = hlr_view(shape, (0, -1, 0), (0, 0, 1))
    v2, h2 = hlr_view(shape, (1, 0, 0), (0, 0, 1))
    hv, vv, dv = (1, 0, 0), (0, 1, 0), (0, 0, 1)
    iso_dir = tuple(-(0.8 * hv[i] + 1.0 * dv[i] + 0.62 * vv[i]) for i in range(3))
    iso_v, _ = hlr_view(shape, iso_dir, vv)
    bb1, bb2, bbi = bbox2d(v), bbox2d(v2), bbox2d(iso_v)
    gap = 20
    w1, h1 = bb1[2] - bb1[0], bb1[3] - bb1[1]
    w2, h2b = bb2[2] - bb2[0], bb2[3] - bb2[1]
    wi, hi = bbi[2] - bbi[0], bbi[3] - bbi[1]
    total_w = w1 + gap + max(w2, wi)
    total_h = h1 + gap + max(h2b, hi)

    aw = (ax1 - ax0) - 24
    ah = (ay1 - ay0) - table_h - 24
    s, s_text = pick_scale(total_w, total_h, aw, ah)
    sheet.scale_text = s_text
    ox = ax0 + 24 - bb1[0] * s
    top_y = ay1 - 12
    oy1 = top_y - bb1[3] * s
    draw_polys(sheet, v, ox, oy1, s, 'outline', 'thick')
    draw_polys(sheet, h, ox, oy1, s, 'hidden', 'thin', 'hidden')
    ox2 = ox + (w1 + gap) * s - bb2[0] * s
    oy2 = top_y - bb2[3] * s
    draw_polys(sheet, v2, ox2, oy2, s, 'outline', 'thick')
    draw_polys(sheet, h2, ox2, oy2, s, 'hidden', 'thin', 'hidden')
    main_bottom = oy1 + bb1[1] * s
    oxi = ox + (w1 + gap) * s - bbi[0] * s
    oyi = (main_bottom - gap * s) - bbi[3] * s
    draw_polys(sheet, iso_v, oxi, oyi, s, 'outline', 'thin')

    # позиции на главном виде — радиально от центра вида, со сдвигом
    cx_view, cy_view = (bb1[0] + bb1[2]) / 2 * s + ox, (bb1[1] + bb1[3]) / 2 * s + oy1
    for k, (i, ch, q, c) in enumerate(pos_list):
        vx, vy = c[0], c[2]   # главный вид: dir=y -> координаты (x, z)
        px, py = vx * s + ox, vy * s + oy1
        dx_, dy_ = px - cx_view, py - cy_view
        L = math.hypot(dx_, dy_) or 1.0
        rr = 16 + (k % 3) * 7
        bx, by = px + dx_ / L * rr, py + dy_ / L * rr
        sheet.circle((bx, by), 3.2, col='dim', lw='thin')
        sheet.text((bx, by), str(i), size=3.2, ha='center', col='dim')
        sheet.line((bx + (px - bx) * 0.22, by + (py - by) * 0.22), (px, py), col='dim', lw='thin')

    # таблица состава — слева внизу (1-2 колонки)
    tx0, ty0 = ax0 + 5, ay0 + 8
    ncols = 2 if n > 28 else 1
    per_col = (n + ncols - 1) // ncols
    col_w = 132
    sheet.text((tx0, ty0 + per_col * row_h + 6), 'Состав сборки:', size=3.5)
    hdrs = ['Поз', 'Обозначение', 'Наименование', 'Кол.']
    for cnum in range(ncols):
        base_x = tx0 + cnum * (col_w + 6)
        colx = [base_x, base_x + 10, base_x + 52, base_x + 122]
        for cx, htxt in zip(colx, hdrs):
            sheet.text((cx + 1, ty0 + per_col * row_h + 1.5), htxt, size=2.8)
        sheet.line((base_x, ty0 + per_col * row_h - 1), (base_x + col_w, ty0 + per_col * row_h - 1),
                   col='thin', lw='thin')
        for k in range(per_col):
            idx = cnum * per_col + k
            if idx >= len(pos_list):
                break
            i, ch, q, c = pos_list[idx]
            y = ty0 + (per_col - 1 - k) * row_h
            sheet.text((colx[0] + 2, y), str(i), size=2.8)
            sheet.text((colx[1] + 1, y), ch, size=2.8)
            sheet.text((colx[2] + 1, y), D.part_name(ch)[:38], size=2.8)
            sheet.text((colx[3] + 1, y), str(q), size=2.8)
            sheet.line((base_x, y - 2.4), (base_x + col_w, y - 2.4), col='thin', lw='thin')

    # ТТ — справа над основной надписью
    yy = ay0 + 92
    sheet.text((ax1 - 185, yy), 'Технические требования:', size=3.5, col='text')
    for i, t in enumerate(TECH['assembly']):
        sheet.text((ax1 - 185, yy - 6 - i * 5), t, size=3.0, col='text')
    return sheet

# ------------------------------------------------------------------ main
def main():
    st, root = load_step()
    walk_collect(st, root)
    print(f"shapes collected: {len(SHAPES)}")

    errors = []
    # ---- детали ----
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

    # ---- сборки ----
    assemblies = [n for n in D.TREE if n.startswith('PSH24-') or n.startswith('PSH20-')]
    for name in assemblies:
        try:
            t0 = time.time()
            sheet = make_asm_drawing(st, name)
            pref = 'ASM_'
            sheet.save_dxf(os.path.join(OUT_DXF, f"{pref}{name}.dxf"))
            sheet.save_pdf(os.path.join(OUT_PDF, f"{pref}{name}.pdf"))
            print(f"OK  {pref}{name}  ({time.time()-t0:.1f}s)")
        except Exception as e:
            errors.append((name, str(e)))
            print(f"ERR {name}: {e}")
            traceback.print_exc()

    print(f"done. errors: {len(errors)}")
    for n, e in errors:
        print('  ', n, '->', e)

if __name__ == '__main__':
    main()
