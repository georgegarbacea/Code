"""Show pages: Music, Party, Ambient, Studio (+ presets)."""
from __future__ import annotations

import copy
import json
import math

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
                               QWidget)

from ..core.party import PARTY_PRESETS, PRESET_ORDER
from ..effects import REGISTRY, ambient_effect_ids, music_effect_ids
from ..effects.custom import BLENDS, DEFAULT_LAYER, DIRECTIONS, SYMMETRIES, normalize_spec
from ..effects.palettes import PALETTE_ORDER, PALETTES
from ..effects.transitions import TRANSITIONS
from . import theme as T
from .widgets import (BigToggleButton, ColorButton, EffectCard, FlowGrid, PaletteChip, SliderRow, Toggle,
                      ToggleRow, button, card, flow, hbox, label)


class Page(QWidget):
    title = ""
    subtitle = ""

    def __init__(self, ctrl, win):
        super().__init__()
        self.ctrl = ctrl
        self.win = win
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(4, 4, 14, 18)
        self.lay.setSpacing(14)

    def on_state(self, changed: dict):
        pass

    def on_config(self):
        pass

    def on_show(self):
        pass

    def tick(self, fo):
        pass


def combo(items, current=None) -> QComboBox:
    c = QComboBox()
    for val, text in items:
        c.addItem(text, val)
    if current is not None:
        i = c.findData(current)
        if i >= 0:
            c.setCurrentIndex(i)
    return c


def set_combo(c: QComboBox, val):
    i = c.findData(val)
    if i >= 0 and i != c.currentIndex():
        c.blockSignals(True)
        c.setCurrentIndex(i)
        c.blockSignals(False)


def build_params(layout: QVBoxLayout, cls, values: dict, on_change, skip=("speed",)) -> list:
    """Auto-generate controls for an effect's parameters."""
    widgets = []
    for p in cls.all_params():
        if p.key in skip:
            continue
        v = values.get(p.key, p.default)
        if p.kind in ("float", "int"):
            dec = 0 if p.kind == "int" else 2
            w = SliderRow(p.label, p.lo, p.hi, float(v), decimals=dec)
            if p.kind == "int":
                w.valueChanged.connect(lambda x, k=p.key: on_change(k, int(round(x))))
            else:
                w.valueChanged.connect(lambda x, k=p.key: on_change(k, round(x, 3)))
        elif p.kind == "bool":
            w = ToggleRow(p.label, bool(v))
            w.toggled.connect(lambda x, k=p.key: on_change(k, bool(x)))
        elif p.kind == "choice":
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(label(p.label, "muted"))
            cb = combo(p.choices, v)
            cb.currentIndexChanged.connect(lambda _i, k=p.key, c=cb: on_change(k, c.currentData()))
            h.addWidget(cb, 1)
            w = row
        else:
            continue
        layout.addWidget(w)
        widgets.append(w)
    if not widgets:
        layout.addWidget(label("Acest efect nu are parametri suplimentari.", "dim"))
    return widgets


def clear_layout(lay):
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w:
            w.setParent(None)
            w.deleteLater()
        elif it.layout():
            clear_layout(it.layout())


# ===================================================================== MUSIC
FILTERS = [
    ("all", "Toate"), ("special", "Speciale perete"), ("spectrum", "Spectru"), ("calm", "Atmosferă"),
    ("particles", "Particule"), ("geometric", "Geometric / Retro"), ("peak", "Energice"),
]


