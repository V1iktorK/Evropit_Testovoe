# -*- coding: utf-8 -*-
"""
sheetlib.py — генерация чертёжных листов ЕСКД (ГОСТ 2.104).
Единая модель листа -> экспорт в DXF (ezdxf) и PDF (matplotlib).
Единицы измерения: мм. Лист задаётся форматом (A4..A0), альбомная/книжная.
"""
import math
import ezdxf
from ezdxf.enums import TextEntityAlignment

FORMATS = {
    'A0': (1189, 841),
    'A1': (841, 594),
    'A2': (594, 420),
    'A3': (420, 297),
    'A4': (297, 210),
}

LW = {'thick': 0.7, 'thin': 0.35, 'extra': 1.0, 'hair': 0.25}
COL = {'frame': 7, 'outline': 1, 'dim': 2, 'text': 3, 'center': 4, 'hidden': 5,
       'note': 6, 'thin': 8}


class Sheet:
    """Чертёжный лист: рамка, основная надпись, графика, размеры, текст."""

    def __init__(self, fmt='A3', landscape=True, designation='', name='',
                 material='', mass='', scale_text='1:1', sheet_no=1, sheets=1,
                 org='ООО «Европит», г. Москва', extra_fields=None):
        w, h = FORMATS[fmt]
        if not landscape:
            w, h = h, w
        self.w, self.h = w, h
        self.fmt = fmt
        self.designation = designation
        self.name = name
        self.material = material
        self.mass = mass
        self.scale_text = scale_text
        self.sheet_no = sheet_no
        self.sheets = sheets
        self.org = org
        self.extra_fields = extra_fields or {}
        self.ents = []
        self._tb_drawn = False
        # границы поля чертежа (внутренняя рамка)
        self.margins = (20, 5, 5, 5)  # левое, нижнее, правое, верхнее
        self._draw_frame()

    def finalize(self):
        """Прорисовка основной надписи (вызывается перед сохранением,
        чтобы подхватить актуальные поля, например масштаб)."""
        if not self._tb_drawn:
            self._tb_drawn = True
            x0, y0, x1, y1 = self.frame_inner
            self._draw_title_block(x1 - 185, y0)

    # ------------------------------------------------------------- geometry
    def add(self, kind, **kw):
        self.ents.append((kind, kw))

    def line(self, p1, p2, col='outline', lw='thick', dash=None):
        self.add('line', p1=p1, p2=p2, col=col, lw=lw, dash=dash)

    def circle(self, c, r, col='outline', lw='thick'):
        self.add('circle', c=c, r=r, col=col, lw=lw)

    def arc(self, c, r, a1, a2, col='outline', lw='thick'):
        self.add('arc', c=c, r=r, a1=a1, a2=a2, col=col, lw=lw)

    def poly(self, pts, col='outline', lw='thick', close=False):
        self.add('poly', pts=pts, col=col, lw=lw, close=close)

    def text(self, pos, s, size=3.5, ha='left', va='center', col='text', angle=0):
        self.add('text', pos=pos, s=s, size=size, ha=ha, va=va, col=col, angle=angle)

    # ------------------------------------------------------------- dims
    def _arrow(self, p, direction, size=2.5, col='dim'):
        # стрелка: треугольник в точке p, direction - единичный вектор от оси
        d = direction
        n = (-d[1], d[0])
        tip = p
        b1 = (p[0] - d[0] * size + n[0] * size * 0.25,
              p[1] - d[1] * size + n[1] * size * 0.25)
        b2 = (p[0] - d[0] * size - n[0] * size * 0.25,
              p[1] - d[1] * size - n[1] * size * 0.25)
        self.poly([tip, b1, b2], col=col, lw='thin', close=True)

    def dim_linear(self, p1, p2, off, text=None, text_size=3.5, col='dim',
                   ext=2.0, side=None, prefix=''):
        """
        Линейный размер. off - отступ размерной линии от измеряемой точки
        (положительный - в сторону нормали). side - ('left'|'right'|'top'|'bottom')
        влияет на поворот текста.
        """
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        L = math.hypot(dx, dy)
        if L < 1e-9:
            return
        ux, uy = dx / L, dy / L
        nx, ny = -uy, ux
        if off < 0:
            nx, ny = -nx, -ny
            off = -off
        q1 = (p1[0] + nx * off, p1[1] + ny * off)
        q2 = (p2[0] + nx * off, p2[1] + ny * off)
        # выносные линии
        e1 = (p1[0] + nx * (off + ext), p1[1] + ny * (off + ext))
        e2 = (p2[0] + nx * (off + ext), p2[1] + ny * (off + ext))
        self.line((p1[0] + nx * 1, p1[1] + ny * 1), e1, col=col, lw='thin')
        self.line((p2[0] + nx * 1, p2[1] + ny * 1), e2, col=col, lw='thin')
        self.line(q1, q2, col=col, lw='thin')
        self._arrow(q1, (-ux, -uy), col=col)
        self._arrow(q2, (ux, uy), col=col)
        if text is None:
            text = f"{L:.1f}".rstrip('0').rstrip('.') if L != int(round(L)) else f"{int(round(L))}"
        text = prefix + text
        mid = ((q1[0] + q2[0]) / 2, (q1[1] + q2[1]) / 2)
        angle = math.degrees(math.atan2(uy, ux))
        if angle > 90:
            angle -= 180
        elif angle < -90:
            angle += 180
        # текст над размерной линией
        tx = mid[0] + nx * 2.0
        ty = mid[1] + ny * 2.0
        self.text((tx, ty), text, size=text_size, ha='center', va='center',
                  col=col, angle=angle)

    def dim_diameter(self, center, r, ang_deg, text=None, text_size=3.5,
                     leader=12, col='dim', inside=False):
        """Размер диаметра с полкой-выноской."""
        a = math.radians(ang_deg)
        p_on = (center[0] + r * math.cos(a), center[1] + r * math.sin(a))
        p_out = (center[0] + (r + leader) * math.cos(a),
                 center[1] + (r + leader) * math.sin(a))
        shelf = 5
        p_sh = (p_out[0] + shelf, p_out[1])
        self.line(p_on, p_out, col=col, lw='thin')
        self.line(p_out, p_sh, col=col, lw='thin')
        if text is None:
            d = 2 * r
            ds = f"{d:.1f}".rstrip('0').rstrip('.') if d != int(round(d)) else f"{int(round(d))}"
            text = f"⌀{ds}"
        self.text((p_out[0] + 1, p_out[1] + 1.8), text, size=text_size,
                  ha='left', va='center', col=col)
        if not inside:
            self._arrow(p_on, (math.cos(a), math.sin(a)), col=col)

    # ------------------------------------------------------------- frame
    def _draw_frame(self):
        ml, mb, mr, mt = self.margins
        x0, y0 = ml, mb
        x1, y1 = self.w - mr, self.h - mt
        self.frame_inner = (x0, y0, x1, y1)
        # внешняя рамка листа
        self.add('rect', p1=(0, 0), p2=(self.w, self.h), col='frame', lw='hair')
        # внутренняя рамка
        self.add('rect', p1=(x0, y0), p2=(x1, y1), col='frame', lw='thick')

    def _draw_title_block(self, bx, by):
        """Основная надпись (упрощённая форма 1, ГОСТ 2.104). 185x55."""
        self.tb_origin = (bx, by)
        X = lambda v: bx + v
        Y = lambda v: by + v
        # границы
        self.add('rect', p1=(bx, by), p2=(bx + 185, by + 55), col='frame', lw='thick')

        def cell(x, y, w, h):
            self.add('rect', p1=(X(x), Y(y)), p2=(X(x + w), Y(y + h)),
                     col='frame', lw='thin')

        # левый блок: изменения
        rows6 = [25, 30, 35, 40, 45, 50]
        for yy in rows6:
            self.line((X(0), Y(yy)), (X(48), Y(yy)), col='frame', lw='thin')
        for xx in (7, 14, 34, 41):
            self.line((X(xx), Y(25)), (X(xx), Y(55)), col='frame', lw='thin')
        # организация
        cell(0, 0, 48, 25)
        # подписи
        rows5 = [5, 10, 15, 20]
        for yy in rows5:
            self.line((X(48), Y(yy)), (X(125), Y(yy)), col='frame', lw='thin')
        for xx in (70, 97, 111):
            self.line((X(xx), Y(0)), (X(xx), Y(25)), col='frame', lw='thin')
        # правый нижний: лист/листов
        cell(125, 0, 30, 12)
        cell(155, 0, 30, 12)
        self.line((X(125), Y(12)), (X(185), Y(12)), col='frame', lw='thin')
        # материал / лит / масса / масштаб строка
        self.line((X(48), Y(25)), (X(185), Y(25)), col='frame', lw='thin')
        self.line((X(48), Y(35)), (X(185), Y(35)), col='frame', lw='thin')
        self.line((X(48), Y(45)), (X(185), Y(45)), col='frame', lw='thin')
        for xx in (125, 140, 163):
            self.line((X(xx), Y(25)), (X(xx), Y(35)), col='frame', lw='thin')

        # ---- текст ----
        T = self.text
        # обозначение
        T((X(52), Y(50)), self.designation, size=5, ha='left', col='text')
        # наименование
        T((X(52), Y(40)), self.name, size=5, ha='left', col='text')
        # материал
        T((X(50), Y(33.2)), 'Материал', size=2.1, ha='left', col='text')
        T((X(50), Y(28)), self.material, size=3.2, ha='left', col='text')
        # лит/масса/масштаб
        T((X(126), Y(33.2)), 'Лит.', size=2.1, ha='left', col='text')
        T((X(126), Y(28)), self.extra_fields.get('lit', ''), size=3.2, ha='left', col='text')
        T((X(141), Y(33.2)), 'Масса', size=2.1, ha='left', col='text')
        T((X(141), Y(28)), self.mass, size=3.2, ha='left', col='text')
        T((X(164), Y(33.2)), 'Масштаб', size=2.1, ha='left', col='text')
        T((X(164), Y(28)), self.scale_text, size=3.2, ha='left', col='text')
        # подписи (Разраб. — сверху, Утв. — снизу)
        sign_rows = ['Разраб.', 'Пров.', 'Т. контр.', 'Н. контр.', 'Утв.']
        for i, s in enumerate(sign_rows):
            T((X(49.5), Y(22.5 - 5 * i)), s, size=2.5, ha='left', col='text')
        # организация
        T((X(2), Y(15)), self.org.split(',')[0], size=4, ha='left', col='text')
        rest = ','.join(self.org.split(',')[1:]).strip()
        if rest:
            T((X(2), Y(9)), rest, size=2.5, ha='left', col='text')
        T((X(2), Y(4)), 'Разраб. — отдел КД', size=2.5, ha='left', col='text')
        # изменения
        for i, s in enumerate(['Изм.', 'Лист', '№ докум.', 'Подп.', 'Дата']):
            xs = [1, 8, 15, 35, 42][i]
            T((X(xs), Y(52.5)), s, size=2.1, ha='left', col='text')
        T((X(1), Y(47.5)), '01', size=2.5, ha='left', col='text')
        T((X(15), Y(47.5)), 'Первый выпуск', size=2.5, ha='left', col='text')
        # лист/листов
        T((X(127), Y(6)), 'Лист', size=2.5, ha='left', col='text')
        T((X(127), Y(2)), str(self.sheet_no), size=3.2, ha='left', col='text')
        T((X(157), Y(6)), 'Листов', size=2.5, ha='left', col='text')
        T((X(157), Y(2)), str(self.sheets), size=3.2, ha='left', col='text')

    def drawing_area(self):
        """Поле чертежа без основной надписи (x0,y0,x1,y1)."""
        x0, y0, x1, y1 = self.frame_inner
        return (x0, y0, x1 - 185 - 5, y1)

    # ------------------------------------------------------------- export
    def save_dxf(self, path):
        self.finalize()
        doc = ezdxf.new('R2018', setup=True)
        doc.header['$INSUNITS'] = 4  # mm
        msp = doc.modelspace()
        # стиль текста с поддержкой кириллицы
        if 'GOST' not in doc.styles:
            doc.styles.add('GOST', font='Arial')
        for kind, kw in self.ents:
            col = COL.get(kw.get('col', 'outline'), 7)
            lw = LW.get(kw.get('lw', 'thick'), 0.7)
            dash = kw.get('dash')
            attrs = dict(color=col, lineweight=int(lw * 100))
            if dash == 'center':
                attrs['linetype'] = 'CENTER'
            elif dash == 'hidden':
                attrs['linetype'] = 'DASHED'
            if kind == 'line':
                msp.add_line(kw['p1'], kw['p2'], dxfattribs=attrs)
            elif kind == 'rect':
                p1, p2 = kw['p1'], kw['p2']
                pts = [(p1[0], p1[1]), (p2[0], p1[1]), (p2[0], p2[1]), (p1[0], p2[1])]
                msp.add_lwpolyline(pts, close=True, dxfattribs=attrs)
            elif kind == 'poly':
                pts = [(p[0], p[1]) for p in kw['pts']]
                msp.add_lwpolyline(pts, close=kw.get('close', False), dxfattribs=attrs)
            elif kind == 'circle':
                msp.add_circle(kw['c'], kw['r'], dxfattribs=attrs)
            elif kind == 'arc':
                msp.add_arc(kw['c'], kw['r'], kw['a1'], kw['a2'], dxfattribs=attrs)
            elif kind == 'text':
                p = kw['pos']
                al = {'left': TextEntityAlignment.LEFT,
                      'center': TextEntityAlignment.MIDDLE,
                      'right': TextEntityAlignment.RIGHT}[kw.get('ha', 'left')]
                s = kw['s'].replace('⌀', 'Ø')
                t = msp.add_text(s, dxfattribs=dict(
                    style='GOST', height=kw.get('size', 3.5), color=col,
                    rotation=kw.get('angle', 0)))
                t.set_placement(p, align=al)
        doc.saveas(path)

    def save_pdf(self, path):
        self.finalize()
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.patches import Circle, Wedge, Polygon
        fig = plt.figure(figsize=(self.w / 25.4, self.h / 25.4), dpi=200)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, self.w)
        ax.set_ylim(0, self.h)
        ax.set_aspect('equal')
        ax.axis('off')
        colors = {'frame': 'black', 'outline': 'black', 'dim': '#003366',
                  'text': 'black', 'center': '#888888', 'hidden': '#888888',
                  'note': 'black', 'thin': '#888888'}
        lws = {'thick': 1.6, 'thin': 0.7, 'extra': 2.2, 'hair': 0.5}
        for kind, kw in self.ents:
            c = colors.get(kw.get('col', 'outline'), 'black')
            lw = lws.get(kw.get('lw', 'thick'), 1.0)
            dash = kw.get('dash')
            ls = (0, (6, 2)) if dash == 'center' else ((0, (3, 2)) if dash == 'hidden' else 'solid')
            if kind == 'line':
                ax.plot([kw['p1'][0], kw['p2'][0]], [kw['p1'][1], kw['p2'][1]],
                        color=c, lw=lw, ls=ls, solid_capstyle='round')
            elif kind == 'rect':
                p1, p2 = kw['p1'], kw['p2']
                ax.plot([p1[0], p2[0], p2[0], p1[0], p1[0]],
                        [p1[1], p1[1], p2[1], p2[1], p1[1]],
                        color=c, lw=lw, solid_capstyle='round')
            elif kind == 'poly':
                pts = kw['pts']
                xs = [p[0] for p in pts] + ([pts[0][0]] if kw.get('close') else [])
                ys = [p[1] for p in pts] + ([pts[0][1]] if kw.get('close') else [])
                ax.plot(xs, ys, color=c, lw=lw, solid_capstyle='round')
            elif kind == 'circle':
                ax.add_patch(Circle(kw['c'], kw['r'], fill=False, ec=c, lw=lw))
            elif kind == 'arc':
                ax.add_patch(Wedge(kw['c'], kw['r'], kw['a1'], kw['a2'],
                                   width=0.001, ec=c, lw=lw))
            elif kind == 'text':
                ang = kw.get('angle', 0)
                ha = kw.get('ha', 'left')
                va = {'center': 'center', 'bottom': 'bottom', 'top': 'top'}.get(kw.get('va', 'center'), 'center')
                ax.text(kw['pos'][0], kw['pos'][1], kw['s'], fontsize=kw.get('size', 3.5) * 2.83,
                        color=c, ha=ha, va=va, rotation=ang, rotation_mode='anchor',
                        family='DejaVu Sans')
        fmt = 'pdf' if path.lower().endswith('.pdf') else 'png'
        fig.savefig(path, format=fmt, dpi=200)
        plt.close(fig)


def pick_scale(w_mm, h_mm, aw, ah):
    """Подбор масштаба из ряда, чтобы вписать w x h в поле aw x ah."""
    for s in [1, 2, 5, 10, 20, 50, 100]:
        if w_mm / s <= aw and h_mm / s <= ah:
            return 1.0 / s, f"1:{s}"
    for s in [2, 5]:
        if w_mm * s <= aw and h_mm * s <= ah:
            return float(s), f"{s}:1"
    return 1.0 / 100, "1:100"
