# -*- coding: utf-8 -*-
"""
views.py — построение чертёжных видов из BREP-геометрии (HLR, OpenCascade).
Возвращает список 2D-примитивов (отрезки/дуги) в координатах вида.
"""
import math
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir, gp_Vec
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopoDS import TopoDS
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GCPnts import GCPnts_QuasiUniformDeflection
from OCP.BRep import BRep_Tool


def _edge_to_segments(edge, deflection=0.08):
    """Кривая ребра -> полилиния (x,y), z отбрасывается (проекция)."""
    try:
        ad = BRepAdaptor_Curve(edge)
    except Exception:
        return []
    try:
        disc = GCPnts_QuasiUniformDeflection(ad, deflection)
    except Exception:
        return []
    pts = []
    if disc.IsDone():
        for i in range(1, disc.NbPoints() + 1):
            p = disc.Value(i)
            pts.append((p.X(), p.Y()))
    else:
        p0 = ad.Value(ad.FirstParameter())
        p1 = ad.Value(ad.LastParameter())
        pts = [(p0.X(), p0.Y()), (p1.X(), p1.Y())]
    return pts


def _collect(compound, deflection=0.08):
    out = []
    if compound is None or compound.IsNull():
        return out
    ex = TopExp_Explorer(compound, TopAbs_EDGE)
    while ex.More():
        e = TopoDS.Edge_s(ex.Current())
        pts = _edge_to_segments(e, deflection)
        if len(pts) >= 2:
            out.append(pts)
        ex.Next()
    return out


def hlr_view(shape, direction, up, deflection=0.08, with_hidden=True):
    """
    Вид вдоль direction (от наблюдателя), 'up' - вертикаль вида.
    Возвращает (visible_polylines, hidden_polylines) в координатах вида.
    """
    d = gp_Dir(*direction)
    # базис вида: x-вправо, y-вверх
    upv = gp_Vec(*up)
    upv = upv - gp_Vec(d.X(), d.Y(), d.Z()) * upv.Dot(gp_Vec(d.X(), d.Y(), d.Z()))
    if upv.Magnitude() < 1e-9:
        upv = gp_Vec(0, 0, 1)
    upv.Normalize()
    right = gp_Vec(d.X(), d.Y(), d.Z()).Crossed(upv)
    ax = gp_Ax2(gp_Pnt(0, 0, 0), d, gp_Dir(right.X(), right.Y(), right.Z()))
    hlr = HLRBRep_Algo()
    hlr.Add(shape)
    prj = HLRAlgo_Projector(ax)
    hlr.Projector(prj)
    hlr.Update()
    hlr.Hide()
    toshape = HLRBRep_HLRToShape(hlr)
    vis = []
    hid = []
    try:
        vis += _collect(toshape.VCompound(), deflection)
    except Exception:
        pass
    try:
        vis += _collect(toshape.OutLineVCompound(), deflection)
    except Exception:
        pass
    try:
        vis += _collect(toshape.Rg1LineVCompound(), deflection)
    except Exception:
        pass
    if with_hidden:
        try:
            hid += _collect(toshape.HCompound(), deflection)
        except Exception:
            pass
    # HLR возвращает координаты в базисе проектора, где ось Y = d x right = -up;
    # приводим к виду «вверх = up» (согласовано с view_project)
    vis = [[(x, -y) for (x, y) in pl] for pl in vis]
    hid = [[(x, -y) for (x, y) in pl] for pl in hid]
    return vis, hid


def bbox2d(polys):
    xs, ys = [], []
    for pl in polys:
        for x, y in pl:
            xs.append(x)
            ys.append(y)
    if not xs:
        return (0, 0, 0, 0)
    return (min(xs), min(ys), max(xs), max(ys))


def view_project(p, direction, up):
    """Проекция 3D-точки в координаты вида (согласовано с hlr_view)."""
    d = direction
    L = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2) or 1.0
    d = (d[0] / L, d[1] / L, d[2] / L)
    u = [up[0], up[1], up[2]]
    dd = u[0] * d[0] + u[1] * d[1] + u[2] * d[2]
    u = [u[i] - dd * d[i] for i in range(3)]
    un = math.sqrt(u[0] ** 2 + u[1] ** 2 + u[2] ** 2) or 1.0
    u = (u[0] / un, u[1] / un, u[2] / un)
    right = (d[1] * u[2] - d[2] * u[1],
             d[2] * u[0] - d[0] * u[2],
             d[0] * u[1] - d[1] * u[0])
    return (p[0] * right[0] + p[1] * right[1] + p[2] * right[2],
            p[0] * u[0] + p[1] * u[1] + p[2] * u[2])