class MusicPage(Page):
    title = "Music"
    subtitle = "Vizualizator muzical în stil MilkDrop, reacționează la muzica redată în Windows"

    def __init__(self, ctrl, win):
        super().__init__(ctrl, win)
        st = ctrl.state()
        c, l = card("Efecte", f"{len(music_effect_ids())} efecte distincte · click pentru a rula")
        chips = FlowGrid(0, 6)
        self.filter_btns = []
        for fid, txt in FILTERS:
            b = button(txt, "chip", checkable=True)
            b.setChecked(fid == "all")
            b.clicked.connect(lambda _=False, f=fid: self.set_filter(f))
            chips.add(b)
            self.filter_btns.append((fid, b))
        l.addWidget(chips)
        self.grid = FlowGrid(172)
        self.cards: dict[str, EffectCard] = {}
        for eid in music_effect_ids():
            cls = REGISTRY[eid]
            cd = EffectCard(eid, cls.name, cls.category, cls.description)
            cd.clicked.connect(lambda _=False, e=eid: self.ctrl.set_state(music_effect=e, mode="music"))
            self.cards[eid] = cd
            self.grid.add(cd)
        l.addWidget(self.grid)
        self.lay.addWidget(c)

        c, l = card("Paletă de culori")
        self.pal_grid = FlowGrid(96, 6)
        self.pal_chips: dict[str, PaletteChip] = {}
        auto = PaletteChip("auto", "Auto (efect)", ["#ff00e6", "#00d5ff", "#00ffa2", "#ffd000"])
        self.pal_chips["auto"] = auto
        self.pal_grid.add(auto)
        color = PaletteChip("color", "Culoarea mea", [st.color, "#ffffff"])
        self.pal_chips["color"] = color
        self.pal_grid.add(color)
        for pid in PALETTE_ORDER:
            name, stops, _ = PALETTES[pid]
            if pid == "custom":
                stops = st.custom_palette
            chip = PaletteChip(pid, name, stops)
            self.pal_chips[pid] = chip
            self.pal_grid.add(chip)
        for pid, chip in self.pal_chips.items():
            chip.clicked.connect(lambda _=False, p=pid: self.ctrl.set_state(palette=p))
        l.addWidget(self.pal_grid)
        crow = QHBoxLayout()
        crow.addWidget(label("Paletă personalizată:", "muted"))
        self.custom_btns = []
        for i in range(4):
            cb = ColorButton(st.custom_palette[i % len(st.custom_palette)], 30)
            cb.colorChanged.connect(lambda _c, k=i: self._custom_changed())
            self.custom_btns.append(cb)
            crow.addWidget(cb)
        crow.addStretch(1)
        l.addLayout(crow)
        crow2 = QHBoxLayout()
        crow2.addWidget(label("Culoarea mea:", "muted"))
        self.color_btn = ColorButton(st.color, 30)
        self.color_btn.colorChanged.connect(lambda c: self.ctrl.set_state(color=c, palette="color"))
        crow2.addWidget(self.color_btn)
        crow2.addStretch(1)
        l.addLayout(crow2)
        self.lay.addWidget(c)

        self.param_card, self.param_lay = card("Parametrii efectului")
        self.param_box = QVBoxLayout()
        self.param_lay.addLayout(self.param_box)
        self.lay.addWidget(self.param_card)

        c, l = card("Tranziții între efecte")
        self.trans = combo(TRANSITIONS, st.transition)
        self.trans.currentIndexChanged.connect(lambda _: self.ctrl.set_state(transition=self.trans.currentData()))
        l.addLayout(hbox(label("Tip", "muted"), self.trans))
        self.trans_time = SliderRow("Durată tranziție", 0.1, 6.0, st.transition_time, fmt=lambda v: f"{v:.1f} s")
        self.trans_time.valueChanged.connect(lambda v: self.ctrl.set_state(transition_time=round(v, 2)))
        l.addWidget(self.trans_time)
        self.lay.addWidget(c)
        self.lay.addStretch(1)
        self._effect = None
        self.sync(st)

    def set_filter(self, fid: str):
        for f, b in self.filter_btns:
            b.setChecked(f == fid)
        for eid, cd in self.cards.items():
            cls = REGISTRY[eid]
            if fid == "all":
                vis = True
            elif fid == "special":
                vis = cls.category == "special"
            elif fid == "geometric":
                vis = "geometric" in cls.tags or "retro" in cls.tags
            else:
                vis = fid in cls.tags
            cd.setHidden(not vis)
        self.grid.refilter()

    def _custom_changed(self):
        cols = [b.color for b in self.custom_btns]
        self.pal_chips["custom"].stops = cols + [cols[0]]
        self.pal_chips["custom"].update()
        self.ctrl.set_state(custom_palette=cols + [cols[0]], palette="custom")

    def set_thumb(self, eid, img):
        if eid in self.cards:
            self.cards[eid].set_thumb(img)

    def sync(self, st):
        for eid, cd in self.cards.items():
            cd.setChecked(st.mode == "music" and eid == st.music_effect)
        for pid, chip in self.pal_chips.items():
            chip.setChecked(pid == st.palette)
        self.pal_chips["color"].stops = [st.color, "#ffffff"]
        self.pal_chips["color"].update()
        self.color_btn.setColor(st.color)
        set_combo(self.trans, st.transition)
        self.trans_time.setValue(st.transition_time)
        if st.music_effect != self._effect:
            self._effect = st.music_effect
            clear_layout(self.param_box)
            cls = REGISTRY.get(st.music_effect)
            if cls:
                self.param_card.findChild(QLabel).setText(f"PARAMETRII EFECTULUI · {cls.name.upper()}")
                self.param_box.addWidget(label(cls.description, "muted", wrap=True))
                sp = SliderRow("Viteză efect", 0.1, 3.0, float(st.effect_params.get(cls.id, {}).get("speed", 1.0)),
                               fmt=lambda v: f"{v:.2f}×")
                sp.valueChanged.connect(lambda v, e=cls.id: self.ctrl.set_effect_param(e, "speed", round(v, 3)))
                self.param_box.addWidget(sp)
                build_params(self.param_box, cls, st.effect_params.get(cls.id, {}),
                             lambda k, v, e=cls.id: self.ctrl.set_effect_param(e, k, v))

    def on_state(self, changed):
        self.sync(self.ctrl.state())


