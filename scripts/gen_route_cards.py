# -*- coding: utf-8 -*-
"""
gen_route_cards.py — маршрутные карты (ЕСТД, форма по ГОСТ 3.1102-82):
 - МК на каждую изготавливаемую деталь (по типу заготовки/операциям);
 - МК на сборку/сварку узлов и изделия;
 - сводный перечень маршрутных карт.
"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

OUT = os.path.join(D.ROOT, '04_Маршрутные_карты')
OUT_D = os.path.join(OUT, 'Детали')
OUT_A = os.path.join(OUT, 'Сборка')
os.makedirs(OUT_D, exist_ok=True)
os.makedirs(OUT_A, exist_ok=True)

thin = Side(style='thin')
BD = Border(left=thin, right=thin, top=thin, bottom=thin)
HDR_FILL = PatternFill('solid', fgColor='D9E1F2')
BOLD = Font(bold=True, size=10)
NORM = Font(size=10)
CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)
WRAP = Alignment(wrap_text=True, vertical='top')

EQUIP = {
    'laser': 'Станок лазерной резки (LVD Phoenix 3015 / LS-3015), 3 кВт',
    'plasma': 'Станок плазменной резки (Kjellberg HiFocus 360i)',
    'saw': 'Ленточнопильный станок (Pilous ARG 300 / Контур-302)',
    'bend': 'Листогибочный пресс (Gasparini PBS 135/3100, ЧПУ)',
    'lathe': 'Токарно-винторезный станок 16К20 / Doosan Puma 2600',
    'mill': 'Фрезерный обрабатывающий центр (Haas VF-2 / 6Р13)',
    'drill': 'Сверлильный станок 2Н135 / сверлильно-расточной 2А135',
    'grind': 'Заточной станок 3Б651 / зачистка УШМ',
    'weld': 'Полуавтомат сварочный ПДГ-500 (МИГ/МАГ), ГОСТ 14771-2005',
    'weld_tig': 'Аппарат аргонодуговой сварки TIG (EWM Phoenix 355)',
    'blast': 'Дробеструйная камера (Shot blasting), Sa 2½ по ГОСТ 9.402',
    'paint': 'Красильная камера, безвоздушное распыление',
    'otk': 'Участок ОТК: плиты поверочные, кронциркуль, УЗК-дефектоскоп',
    'assembly': 'Сборочный стенд (сварочный манипулятор), тали 2 т',
}

def norm_time(base, factor=1.0):
    return round(base * factor, 2)

def part_operations(name):
    kind = D.part_kind(name)
    g = D.geom_of(name)
    dims = sorted([g['dx'], g['dy'], g['dz']])
    th, mid, big = dims
    perim = 2 * (mid + big)          # оценка длины контура, мм
    ops = []
    if kind == 'plate':
        t_cut = norm_time(0.15 + perim / 40000.0)
        ops.append(['10', 'Заготовительная', 'Раскрой листа лазерной резкой по контуру DXF (1:1)',
                    EQUIP['laser'], 'Стол раскройный, лист s=%.1f' % th,
                    'Допуск реза ±0,5 мм; шероховатость кромки Ra 25 (ISO 9013-I)',
                    t_cut, 'Визуальный, замер габаритов'])
        ops.append(['20', 'Слесарная', 'Снятие заусенцев, зачистка кромок, притупление острых кромок',
                    EQUIP['grind'], 'УШМ, щётки абразивные', 'Заусенцы — по ГОСТ 14637-89, кромки R0,5',
                    norm_time(0.05 + perim / 200000.0), 'Визуальный'])
    elif kind == 'bent':
        t_est = D.sheet_thickness_est(name)
        ops.append(['10', 'Заготовительная', 'Раскрой листа s=%.1f по DXF (заготовка с припуском на гибы)' % t_est,
                    EQUIP['laser'], 'Стол раскройный', 'Допуск реза ±0,5 мм',
                    norm_time(0.2 + perim / 35000.0), 'Визуальный, замер'])
        ops.append(['20', 'Гибочная', 'Гибка на листогибочном прессе по чертежу (линии гиба — по разметке/чертилке)',
                    EQUIP['bend'], 'Пуансоны/матрицы по углу гиба, упоры',
                    'Угол по чертежу ±0,5°; радиус гиба по чертежу; контролировать прогиб',
                    norm_time(0.25 + perim / 120000.0), 'Угольник, шаблон'])
        ops.append(['30', 'Слесарная', 'Снятие заусенцев, правка, зачистка',
                    EQUIP['grind'], 'УШМ', 'Недопустимы трещины на линии гиба', 0.08, 'Визуальный'])
    elif kind in ('tube', 'profile'):
        ops.append(['10', 'Заготовительная', 'Распиловка профиля в размер L=%.0f мм' % big,
                    EQUIP['saw'], 'Упоры, кондуктор', 'Отклонение длины ±1 мм, торец перпендикулярен ±0,5 мм',
                    norm_time(0.08 + big / 30000.0), 'Контрольный замер'])
        ops.append(['20', 'Слесарная', 'Снятие фасок 1×45°, зачистка торцов, разметка отверстий (при наличии)',
                    EQUIP['drill'], 'Свёрла, кондуктор', 'Фаски по чертежу', 0.1, 'Визуальный'])
    elif kind == 'shaft':
        ops.append(['10', 'Заготовительная', 'Распиловка прутка Ø%.0f в размер L=%.0f' % (mid, big),
                    EQUIP['saw'], 'Упоры', 'Припуск на обработку 3 мм на сторону', 0.1, 'Замер'])
        ops.append(['20', 'Токарная', 'Обточка по чертежу, снятие фасок',
                    EQUIP['lathe'], 'Цанги/патрон, резцы', 'Допуски по ГОСТ 25058-2016; Ra 3,2',
                    norm_time(0.25 + big / 15000.0), 'Кронциркуль, микрометр'])
        ops.append(['30', 'Слесарная', 'Зачистка, притупление кромок', EQUIP['grind'], 'УШМ', 'Кромки R0,5', 0.05, 'Визуальный'])
    else:
        ops.append(['10', 'Заготовительная', 'Заготовка по чертежу (резка/литая/сварная заготовка), комплектование',
                    EQUIP['saw'] + ' / участок заготовок', 'По технологу', 'Припуск на механическую обработку по технологу',
                    norm_time(0.2 + big / 25000.0), 'Входной контроль'])
        ops.append(['20', 'Механическая', 'Механическая обработка по чертежу (токарно-фрезерная)',
                    EQUIP['lathe'] + ' / ' + EQUIP['mill'], 'Универсальная оснастка',
                    'Допуски по ГОСТ 25058-2016; Ra 6,3..12,5', norm_time(0.6 + big / 12000.0), 'Контроль по чертежу'])
        ops.append(['30', 'Слесарная', 'Снятие заусенцев, зачистка', EQUIP['grind'], 'УШМ', 'Кромки R0,5', 0.08, 'Визуальный'])
    ops.append(['90', 'Контрольная', 'Окончательный контроль по чертежу, маркировка',
                EQUIP['otk'], 'СИК, штампы маркировочные', 'Маркировка обозначения по ГОСТ 2.316-2008',
                0.06, 'ОТК'])
    return ops

def assembly_operations(name, is_root=False):
    kids = D.TREE.get(name, {})
    n_weld_est = sum(1 for ch in kids if D.is_custom(ch))
    ops = [
        ['10', 'Комплектовочная', 'Комплектование деталей и покупных изделий по спецификации',
         'Участок комплектации', 'Стеллажи, тара', 'Проверить маркировку деталей, наличие сертификатов на покупные',
         norm_time(0.2 + 0.03 * len(kids)), 'Визуальный'],
        ['20', 'Сборочно-сварочная', 'Сборка узла по сборочному чертежу, прихватка и сварка швов',
         EQUIP['weld'], 'Сборочный стенд, кондукторы, струбцины',
         'Швы — по ГОСТ 14771-2005 / ГОСТ 5264-80; зазоры ≤1 мм; не сваривать без прихватки',
         norm_time(0.8 + 0.25 * n_weld_est), 'Визуальный по ГОСТ 3242-79'],
        ['30', 'Слесарная', 'Зачистка сварных швов, правка, доводка стыков',
         EQUIP['grind'], 'УШМ, абразивные круги', 'Шов ровный, без подрезов и сварных брызг',
         norm_time(0.3 + 0.05 * n_weld_est), 'Визуальный'],
        ['40', 'Покрасочная', 'Подготовка поверхности (дробеструй), грунтовка, окраска в 2 слоя',
         EQUIP['blast'] + ' / ' + EQUIP['paint'], 'Краскопульт, камера',
         'Подготовка — Sa 2½ (ГОСТ 9.402-2004); покрытие — по ГОСТ 9.401-91, толщина 80..120 мкм',
         norm_time(0.6 + 0.02 * (n_weld_est + 3)), 'Визуальный, толщиномер'],
    ]
    if is_root:
        ops.insert(4, ['50', 'Сборочная', 'Монтаж узлов и механизмов изделия, установка подшипниковых узлов и крепежа',
                       EQUIP['assembly'], 'Тали, динамометрический ключ',
                       'Моменты затяжки — по ГОСТ Р ИСО 898-1; смазка ЛИТОЛ-24 (ГОСТ 21150-2018)',
                       2.5, 'Визуальный, протокол затяжки'])
        ops.append(['90', 'Контрольная', 'Приёмочный контроль изделия, испытание на работоспособность, консервация',
                    EQUIP['otk'], 'СИК', 'Акт приёмо-сдаточных испытаний; консервация по ГОСТ 9.010-80',
                    1.2, 'ОТК, комиссия'])
    else:
        ops.append(['90', 'Контрольная', 'Окончательный контроль узла по чертежу, маркировка',
                    EQUIP['otk'], 'СИК', 'Маркировка по ГОСТ 2.316-2008', 0.12, 'ОТК'])
    return ops

def write_mk(path, designation, name, material, mass, qty, ops, note='Нормы времени — расчётные, уточняются по нормативам предприятия.'):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Маршрутная карта'
    # шапка
    ws.merge_cells('A1:H1')
    c = ws.cell(1, 1, f"МАРШУТНАЯ КАРТА  {designation}")
    c.font = Font(bold=True, size=14)
    c.alignment = Alignment(horizontal='center')
    ws.merge_cells('A2:H2')
    ws.cell(2, 1, name).font = Font(bold=True, size=12)
    ws.cell(2, 1).alignment = Alignment(horizontal='center')
    meta = [('Обозначение', designation), ('Наименование', name),
            ('Материал', material), ('Масса ед., кг', round(mass, 2)),
            ('Количество', qty), ('Документ', f"Чертёж {designation}")]
    for i, (k, v) in enumerate(meta):
        col = 1 + (i % 3) * 2 + 1
        ws.cell(3 + i // 3, col - 1, k).font = BOLD
        ws.cell(3 + i // 3, col, v).font = NORM
    hdr_row = 6
    hdrs = ['№ оп.', 'Наименование операции', 'Содержание работ', 'Оборудование',
            'Оснастка, инструмент', 'Технологические требования', 'Норма времени, ч', 'Контроль']
    widths = [7, 18, 44, 32, 28, 42, 10, 22]
    for i, (h, w) in enumerate(zip(hdrs, widths), 1):
        c = ws.cell(hdr_row, i, h)
        c.font = BOLD; c.fill = HDR_FILL; c.border = BD; c.alignment = CENTER
        ws.column_dimensions[get_column_letter(i)].width = w
    r = hdr_row + 1
    total = 0.0
    for op in ops:
        for i, v in enumerate(op, 1):
            c = ws.cell(r, i, v)
            c.font = NORM; c.border = BD
            c.alignment = CENTER if i in (1, 7) else WRAP
        total += float(op[6])
        r += 1
    ws.cell(r, 6, 'Итого норма времени на изделие (деталь), ч:').font = BOLD
    ws.cell(r, 7, round(total, 2)).font = BOLD
    ws.cell(r + 2, 1, note).font = Font(size=9, italic=True)
    ws.cell(r + 3, 1, 'Разраб.: отдел технической подготовки производства (ОТПП)').font = Font(size=9)
    wb.save(path)

def main():
    index = []
    # ---- детали ----
    for name in sorted(D.TOTALS):
        if not D.is_custom(name) or D.is_purchased(name) or name in D.TREE:
            continue
        ops = part_operations(name)
        mass = D.part_mass_kg(name)
        qty = D.TOTALS[name]
        fn = f"МК_{name}.xlsx"
        write_mk(os.path.join(OUT_D, fn), name, D.part_name(name),
                 D.part_material_ru(name), mass, qty, ops)
        total = sum(float(o[6]) for o in ops)
        index.append(['Деталь', name, D.part_name(name), qty, round(total, 2), fn])
    # ---- сборки ----
    for name in sorted(D.TREE):
        if not name.startswith(('PSH24-', 'PSH20-')):
            continue
        is_root = (name == 'PSH24-000.00')
        ops = assembly_operations(name, is_root)
        mass = D.part_mass_kg(name)
        qty = 1
        fn = f"МК_СБ_{name}.xlsx"
        write_mk(os.path.join(OUT_A, fn), name, D.part_name(name),
                 'Сборка сварная (Ст3сп5/09Г2С)', mass, qty, ops)
        total = sum(float(o[6]) for o in ops)
        index.append(['Сборка', name, D.part_name(name), qty, round(total, 2), fn])

    # ---- перечень ----
    wb = Workbook()
    ws = wb.active
    ws.title = 'Перечень МК'
    hdrs = ['№', 'Вид', 'Обозначение', 'Наименование', 'Кол.', 'Норма времени, ч', 'Файл']
    widths = [5, 10, 26, 42, 6, 16, 34]
    for i, (h, w) in enumerate(zip(hdrs, widths), 1):
        c = ws.cell(1, i, h)
        c.font = BOLD; c.fill = HDR_FILL; c.border = BD; c.alignment = CENTER
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = 'A2'
    for r, row in enumerate(index, 2):
        for i, v in enumerate([r - 1] + row, 1):
            c = ws.cell(r, i, v)
            c.font = NORM; c.border = BD
            c.alignment = WRAP
    ws.cell(len(index) + 2, 6, round(sum(x[4] for x in index), 1)).font = BOLD
    ws.cell(len(index) + 2, 4, 'ИТОГО нормо-часов:').font = BOLD
    wb.save(os.path.join(OUT, 'Перечень_маршрутных_карт.xlsx'))
    print('МК деталей:', len([x for x in index if x[0] == 'Деталь']))
    print('МК сборок:', len([x for x in index if x[0] == 'Сборка']))
    print('saved', OUT)

if __name__ == '__main__':
    main()
