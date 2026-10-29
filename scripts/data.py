# -*- coding: utf-8 -*-
"""
data.py — ядро данных проекта PSH24-000.00 (бункер):
дерево сборки, количества, материалы (EN -> РФ), массы, наименования, аналоги.
"""
import json, os, math, sys
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.normpath(os.path.join(ROOT, 'data'))

with open(os.path.join(DATA, 'parts_geom.json'), encoding='utf-8') as f:
    GEOM = json.load(f)
with open(os.path.join(DATA, 'part_materials.json'), encoding='utf-8') as f:
    _m = json.load(f)
    MAT_EN = _m['material']
with open(os.path.join(DATA, 'step_tree.json'), encoding='utf-8') as f:
    _t = json.load(f)
    TREE = _t['tree']
    TOTALS = _t['totals']

DENSITY = {  # г/см3
    'S235': 7.85, 'S355': 7.85, 'S355JR': 7.85, 'S355J2G3': 7.85,
    'Steel, Mild': 7.85, 'Steel': 7.85, '.': 7.85, None: 7.85,
    'Rubber': 1.15, 'PE 1000': 0.95, 'Ertalon 6SA': 1.15,
    'Plastic': 1.20, 'Generic': 7.85,
}

MAT_RU = {
    'S235': 'Ст3сп5, ГОСТ 380-2005 (аналог S235JR)',
    'S355': 'Сталь 09Г2С, ГОСТ 19281-2014 (аналог S355JR)',
    'S355JR': 'Сталь 09Г2С, ГОСТ 19281-2014 (аналог S355JR)',
    'S355J2G3': 'Сталь 17Г1С-У, ГОСТ 5520-2014 (аналог S355J2G3)',
    'Steel, Mild': 'Ст3кп/Ст3пс, ГОСТ 380-2005',
    'Steel': 'Сталь 20, ГОСТ 1050-2013',
    '.': 'Ст3сп5, ГОСТ 380-2005 (принято по умолчанию)',
    None: 'Ст3сп5, ГОСТ 380-2005 (принято по умолчанию)',
    'Rubber': 'Резина листовая, ГОСТ 7338-90',
    'PE 1000': 'Полиэтилен высокомолекулярный ПЭ-1000 (УПЭ), ТУ 2211-032',
    'Ertalon 6SA': 'Капролон (ПА-6), ТУ 2211-032 (аналог Ertalon 6SA)',
    'Plastic': 'Пластик конструкционный (полиамид), по согласованию',
    'Generic': 'Комплектующее покупное (см. спецификацию)',
}

# ---------------- алиасы имён: дерево STEP (ID) -> геометрия XCAF ----------------
ALIAS = {
    'DIN 934 - M10': 'DIN 934 - M10 x 1,5',
    'DIN 934 - M12': 'DIN 934 - M12 x 1,75',
    'DIN 934 - M14': 'DIN 934 - M14 x 2',
    'DIN 934 - M16': 'DIN 934 - M16 x 2',
    'DIN 934 - M20': 'DIN 934 - M20 x 2,5',
    'DIN 934 - M24': 'DIN 934 - M24 x 3',
    'DIN 934 - M36': 'DIN 934 - M36 x 4',
    'zzDIN 934 - M6': 'DIN 934 - M6',
    'ISO 2341 - B - 16 x 100': 'ISO 2341 - B - 16 x 100DIN EN',
    'PSH24-000.02': 'PSH24-000.02-Variant2',
    'DIN 125 - A 17_1': 'Шайба DIN 125 - 17 - 200 HV HDG',
    '\\X2\\04280430043904310430\\X0\\ DIN 127 - 7': 'Шайба DIN 127 - 7',
}
ALIAS_INV = {v: k for k, v in ALIAS.items()}

def canonical(name):
    """XCAF-имя -> имя дерева STEP (обозначение)."""
    return ALIAS_INV.get(name, name)

def geom_of(name):
    """Геометрия по обозначению (имя дерева STEP)."""
    return GEOM.get(ALIAS.get(name, name), {})

