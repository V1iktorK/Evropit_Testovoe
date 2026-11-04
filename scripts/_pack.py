# -*- coding: utf-8 -*-
"""Упаковка комплекта КД в ZIP для отправки заказчику."""
import sys, os, zipfile, datetime
sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUT = os.path.join(ROOT, 'Комплект_КД_PSH24-000.00.zip')

# папки/файлы, которые входят в комплект
PARTS = ['01_Чертежи_2D', '02_Контуры_резки', '03_BOM', '04_Маршрутные_карты', 'docs']
SKIP_DIRS = {'__pycache__', '_smoke'}

# служебные файлы, не входящие в комплект
SKIP_NAMES = {'push2.txt', 'gen_drawings.log'}

n = 0
with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for part in PARTS:
        base = os.path.join(ROOT, part)
        if not os.path.exists(base):
            print('нет:', part)
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in sorted(filenames):
                if fn in SKIP_NAMES or fn.startswith('~$'):
                    continue
                p = os.path.join(dirpath, fn)
                rel = os.path.relpath(p, ROOT).replace(os.sep, '/')
                z.write(p, rel)
                n += 1
    # корневая 3D-модель — по просьбе заказчика исходник
    stp = os.path.join(ROOT, '05_Модель', 'PSH24-000.00.stp')
    if os.path.exists(stp):
        z.write(stp, '05_Модель/PSH24-000.00.stp')
        n += 1

sz = os.path.getsize(OUT)
print(f'файлов: {n}')
print(f'архив:  {OUT}')
print(f'размер: {sz/1024/1024:.1f} МБ')

# оглавление верхнего уровня
with zipfile.ZipFile(OUT) as z:
    tops = sorted({n_.split('/')[0] for n_ in z.namelist()})
print('состав:', ', '.join(tops))