# ===================================================================== PARTY
class PartyMeter(QWidget):
    """Live analysis panel: BPM, section, energy, bands, beat and drop indicators."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(180)
        self.fo = None
        self.beat_flash = 0.0
        self.drop_flash = 0.0
        self.last_beat = 0
        self.last_drop = 0

    def update_from(self, fo):
        a = fo.audio
        if a.beat_count != self.last_beat:
            self.last_beat = a.beat_count
            self.beat_flash = 1.0
        if a.drop_count != self.last_drop:
            self.last_drop = a.drop_count
            self.drop_flash = 1.0
        self.beat_flash *= 0.82
        self.drop_flash *= 0.95
        self.fo = fo
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        fo = self.fo
        a = fo.audio if fo else None
        # BPM block
        f = QFont(self.font())
        f.setPointSizeF(34)
        f.setBold(True)
        p.setFont(f)
        bpm = f"{a.bpm:.0f}" if a and a.bpm > 0 and not a.silent else "--"
        p.setPen(QColor(T.TEXT))
        p.drawText(QRectF(0, 0, 150, 60), Qt.AlignLeft | Qt.AlignVCenter, bpm)
        f.setPointSizeF(9)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(T.MUTED))
        p.drawText(QRectF(0, 56, 150, 18), Qt.AlignLeft, "BPM  ·  încredere " + (f"{a.bpm_confidence * 100:.0f}%" if a else "-"))
        # beat dot
        c = QColor(T.A3)
        c.setAlphaF(0.25 + 0.75 * self.beat_flash)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(124, 18, 18, 18))
        # section badge
        sec = fo.section if fo and fo.section else "—"
        style = fo.style if fo and fo.style else ""
        f.setPointSizeF(11)
        f.setBold(True)
        p.setFont(f)
        bx = 170
        badge = QRectF(bx, 8, 150, 30)
        g = QLinearGradient(badge.topLeft(), badge.topRight())
        if sec == "DROP" or self.drop_flash > 0.3:
            g.setColorAt(0, QColor(T.A3)); g.setColorAt(1, QColor(T.WARN))
        else:
            g.setColorAt(0, QColor(T.A1)); g.setColorAt(1, QColor(T.A2))
        p.setBrush(g)
        p.drawRoundedRect(badge, 15, 15)
        p.setPen(QColor("white"))
        p.drawText(badge, Qt.AlignCenter, sec.upper())
        f.setPointSizeF(9)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(T.MUTED))
        p.drawText(QRectF(bx, 42, r.width() - bx, 18), Qt.AlignLeft, style)
        if fo and fo.beats_left:
            p.drawText(QRectF(bx, 60, r.width() - bx, 18), Qt.AlignLeft, f"Următoarea schimbare în {fo.beats_left} bătăi")
        if fo:
            p.setPen(QColor(T.TEXT))
            p.drawText(QRectF(bx, 78, r.width() - bx, 18), Qt.AlignLeft, f"Efect: {fo.effect_name}")
        # bars
        names = [("Energie", a.energy if a else 0, T.A1), ("Bass", a.bass if a else 0, T.A3),
                 ("Medii", a.mid if a else 0, T.A2), ("Înalte", a.high if a else 0, T.WARN),
                 ("Build-up", a.buildup if a else 0, T.OK)]
        y0 = 108
        bw = (r.width() - 20) / len(names)
        for i, (n, v, col) in enumerate(names):
            x = i * bw
            p.setPen(QColor(T.MUTED))
            p.drawText(QRectF(x, y0, bw - 10, 16), Qt.AlignLeft, n)
            track = QRectF(x, y0 + 22, bw - 14, 8)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.SURFACE3))
            p.drawRoundedRect(track, 4, 4)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(track.left(), track.top(), track.width() * max(0.0, min(1.0, float(v))), 8), 4, 4)
        if self.drop_flash > 0.05:
            p.setPen(QColor(255, 181, 71, int(255 * self.drop_flash)))
            f.setBold(True)
            f.setPointSizeF(12)
            p.setFont(f)
            p.drawText(QRectF(0, 150, r.width(), 30), Qt.AlignCenter, "⚡ BASS DROP")


class PresetCard(QAbstractButton):
    def __init__(self, pid: str):
        super().__init__()
        self.pid = pid
        self.p = PARTY_PRESETS[pid]
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(196, 92)
        pals = self.p["palettes"] or ["neon", "festival", "chill"]
        self.stops = PALETTES[pals[0]][1]

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        n = max(1, len(self.stops) - 1)
        for i, s in enumerate(self.stops):
            c = QColor(s)
            c.setAlphaF(0.55 if self.isChecked() else 0.28)
            g.setColorAt(i / n, c)
        p.setBrush(QColor(T.SURFACE))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(r, 14, 14)
        p.setBrush(g)
        p.drawRoundedRect(r, 14, 14)
        if self.isChecked():
            p.setPen(QPen(QColor("white"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 13, 13)
        f = QFont(self.font())
        f.setPointSizeF(12.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("white"))
        name = ("✦ " if self.pid == "auto_dj" else "") + self.p["name"]
        p.drawText(r.adjusted(14, 10, -10, -40), Qt.AlignLeft | Qt.AlignTop, name)
        f.setPointSizeF(8.5)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(235, 238, 248, 210))
        p.drawText(r.adjusted(14, 40, -10, -8), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self.p["desc"])


class PartyPage(Page):
    title = "Party"
    subtitle = "Spectacol complet automat: BPM, ritm, bass drop, tranziții, sincronizare simetrică"

    def __init__(self, ctrl, win):
        super().__init__(ctrl, win)
        st = ctrl.state()
        self.start = BigToggleButton("PARTY MODE", "Pornește spectacolul automat sincronizat cu muzica", 70)
        self.start.toggled.connect(lambda on: self.ctrl.set_state(mode="party" if on else "music"))
        self.lay.addWidget(self.start)
        c, l = card("Analiză live")
        self.meter = PartyMeter()
        l.addWidget(self.meter)
        self.lay.addWidget(c)
        c, l = card("Presetări Party")
        self.grid = FlowGrid(200, 8)
        self.cards = {}
        for pid in PRESET_ORDER:
            pc = PresetCard(pid)
            pc.clicked.connect(lambda _=False, p=pid: self.ctrl.set_state(party_preset=p, mode="party"))
            self.cards[pid] = pc
            self.grid.add(pc)
        l.addWidget(self.grid)
        self.lay.addWidget(c)
        c, l = card("Comportament")
        self.duration = SliderRow("Durata efectelor", 0.25, 4.0, st.duration,
                                  fmt=lambda v: f"{v:.2f}× fraza muzicală")
        self.duration.valueChanged.connect(lambda v: self.ctrl.set_state(duration=round(v, 2)))
        l.addWidget(self.duration)
        self.sym = ToggleRow("Sincronizare simetrică stânga / dreapta", st.symmetric,
                             "Profilele 1–6 și 7–12 se oglindesc față de șemineu")
        self.sym.toggled.connect(lambda v: self.ctrl.set_state(symmetric=v))
        l.addWidget(self.sym)
        self.agc = ToggleRow("Adaptare automată a sensibilității", st.auto_sensitivity,
                             "Normalizează volumul (AGC) pentru orice nivel de redare")
        self.agc.toggled.connect(lambda v: self.ctrl.set_state(auto_sensitivity=v))
        l.addWidget(self.agc)
        self.sb = ToggleRow("Standby ambiental când muzica se oprește", st.standby_enabled,
                            "După 4 secunde de liniște trece pe o scenă ambientală discretă")
        self.sb.toggled.connect(lambda v: self.ctrl.set_state(standby_enabled=v))
        l.addWidget(self.sb)
        self.sb_scene = combo([(k, REGISTRY[k].name) for k in ambient_effect_ids()], st.standby_scene)
        self.sb_scene.currentIndexChanged.connect(lambda _: self.ctrl.set_state(standby_scene=self.sb_scene.currentData()))
        l.addLayout(hbox(label("Scenă standby", "muted"), self.sb_scene))
        self.sb_level = SliderRow("Luminozitate standby", 0.05, 1.0, st.standby_level, fmt=lambda v: f"{v * 100:.0f}%")
        self.sb_level.valueChanged.connect(lambda v: self.ctrl.set_state(standby_level=round(v, 2)))
        l.addWidget(self.sb_level)
        l.addWidget(label("Stroboscopul rămâne dezactivat dacă nu îl activezi separat (bara de jos). "
                          "Chiar și activat, Party îl folosește doar scurt, pe drop-uri.", "dim", wrap=True))
        self.lay.addWidget(c)
        self.lay.addStretch(1)
        self.sync(st)

    def sync(self, st):
        self.start.blockSignals(True)
        self.start.setChecked(st.mode == "party")
        self.start.blockSignals(False)
        for pid, pc in self.cards.items():
            pc.setChecked(pid == st.party_preset)
        self.duration.setValue(st.duration)
        self.sym.setChecked(st.symmetric)
        self.agc.setChecked(st.auto_sensitivity)
        self.sb.setChecked(st.standby_enabled)
        set_combo(self.sb_scene, st.standby_scene)
        self.sb_level.setValue(st.standby_level)

    def on_state(self, changed):
        self.sync(self.ctrl.state())

    def tick(self, fo):
        self.meter.update_from(fo)


# ===================================================================== AMBIENT
class AmbientPage(Page):
    title = "Ambient"
    subtitle = "Scene independente de muzică, pentru utilizarea zilnică"

    def __init__(self, ctrl, win):
        super().__init__(ctrl, win)
        st = ctrl.state()
        c, l = card("Scene")
        self.grid = FlowGrid(172)
        self.cards = {}
        for eid in ambient_effect_ids():
            cls = REGISTRY[eid]
            cd = EffectCard(eid, cls.name, "ambient", cls.description)
            cd.clicked.connect(lambda _=False, e=eid: self.ctrl.set_state(ambient_scene=e, mode="ambient"))
            self.cards[eid] = cd
            self.grid.add(cd)
        l.addWidget(self.grid)
        self.lay.addWidget(c)
        c, l = card("Reglaje scenă")
        self.inten = SliderRow("Intensitate", 0.0, 1.0, st.ambient_intensity, fmt=lambda v: f"{v * 100:.0f}%")
        self.inten.valueChanged.connect(lambda v: self.ctrl.set_state(ambient_intensity=round(v, 3)))
        l.addWidget(self.inten)
        self.temp = SliderRow("Temperatură de culoare (simulată RGB)", 1800, 6500, st.ambient_temp,
                              fmt=lambda v: f"{v:.0f} K", warm=True)
        self.temp.valueChanged.connect(lambda v: self.ctrl.set_state(ambient_temp=int(round(v / 50) * 50)))
        l.addWidget(self.temp)
        self.speed = SliderRow("Viteză animație", 0.1, 3.0, st.ambient_speed, fmt=lambda v: f"{v:.2f}×")
        self.speed.valueChanged.connect(lambda v: self.ctrl.set_state(ambient_speed=round(v, 2)))
        l.addWidget(self.speed)
        self.color = ColorButton(st.color, 32)
        self.color.colorChanged.connect(lambda c: self.ctrl.set_state(color=c, ambient_scene="solid_color", mode="ambient"))
        l.addLayout(hbox(label("Culoare fixă", "muted"), "stretch", self.color))
        self.param_box = QVBoxLayout()
        l.addLayout(self.param_box)
        self.lay.addWidget(c)
        self.lay.addStretch(1)
        self._scene = None
        self.sync(st)

    def set_thumb(self, eid, img):
        if eid in self.cards:
            self.cards[eid].set_thumb(img)

    def sync(self, st):
        for eid, cd in self.cards.items():
            cd.setChecked(st.mode == "ambient" and eid == st.ambient_scene)
        self.inten.setValue(st.ambient_intensity)
        self.temp.setValue(st.ambient_temp)
        self.speed.setValue(st.ambient_speed)
        self.color.setColor(st.color)
        if st.ambient_scene != self._scene:
            self._scene = st.ambient_scene
            clear_layout(self.param_box)
            cls = REGISTRY.get(st.ambient_scene)
            if cls and len(cls.all_params()) > 1:
                build_params(self.param_box, cls, st.effect_params.get(cls.id, {}),
                             lambda k, v, e=cls.id: self.ctrl.set_effect_param(e, k, v))

    def on_state(self, changed):
        self.sync(self.ctrl.state())


# ===================================================================== STUDIO
class LayerEditor(QWidget):
    changed = Signal()
    removed = Signal(object)

    def __init__(self, idx: int, layer: dict):
        super().__init__()
        self.layer = dict(layer)
        f, l = card(None, flat=True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(f)
        top = QHBoxLayout()
        self.title = label(f"STRAT {idx + 1}", "section")
        top.addWidget(self.title)
        top.addStretch(1)
        self.enabled = Toggle(layer.get("enabled", True))
        self.enabled.toggled.connect(lambda v: self._set("enabled", bool(v)))
        top.addWidget(self.enabled)
        rm = button("✕", "ghost", tip="Elimină stratul")
        rm.clicked.connect(lambda: self.removed.emit(self))
        top.addWidget(rm)
        l.addLayout(top)
        effs = [(k, ("★ " if REGISTRY[k].category == "special" else "") + REGISTRY[k].name)
                for k in music_effect_ids() + ambient_effect_ids()]
        self.effect = combo(effs, layer["effect"])
        self.effect.currentIndexChanged.connect(lambda _: self._effect_changed())
        l.addLayout(hbox(label("Efect", "muted"), self.effect))
        pals = [("auto", "Auto (efect)")] + [(k, PALETTES[k][0]) for k in PALETTE_ORDER if k != "custom"] + \
               [("colors", "Culori proprii…")]
        self.palette = combo(pals, "colors" if layer.get("colors") else layer.get("palette", "auto"))
        self.palette.currentIndexChanged.connect(lambda _: self._palette_changed())
        l.addLayout(hbox(label("Culori", "muted"), self.palette))
        crow = QHBoxLayout()
        self.color_btns = []
        cols = layer.get("colors") or ["#7c5cff", "#22d3ee", "#ff4fa3"]
        for i in range(3):
            cb = ColorButton(cols[i % len(cols)], 28)
            cb.colorChanged.connect(lambda _c: self._palette_changed())
            self.color_btns.append(cb)
            crow.addWidget(cb)
        crow.addStretch(1)
        self.color_row = QWidget()
        self.color_row.setLayout(crow)
        self.color_row.setVisible(bool(layer.get("colors")))
        l.addWidget(self.color_row)
        for key, text, lo, hi, fmt in (("speed", "Viteză", 0.1, 3.0, lambda v: f"{v:.2f}×"),
                                       ("intensity", "Intensitate", 0.0, 1.5, lambda v: f"{v * 100:.0f}%"),
                                       ("sensitivity", "Sensibilitate audio", 0.0, 3.0, lambda v: f"{v:.2f}×"),
                                       ("opacity", "Opacitate", 0.0, 1.0, lambda v: f"{v * 100:.0f}%")):
            s = SliderRow(text, lo, hi, float(layer.get(key, 1.0)), fmt=fmt)
            s.valueChanged.connect(lambda v, k=key: self._set(k, round(v, 3)))
            l.addWidget(s)
        g = QHBoxLayout()
        self.direction = combo(DIRECTIONS, layer.get("direction", "up"))
        self.direction.currentIndexChanged.connect(lambda _: self._set("direction", self.direction.currentData()))
        self.symmetry = combo(SYMMETRIES, layer.get("symmetry", "none"))
        self.symmetry.currentIndexChanged.connect(lambda _: self._set("symmetry", self.symmetry.currentData()))
        self.blend = combo(BLENDS, layer.get("blend", "add"))
        self.blend.currentIndexChanged.connect(lambda _: self._set("blend", self.blend.currentData()))
        for t, w in (("Direcție", self.direction), ("Simetrie", self.symmetry), ("Amestec", self.blend)):
            col = QVBoxLayout()
            col.addWidget(label(t, "dim"))
            col.addWidget(w)
            g.addLayout(col)
        l.addLayout(g)
        self.param_box = QVBoxLayout()
        l.addLayout(self.param_box)
        self._build_params()

    def _build_params(self):
        clear_layout(self.param_box)
        cls = REGISTRY.get(self.layer["effect"])
        if cls:
            build_params(self.param_box, cls, self.layer.get("params") or {}, self._param)

    def _param(self, k, v):
        p = dict(self.layer.get("params") or {})
        p[k] = v
        self.layer["params"] = p
        self.changed.emit()

    def _set(self, k, v):
        self.layer[k] = v
        self.changed.emit()

    def _effect_changed(self):
        self.layer["effect"] = self.effect.currentData()
        self.layer["params"] = {}
        self._build_params()
        self.changed.emit()

    def _palette_changed(self):
        v = self.palette.currentData()
        self.color_row.setVisible(v == "colors")
        if v == "colors":
            self.layer["colors"] = [b.color for b in self.color_btns] + [self.color_btns[0].color]
            self.layer["palette"] = "auto"
        else:
            self.layer["colors"] = []
            self.layer["palette"] = v
        self.changed.emit()


class StudioPage(Page):
    title = "Studio"
    subtitle = "Creează efecte proprii din straturi, cu previzualizare în timp real"

    def __init__(self, ctrl, win):
        super().__init__(ctrl, win)
        st = ctrl.state()
        self.spec = normalize_spec(st.studio_spec)
        c, l = card("Efect personalizat")
        self.name = QLineEdit(self.spec["name"])
        self.name.textEdited.connect(self._name)
        l.addLayout(hbox(label("Nume", "muted"), self.name))
        self.live = button("▶  Rulează live pe perete", "primary")
        self.live.clicked.connect(lambda: self.ctrl.set_state(mode="studio", studio_spec=self.spec))
        l.addWidget(self.live)
        self.lay.addWidget(c)
        self.layers_box = QVBoxLayout()
        self.layers_box.setSpacing(10)
        self.lay.addLayout(self.layers_box)
        self.add_btn = button("+  Adaugă strat (max. 4)")
        self.add_btn.clicked.connect(self._add)
        self.lay.addWidget(self.add_btn)
        c, l = card("Tranziție la pornirea efectului")
        self.trans = combo(TRANSITIONS, self.spec["transition"]["type"])
        self.trans.currentIndexChanged.connect(self._trans)
        l.addLayout(hbox(label("Tip", "muted"), self.trans))
        self.trans_t = SliderRow("Durată", 0.1, 6.0, self.spec["transition"]["time"], fmt=lambda v: f"{v:.1f} s")
        self.trans_t.valueChanged.connect(self._trans)
        l.addWidget(self.trans_t)
        self.lay.addWidget(c)
        c, l = card("Presetări", "Salvează starea curentă (orice mod), încarcă, exportă sau importă fișiere .json")
        self.plist = QListWidget()
        self.plist.setMinimumHeight(170)
        self.plist.itemDoubleClicked.connect(lambda _: self._load())
        l.addWidget(self.plist)
        row1 = []
        for txt, fn, kind in (("Salvează curentă", self._save, "primary"), ("Încarcă", self._load, None),
                              ("Șterge", self._delete, "danger")):
            b = button(txt, kind)
            b.clicked.connect(fn)
            row1.append(b)
        l.addWidget(flow(*row1))
        row2 = []
        for txt, fn in (("Exportă selectată", lambda: self._export(True)), ("Exportă toate", lambda: self._export(False)),
                        ("Importă…", self._import)):
            b = button(txt)
            b.clicked.connect(fn)
            row2.append(b)
        l.addWidget(flow(*row2))
        self.lay.addWidget(c)
        self.lay.addStretch(1)
        self._push_timer = QTimer(self)
        self._push_timer.setSingleShot(True)
        self._push_timer.timeout.connect(self._push)
        self._rebuild_layers()
        self.refresh_presets()

    # ---- layers
    def _rebuild_layers(self):
        clear_layout(self.layers_box)
        self.editors = []
        for i, layer in enumerate(self.spec["layers"]):
            ed = LayerEditor(i, layer)
            ed.changed.connect(self._changed)
            ed.removed.connect(self._remove)
            self.layers_box.addWidget(ed)
            self.editors.append(ed)
        self.add_btn.setEnabled(len(self.spec["layers"]) < 4)

    def _changed(self):
        self.spec["layers"] = [ed.layer for ed in self.editors]
        self._push_timer.start(120)

    def _add(self):
        if len(self.spec["layers"]) >= 4:
            return
        self.spec["layers"].append(dict(DEFAULT_LAYER, effect="twinkle", blend="screen"))
        self._rebuild_layers()
        self._push()

    def _remove(self, ed):
        if len(self.editors) <= 1:
            return
        idx = self.editors.index(ed)
        self.spec["layers"].pop(idx)
        self._rebuild_layers()
        self._push()

    def _name(self, txt):
        self.spec["name"] = txt
        self._push_timer.start(300)

    def _trans(self, *_):
        self.spec["transition"] = {"type": self.trans.currentData(), "time": round(self.trans_t.value(), 2)}
        self._push_timer.start(200)

    def _push(self):
        st = self.ctrl.state()
        upd = {"studio_spec": copy.deepcopy(self.spec)}
        if st.mode != "studio":
            upd["mode"] = "studio"
        self.ctrl.set_state(**upd)

    # ---- presets
    def refresh_presets(self):
        self.plist.clear()
        icons = {"music": "♪", "party": "✦", "ambient": "☾", "studio": "◧"}
        for p in self.ctrl.presets.list():
            it = QListWidgetItem(f"{icons.get(p['mode'], '•')}  {p['name']}    ·  {p['mode'].capitalize()}  ·  {p.get('created', '')}")
            it.setData(Qt.UserRole, p["id"])
            self.plist.addItem(it)

    def _selected(self):
        it = self.plist.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _save(self):
        st = self.ctrl.state()
        default = st.studio_spec.get("name", "") if st.mode == "studio" else ""
        name, ok = QInputDialog.getText(self, "Salvează presetarea", f"Nume presetare (mod {st.mode}):", text=default)
        if ok and name.strip():
            self.ctrl.presets.create(name, st)
            self.refresh_presets()
            self.ctrl.emit("presets", None)

    def _load(self):
        pid = self._selected()
        if pid:
            self.ctrl.apply_preset(pid)
            st = self.ctrl.state()
            if st.mode == "studio":
                self.spec = normalize_spec(st.studio_spec)
                self.name.setText(self.spec["name"])
                self._rebuild_layers()

    def _delete(self):
        pid = self._selected()
        if pid and QMessageBox.question(self, "Șterge", "Ștergi presetarea selectată?") == QMessageBox.Yes:
            self.ctrl.presets.delete(pid)
            self.refresh_presets()
            self.ctrl.emit("presets", None)

    def _export(self, selected: bool):
        ids = None
        if selected:
            pid = self._selected()
            if not pid:
                return
            ids = [pid]
        path, _ = QFileDialog.getSaveFileName(self, "Exportă presetări", "lumibeat-presetari.json", "JSON (*.json)")
        if path:
            n = self.ctrl.presets.export(path, ids)
            self.win.toast(f"{n} presetări exportate")

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importă presetări", "", "JSON (*.json)")
        if path:
            try:
                n = self.ctrl.presets.import_file(path)
                self.refresh_presets()
                self.ctrl.emit("presets", None)
                self.win.toast(f"{n} presetări importate")
            except (OSError, ValueError) as e:
                QMessageBox.warning(self, "Import", f"Fișier invalid: {e}")

    def on_state(self, changed):
        if "studio_spec" in changed and changed["studio_spec"] != self.spec:
            self.spec = normalize_spec(changed["studio_spec"])
            self.name.setText(self.spec["name"])
            self._rebuild_layers()