# ---------------- имена покупных изделий / аналоги ----------------
STD = {
    'DIN 933 - M10  x 20':  ('Болт М10×20', 'ГОСТ 7798-70 (болт с шестигранной головкой, класс B)'),
    'DIN 933 - M10  x 35':  ('Болт М10×35', 'ГОСТ 7798-70'),
    'DIN 933 - M12  x 30':  ('Болт М12×30', 'ГОСТ 7798-70'),
    'DIN 933 - M12  x 45':  ('Болт М12×45', 'ГОСТ 7798-70'),
    'DIN 933 - M12  x 55':  ('Болт М12×55', 'ГОСТ 7798-70'),
    'DIN 933 - M14  x 40':  ('Болт М14×40', 'ГОСТ 7798-70'),
    'DIN 933 - M16  x 40':  ('Болт М16×40', 'ГОСТ 7798-70'),
    'DIN 933 - M6  x 20':   ('Болт М6×20', 'ГОСТ 7798-70'),
    'DIN 933 - M6  x 25':   ('Болт М6×25', 'ГОСТ 7798-70'),
    'DIN 933 - M8  x 16':   ('Болт М8×16', 'ГОСТ 7798-70'),
    'DIN 931-1 - M24 x 100':('Болт М24×100 (резьба частичная)', 'ГОСТ 7798-70'),
    'DIN 934 - M10':        ('Гайка М10', 'ГОСТ 5915-70 (допускается ГОСТ Р ИСО 4032)'),
    'DIN 934 - M12':        ('Гайка М12', 'ГОСТ 5915-70'),
    'DIN 934 - M14':        ('Гайка М14', 'ГОСТ 5915-70'),
    'DIN 934 - M16':        ('Гайка М16', 'ГОСТ 5915-70'),
    'DIN 934 - M20':        ('Гайка М20', 'ГОСТ 5915-70'),
    'DIN 934 - M24':        ('Гайка М24', 'ГОСТ 5915-70'),
    'DIN 934 - M36':        ('Гайка М36', 'ГОСТ 5915-70'),
    'zzDIN 934 - M6':       ('Гайка М6', 'ГОСТ 5915-70'),
    'DIN 125 - A 10,5':     ('Шайба плоская 10,5', 'ГОСТ 11371-78, исп. 1'),
    'DIN 125 - A 13':       ('Шайба плоская 13', 'ГОСТ 11371-78, исп. 1'),
    'DIN 125 - A 15':       ('Шайба плоская 15', 'ГОСТ 11371-78, исп. 1'),
    'DIN 125 - A 17':       ('Шайба плоская 17', 'ГОСТ 11371-78, исп. 1'),
    'DIN 125 - A 17_1':     ('Шайба плоская 17', 'ГОСТ 11371-78, исп. 1'),
    'DIN 125 - A 21':       ('Шайба плоская 21', 'ГОСТ 11371-78, исп. 1'),
    'DIN 125 - A 25':       ('Шайба плоская 25', 'ГОСТ 11371-78, исп. 1'),
    'DIN 125 - A 37':       ('Шайба плоская 37', 'ГОСТ 11371-78, исп. 1'),
    'DIN 125 - A 4,3':      ('Шайба плоская 4,3', 'ГОСТ 11371-78, исп. 1'),
    'DIN 125 - A 8,4':      ('Шайба плоская 8,4', 'ГОСТ 11371-78, исп. 1'),
    'DIN125  M6':           ('Шайба плоская 6', 'ГОСТ 11371-78, исп. 1'),
    '\\X2\\04280430043904310430\\X0\\ DIN 127 - 7': ('Шайба пружинная 7', 'ГОСТ 6402-70'),
    'DIN 929 M10':          ('Гайка приварная шестигранная М10', 'ГОСТ 14776-79, исп. 1'),
    'DIN 929 M16':          ('Гайка приварная шестигранная М16', 'ГОСТ 14776-79, исп. 1'),
    'DIN 929 M8':           ('Гайка приварная шестигранная М8', 'ГОСТ 14776-79, исп. 1'),
    'DIN 929 M6 Steel':     ('Гайка приварная шестигранная М6', 'ГОСТ 14776-79, исп. 1'),
    'DIN 94 - 3,2 x 28':    ('Шплинт 3,2×28', 'ГОСТ 397-79'),
    'DIN 94 - 4 x 28':      ('Шплинт 4×28', 'ГОСТ 397-79'),
    'DIN 1444 - 19x92':     ('Штифт с головкой 19×92', '≈ ГОСТ 3128-70, уточнить (изготовить по чертежу)'),
    'ISO 2341 - B - 16 x 100': ('Палец шарнирный 16×100 с отверстием под шплинт',
                                  'Изготовить по чертежу (ISO 2341), замена по согласованию'),
    'UCP-214':              ('Узел подшипниковый UCP-214', 'Отечественные аналоги: ВПЗ/ГПЗ UCP-214; либо SN514 + 11214 — уточнить'),
    'UCP-218':              ('Узел подшипниковый UCP-218', 'Отечественные аналоги: ВПЗ/ГПЗ UCP-218; либо SN518 + 11218 — уточнить'),
    'SKF_SYJ 70 TF':        ('Узел подшипниковый фланцевый SYJ 70 TF (⌀70)', 'Отечественные аналоги корпусных узлов ⌀70 (ВПЗ/ГПЗ) — уточнить по каталогу'),
    'SKF_SYJ 90 TF':        ('Узел подшипниковый фланцевый SYJ 90 TF (⌀90)', 'Отечественные аналоги корпусных узлов ⌀90 (ВПЗ/ГПЗ) — уточнить по каталогу'),
    '_YAR 214-2F-87.05103002214-b': ('Подшипник сферический YAR 214-2F (⌀70)', 'Аналог — подшипник с наружным кольцом сферическим (ВПЗ), уточнить'),
    '_YAR 218-2F-112.5103002218-b': ('Подшипник сферический YAR 218-2F (⌀90)', 'Аналог — подшипник с наружным кольцом сферическим (ВПЗ), уточнить'),
    '_housingSYJ 514-h':    ('Корпус подшипниковый SYJ 514', 'Аналог — корпус SN514 (ГОСТ 22673?), уточнить'),
    '_housingSYJ 518-h':    ('Корпус подшипниковый SYJ 518', 'Аналог — корпус SN518, уточнить'),
    '_1_4-28 SAE-LT':       ('Пресс-маслёнка 1/4-28 SAE-LT', 'Пресс-маслёнка АМГ/ТММ, ГОСТ 13033-80? — уточнить'),
    '_1_4-28 SAE-LT_1':     ('Пресс-маслёнка 1/4-28 SAE-LT', 'Пресс-маслёнка АМГ/ТММ — уточнить'),
    '_70-125-69.9-28-ybrg1-11417.462-97.5-b': ('Тело качения шар ⌀17,46 (шарикоподшипник 214)', 'Комплектующее подшипника'),
    '_90-160-89-36-ybrg1-12222.225-126-b': ('Тело качения шар ⌀22,23 (шарикоподшипник 218)', 'Комплектующее подшипника'),
    'INDUCTIVE SENSOR':     ('Датчик индуктивный M12 (Sn=8 мм, PNP NO)', 'Аналог отечественный — ИК-212.38.20.1 «Взлёт»; либо по параметрам'),
    'tension lock small':   ('Замок натяжной малый', 'Замок натяжной ZL-серия / отечественные аналоги — уточнить'),
    'KP plast MU':          ('Упор концевой пластиковый (KP plast MU)', 'Аналог — упор концевой пластиковый КУ, по согласованию'),
    '100_16mm_messingseibiga_Charmag': ('Шайба латунная ⌀100/16', 'Изготовить по чертежу (латунь Л63, ГОСТ 15527-2004)'),
    'Feik_M6x20-L-8':       ('Комплект крепёжный М6×20 (болт+шайбы+гайка)', 'ГОСТ 7798-70 + ГОСТ 11371-78 + ГОСТ 6402-70 + ГОСТ 5915-70'),
    'Feik_M6x25-L-10':      ('Комплект крепёжный М6×25 (болт+шайбы+гайка)', 'ГОСТ 7798-70 + ГОСТ 11371-78 + ГОСТ 6402-70 + ГОСТ 5915-70'),
    '2021_08_31__13-50-03-564.1': ('Устройство приводное (по паспорту поставщика)', 'Поставка по паспорту/сертификату — уточнить наименование'),
}

# ---------------- конструктивные наименования деталей PSH24 ----------------
def fmt_num(v, nd=1):
    s = f"{v:.{nd}f}".rstrip('0').rstrip('.')
    return s.replace('.', ',')

def sheet_thickness_est(name):
    """Оценка толщины листа: t = 2V/S (для тонкостенных деталей)."""
    g = geom_of(name)
    V = g['volume']          # мм3
    S = max(g['area'], 1.0)  # мм2
    return 2.0 * V / S

def classify_part(name):
    """Определяет тип детали по геометрии: (kind, наименование)."""
    g = geom_of(name)
    if not g or 'error' in g:
        return 'other', 'Деталь'
    dx, dy, dz = g['dx'], g['dy'], g['dz']
    dims = sorted([dx, dy, dz])
    th, mid, big = dims
    V = g['volume'] / 1000.0  # см3
    mat = MAT_EN.get(name)
    A_mm2 = g['volume'] / max(big, 1e-9)  # площадь поперечного сечения, мм2
    elong = big / max(mid, th, 1e-9)

    # --- стержни, трубы, профили (вытянутые) ---
    if elong > 3:
        t_est = sheet_thickness_est(name)
        # плоская полоса (лист/полоса) — при малой толщине относительно ширины
        if th <= 12 and th / mid <= 0.2:
            if mat == 'Rubber':
                return 'plate', f"Полоса резиновая {fmt_num(mid)}×{fmt_num(th)}, L={fmt_num(big)}"
            return 'plate', f"Полоса {fmt_num(mid)}×{fmt_num(th)}, L={fmt_num(big)}"
        # резиновые гибкие полотна/профили
        if mat == 'Rubber' and t_est <= 8 and th > 3 * t_est:
            return 'bent', f"Полотно гибкое (резина), s={fmt_num(t_est)}"
        is_round = abs(mid - th) / mid < 0.12
        perim = math.pi * mid if is_round else 2.0 * (mid + th)
        A_pred = perim * t_est
        closed = abs(A_mm2 - A_pred) <= 0.35 * max(A_pred, 1.0)
        if closed:
            if is_round:
                d = mid
                Around = math.pi / 4 * d * d
                if A_mm2 > 0.92 * Around:
                    return 'shaft', f"Стержень ⌀{fmt_num(d)}, L={fmt_num(big)}"
                s = (d - math.sqrt(max(d * d - 4 * A_mm2 / math.pi, 0.0))) / 2
                return 'tube', f"Труба ⌀{fmt_num(d)}×{fmt_num(s,1)}, L={fmt_num(big)}"
            Arect = mid * th
            if A_mm2 > 0.92 * Arect:
                return 'profile', f"Профиль сплошной {fmt_num(mid)}×{fmt_num(th)}, L={fmt_num(big)}"
            s = ((mid + th) - math.sqrt(max((mid + th) ** 2 - 4 * A_mm2, 0.0))) / 4
            return 'tube', f"Труба профильная {fmt_num(mid)}×{fmt_num(th)}×{fmt_num(s,1)}, L={fmt_num(big)}"
        # незамкнутый тонкий профиль (гнутая панель)
        if t_est <= 8 and th / mid > 0.25 and A_mm2 < 0.10 * mid * th:
            pre = 'Полотно гибкое (резина)' if mat == 'Rubber' else 'Панель гнутая'
            return 'bent', f"{pre}, s={fmt_num(t_est)}"
        if mat == 'Rubber':
            return 'profile', f"Профиль резиновый {fmt_num(mid)}×{fmt_num(th)}, L={fmt_num(big)}"
        return 'other', f"Деталь {fmt_num(big)}×{fmt_num(mid)}×{fmt_num(th)}"

    # --- листовые плоские (min = толщина, объём ~ площадь*толщина) ---
    plate_area = V / (th / 10.0)  # см2
    nominal = mid * big / 100.0
    t_est = sheet_thickness_est(name)
    if th <= 25 and 0.55 * nominal <= plate_area <= 1.05 * nominal:
        if big / mid > 4:
            if mat == 'Rubber':
                return 'plate', f"Полоса резиновая {fmt_num(mid)}×{fmt_num(th)}, L={fmt_num(big)}"
            return 'plate', f"Полоса {fmt_num(mid)}×{fmt_num(th)}, L={fmt_num(big)}"
        return 'plate', f"Пластина {fmt_num(big)}×{fmt_num(mid)}, s={fmt_num(th)}"

    # --- гнутые/формованные листовые панели (t оценивается как 2V/S) ---
    A_flat = g['volume'] / max(t_est, 0.1)          # площадь срединной поверхности
    if (t_est <= 8 and th > 3 * t_est and g['nfaces'] >= 8
            and A_flat >= 0.9 * mid * big):
        pre = 'Полотно гибкое (резина)' if mat == 'Rubber' else 'Панель гнутая'
        return 'bent', f"{pre}, s={fmt_num(t_est)}"

    if th <= 12:
        return 'plate', f"Пластина {fmt_num(big)}×{fmt_num(mid)}, s={fmt_num(th)}"
    return 'other', f"Деталь {fmt_num(big)}×{fmt_num(mid)}×{fmt_num(th)}"

ASM_NAMES = {
    'PSH24-000.00': 'Бункер (изделие PSH24-000.00)',
    'PSH24-070.00': 'Термочехол на задвижку',
    'PSH24-050.00-2': 'Задвижка шиберная (узел)',
}

def is_asm(name):
    return name in TREE

def part_name(name):
    if is_asm(name):
        return ASM_NAMES.get(name, f"Узел {name} (сборочная единица)")
    if name in STD:
        return STD[name][0]
    kind, nm = classify_part(name)
    return nm

def part_kind(name):
    if is_asm(name):
        return 'assembly'
    if name in STD:
        return 'purchased'
    return classify_part(name)[0]

def part_material_ru(name):
    en = MAT_EN.get(name)
    if is_custom(name) and en in ('Generic', '.', None, ''):
        return MAT_RU[None]
    return MAT_RU.get(en, MAT_RU[None])

def part_mass_kg(name):
    if is_asm(name):
        return sum(part_mass_kg(ch) * q for ch, q in TREE[name].items())
    g = geom_of(name)
    if 'volume' not in g:
        return 0.0
    rho = DENSITY.get(MAT_EN.get(name), 7.85)
    return g['volume'] / 1000.0 * rho / 1000.0  # см3 * г/см3 / 1000 = кг

def analog(name):
    return STD.get(name, ('', 'Изготовить по чертежу PSH24 / по конструкторской документации'))[1]

def is_purchased(name):
    return name in STD

def is_custom(name):
    return name.startswith(('PSH24-', 'PSH20-'))

# ---------------- полное дерево с количествами ----------------
def walk(node, mult=1, depth=0, out=None):
    if out is None:
        out = []
    kids = TREE.get(node, {})
    for ch, q in sorted(kids.items()):
        out.append((depth, ch, mult * q))
        if ch in TREE:
            walk(ch, mult * q, depth + 1, out)
    return out

if __name__ == '__main__':
    print('custom parts:', len([k for k in GEOM if is_custom(k)]))
    for k in sorted(GEOM):
        if is_custom(k):
            print(f"{k:<28} {part_name(k):<45} {part_material_ru(k)[:40]:<42} {part_mass_kg(k):8.3f} кг")
