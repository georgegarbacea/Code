"""Setup pages: Installation & calibration, Network (Art-Net / SP801E), Phone, Settings."""
from __future__ import annotations

import secrets
import shutil
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..audio.capture import list_devices
from ..core import autostart
from ..core.artnet import local_ipv4_addresses, valid_ipv4
from ..core.compat import run_check
from ..core.config import APP_VERSION, COLOR_ORDERS, Config, app_data_dir, load_json, profile_x_positions, \
    save_json
from ..core.mapping import OutputMapper, TestPattern
from . import theme as T
from .pages import Page, clear_layout, combo, set_combo
from .widgets import ColorButton, SliderRow, Toggle, ToggleRow, button, card, hbox, label


def spin(lo, hi, val, step=1, dec=0, suffix="") -> QSpinBox | QDoubleSpinBox:
    if dec:
        s = QDoubleSpinBox()
        s.setDecimals(dec)
        s.setSingleStep(step)
    else:
        s = QSpinBox()
        s.setSingleStep(int(step))
    s.setRange(lo, hi)
    s.setValue(val)
    if suffix:
        s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    return s


class Worker(QObject):
    done = Signal(object)

    def run(self, fn):
        def target():
            try:
                res = fn()
            except Exception as e:  # pragma: no cover
                res = e
            self.done.emit(res)
        threading.Thread(target=target, daemon=True).start()


# ===================================================================== INSTALLATION
TESTS = [
    ("off", "Oprit"), ("solid", "Culoare solidă"), ("pixel", "Pixel individual"),
    ("count", "Numărare pixeli (primii N din DATA)"), ("direction", "Direcție DATA (jos roșu → sus albastru)"),
    ("ports", "Porturi (P1 roșu, P2 verde, P3 albastru, P4 alb)"), ("marks", "Marcaje la fiecare 10 pixeli"),
]


class HardwarePage(Page):
    title = "Instalație & calibrare"
    subtitle = "12 profile verticale, 4 porturi SP801E, cablare serpentină ↑ ↓ ↑ – totul editabil"

    def __init__(self, ctrl, win):
        super().__init__(ctrl, win)
        self.sel = 0
        self._loading = False
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.timeout.connect(self._apply_pending)
        self._pending = None

        # ---- profiles table
        c, l = card("Profile", "Click pe un rând sau direct pe un profil din simulator pentru a-l edita.")
        self.table = QTableWidget(12, 6)
        self.table.setHorizontalHeaderLabels(["Profil", "Port", "Poz. lanț", "DATA", "Pixeli", "Activ"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setFixedHeight(12 * 27 + 32)
        self.table.verticalHeader().setDefaultSectionSize(27)
        self.table.itemSelectionChanged.connect(self._table_sel)
        l.addWidget(self.table)
        self.lay.addWidget(c)

        # ---- selected profile form
        c, l = card("Profil selectat")
        self.sel_title = label("", "h2")
        l.addWidget(self.sel_title)
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(8)
        self.f_enabled = Toggle(True)
        self.f_port = combo([(i, f"Port {i}") for i in range(1, 5)])
        self.f_chain = spin(0, 11, 0)
        self.f_dir = combo([(True, "↑ DATA intră jos"), (False, "↓ DATA intră sus")])
        self.f_pixels = spin(1, 1024, 84)
        self.f_skip = spin(0, 256, 0)
        self.f_len = spin(10, 600, 140, 1, 1, " cm")
        self.f_x = spin(0, 2000, 0, 1, 1, " cm")
        self.f_bottom = spin(0, 400, 40, 1, 1, " cm")
        self.f_bright = spin(0, 100, 100, 1, 0, " %")
        self.f_r = spin(0, 100, 100, 1, 0, " %")
        self.f_g = spin(0, 100, 100, 1, 0, " %")
        self.f_b = spin(0, 100, 100, 1, 0, " %")
        rows = [("Activ", self.f_enabled), ("Port SP801E", self.f_port), ("Poziție în lanțul DATA", self.f_chain),
                ("Direcție DATA", self.f_dir), ("Pixeli adresabili (IC)", self.f_pixels),
                ("Pixeli ignorați la început", self.f_skip), ("Lungime", self.f_len), ("Poziție X", self.f_x),
                ("Înălțime de la podea", self.f_bottom), ("Luminozitate profil", self.f_bright),
                ("Balans R", self.f_r), ("Balans G", self.f_g), ("Balans B", self.f_b)]
        for i, (t, w) in enumerate(rows):
            g.addWidget(label(t, "muted"), i, 0)
            g.addWidget(w, i, 1)
        g.setColumnStretch(1, 1)
        l.addLayout(g)
        for w in (self.f_chain, self.f_pixels, self.f_skip, self.f_len, self.f_x, self.f_bottom, self.f_bright,
                  self.f_r, self.f_g, self.f_b):
            w.valueChanged.connect(self._form_changed)
        self.f_port.currentIndexChanged.connect(self._form_changed)
        self.f_dir.currentIndexChanged.connect(self._form_changed)
        self.f_enabled.toggled.connect(self._form_changed)
        b_all = button("Aplică numărul de pixeli la toate profilele")
        b_all.clicked.connect(self._pixels_all)
        b_lay = button("Reface cablarea implicită (3 profile/port, ↑ ↓ ↑)")
        b_lay.clicked.connect(self._default_wiring)
        l.addWidget(b_all)
        l.addWidget(b_lay)
        self.lay.addWidget(c)

        # ---- tests
        c, l = card("Teste & calibrare", "Testele ocolesc efectele și adresează direct pixelii reali.")
        self.t_kind = combo(TESTS, "off")
        self.t_kind.currentIndexChanged.connect(self._test_changed)
        l.addLayout(hbox(label("Test", "muted"), self.t_kind))
        self.t_all = ToggleRow("Toate profilele (altfel doar profilul selectat)", False)
        self.t_all.toggled.connect(self._test_changed)
        l.addWidget(self.t_all)
        crow = QHBoxLayout()
        crow.addWidget(label("Culoare", "muted"))
        self.t_colors = []
        for name, col in (("R", "#ff0000"), ("G", "#00ff00"), ("B", "#0000ff"), ("W", "#ffffff")):
            b = button(name, "chip", checkable=True)
            b.setStyleSheet(f"QPushButton {{ color: {col}; }}")
            b.clicked.connect(lambda _=False, c_=col, bb=b: self._pick_color(c_, bb))
            self.t_colors.append(b)
            crow.addWidget(b)
        self.t_colors[3].setChecked(True)
        self.t_color = "#ffffff"
        crow.addStretch(1)
        l.addLayout(crow)
        self.t_index = SliderRow("Index pixel / N", 0, 1024, 0, decimals=0)
        self.t_index.valueChanged.connect(lambda v: self._set_index(int(round(v))))
        l.addWidget(self.t_index)
        nav = QHBoxLayout()
        self.t_spin = spin(0, 1024, 0)
        self.t_spin.valueChanged.connect(self._set_index)
        prev = button("◀")
        prev.clicked.connect(lambda: self._set_index(self.t_spin.value() - 1))
        nxt = button("▶")
        nxt.clicked.connect(lambda: self._set_index(self.t_spin.value() + 1))
        self.walk = button("Parcurgere automată", checkable=True)
        self.walk.toggled.connect(lambda on: self._walk_timer.start(120) if on else self._walk_timer.stop())
        self.set_count = button("Setează pixeli = N", "accent",
                                tip="La testul de numărare: când lumina ajunge exact la capătul profilului, apasă aici")
        self.set_count.clicked.connect(self._apply_count)
        nav.addWidget(prev)
        nav.addWidget(self.t_spin)
        nav.addWidget(nxt)
        nav.addWidget(self.walk)
        nav.addStretch(1)
        nav.addWidget(self.set_count)
        l.addLayout(nav)
        self._walk_timer = QTimer(self)
        self._walk_timer.timeout.connect(lambda: self._set_index(self.t_spin.value() + 1, wrap=True))
        stop = button("Oprește testul", "danger")
        stop.clicked.connect(lambda: set_combo(self.t_kind, "off") or self._test_changed())
        l.addWidget(stop)
        l.addWidget(label(
            "Calibrare recomandată: 1) «Porturi» – verifică că fiecare grup de 3 profile are culoarea portului său. "
            "2) «Direcție DATA» – roșul trebuie să fie JOS pe toate profilele și punctul alb să urce; dacă un profil e "
            "inversat, schimbă «Direcție DATA». 3) «Numărare pixeli» – crește N până când lumina atinge exact capătul "
            "profilului (ultimul pixel e roșu), apoi «Setează pixeli = N».", "dim", wrap=True))
        self.lay.addWidget(c)

        # ---- ports & universes
        c, l = card("Porturi & universuri Art-Net",
                    "Un port nu este presupus a fi un singur univers: fiecare port începe la universul configurat și "
                    "continuă pe universurile următoare (170 pixeli RGB / univers).")
        self.ports_table = QTableWidget(4, 6)
        self.ports_table.setHorizontalHeaderLabels(["Port", "Univers start", "Canal start", "Pixeli/univers",
                                                    "Ordine RGB", "Utilizare"])
        self.ports_table.verticalHeader().setVisible(False)
        self.ports_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.ports_table.setFixedHeight(4 * 34 + 32)
        self.ports_table.verticalHeader().setDefaultSectionSize(34)
        self.port_w = []
        for i in range(4):
            it = QTableWidgetItem(f"Port {i + 1}")
            it.setForeground(QColor(T.PORT_COLORS[i]))
            self.ports_table.setItem(i, 0, it)
            u = spin(0, 32767, 0)
            ch = spin(1, 510, 1)
            ppu = spin(1, 170, 170)
            order = combo([(o, o) for o in COLOR_ORDERS], "RGB")
            use = QLabel("")
            use.setProperty("role", "dim")
            for col, w in ((1, u), (2, ch), (3, ppu), (4, order), (5, use)):
                self.ports_table.setCellWidget(i, col, w)
            for w in (u, ch, ppu):
                w.valueChanged.connect(self._ports_changed)
            order.currentIndexChanged.connect(self._ports_changed)
            self.port_w.append((u, ch, ppu, order, use))
        l.addWidget(self.ports_table)
        auto = button("Alocare automată contiguă a universurilor")
        auto.clicked.connect(self._auto_universes)
        l.addWidget(auto)
        self.report = label("", "muted", wrap=True)
        l.addWidget(self.report)
        self.lay.addWidget(c)

        # ---- geometry + photo
        c, l = card("Geometrie perete & simulator")
        g = QGridLayout()
        w = ctrl.cfg.wall
        self.g_spacing = spin(5, 200, w.profile_spacing_cm, 1, 1, " cm")
        self.g_gap = spin(20, 600, w.fireplace_gap_cm, 1, 1, " cm")
        self.g_fw = spin(20, 400, w.fireplace_width_cm, 1, 1, " cm")
        self.g_fh = spin(10, 200, w.fireplace_height_cm, 1, 1, " cm")
        self.g_fb = spin(0, 200, w.fireplace_bottom_cm, 1, 1, " cm")
        self.g_ww = spin(100, 2000, w.wall_width_cm, 1, 1, " cm")
        self.g_wh = spin(100, 600, w.wall_height_cm, 1, 1, " cm")
        self.g_rows = spin(8, 512, w.matrix_rows)
        items = [("Distanță între profile", self.g_spacing), ("Distanță profil 6 ↔ 7", self.g_gap),
                 ("Lățime șemineu", self.g_fw), ("Înălțime șemineu", self.g_fh), ("Șemineu de la podea", self.g_fb),
                 ("Lățime perete", self.g_ww), ("Înălțime perete", self.g_wh), ("Rânduri matrice virtuală", self.g_rows)]
        for i, (t, wdg) in enumerate(items):
            g.addWidget(label(t, "muted"), i, 0)
            g.addWidget(wdg, i, 1)
        l.addLayout(g)
        ap = button("Aplică geometria (repoziționează profilele)", "primary")
        ap.clicked.connect(self._apply_geometry)
        l.addWidget(ap)
        l.addWidget(label("Fotografia reală a peretelui", "section"))
        prow = QHBoxLayout()
        bl = button("Încarcă fotografie…")
        bl.clicked.connect(self._load_photo)
        br = button("Elimină fotografia")
        br.clicked.connect(self._remove_photo)
        self.edit_btn = button("Poziționează profilele pe foto", checkable=True)
        self.edit_btn.toggled.connect(self._edit_mode)
        prow.addWidget(bl)
        prow.addWidget(br)
        prow.addWidget(self.edit_btn)
        l.addLayout(prow)
        rs = button("Resetează pozițiile profilelor")
        rs.clicked.connect(self._reset_views)
        l.addWidget(rs)
        self.photo_b = SliderRow("Luminozitate foto (LED stinse)", 0.1, 1.0, w.photo_brightness,
                                 fmt=lambda v: f"{v * 100:.0f}%")
        self.photo_b.valueChanged.connect(lambda v: self._edit(lambda c: setattr(c.wall, "photo_brightness", round(v, 2))))
        l.addWidget(self.photo_b)
        l.addWidget(label("În modul de poziționare trage capetele (bulinele) sau tot profilul; ține Shift pentru "
                          "a-l păstra vertical.", "dim", wrap=True))
        self.lay.addWidget(c)

        # ---- limits
        c, l = card("Limitare luminozitate & consum")
        o = ctrl.cfg.output
        self.o_max = SliderRow("Luminozitate maximă globală", 0.05, 1.0, o.max_brightness, fmt=lambda v: f"{v * 100:.0f}%")
        self.o_max.valueChanged.connect(lambda v: self._edit(lambda c: setattr(c.output, "max_brightness", round(v, 3))))
        l.addWidget(self.o_max)
        g = QGridLayout()
        self.o_lim = spin(10, 2000, o.power_limit_w, 5, 0, " W")
        self.o_wpm = spin(1, 60, o.watts_per_meter, 0.5, 1, " W/m")
        self.o_gamma = spin(1.0, 3.0, o.gamma, 0.1, 1)
        self.o_psu = spin(10, 3000, o.supply_w, 10, 0, " W")
        for i, (t, wdg) in enumerate((("Limită putere", self.o_lim), ("Consum bandă", self.o_wpm),
                                       ("Gamma", self.o_gamma), ("Sursă", self.o_psu))):
            g.addWidget(label(t, "muted"), i, 0)
            g.addWidget(wdg, i, 1)
            wdg.valueChanged.connect(self._limits_changed)
        l.addLayout(g)
        self.power_lbl = label("", "muted", wrap=True)
        l.addWidget(self.power_lbl)
        self.lay.addWidget(c)
        self.lay.addStretch(1)

        self.win.wall.profileClicked.connect(self.select)
        self.win.wall.viewsEdited.connect(self._views_edited)
        self.load()

    # ---------------------------------------------------------------- data
    def load(self):
        self._loading = True
        cfg = self.ctrl.cfg
        for i, p in enumerate(cfg.profiles):
            vals = [p.label, f"P{p.port}", str(p.chain_pos + 1), "↑" if p.data_up else "↓", str(p.pixels),
                    "da" if p.enabled else "nu"]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setTextAlignment(Qt.AlignCenter)
                if j == 1:
                    it.setForeground(QColor(T.PORT_COLORS[p.port - 1]))
                self.table.setItem(i, j, it)
        for i, pc in enumerate(cfg.ports):
            u, ch, ppu, order, use = self.port_w[i]
            for w_, v in ((u, pc.universe), (ch, pc.start_channel), (ppu, pc.pixels_per_universe)):
                w_.blockSignals(True)
                w_.setValue(v)
                w_.blockSignals(False)
            set_combo(order, pc.color_order)
        self._load_form()
        self._update_report()
        self._loading = False

    def _load_form(self):
        self._loading = True
        p = self.ctrl.cfg.profiles[self.sel]
        self.sel_title.setText(f"{p.label}  ·  {'stânga' if self.sel < 6 else 'dreapta'} șemineului")
        self.f_enabled.setCheckedSilent(p.enabled)
        for w, v in ((self.f_chain, p.chain_pos), (self.f_pixels, p.pixels), (self.f_skip, p.skip_pixels),
                     (self.f_len, p.length_cm), (self.f_x, p.x_cm), (self.f_bottom, p.bottom_cm),
                     (self.f_bright, round(p.brightness * 100)), (self.f_r, round(p.gain_r * 100)),
                     (self.f_g, round(p.gain_g * 100)), (self.f_b, round(p.gain_b * 100))):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        set_combo(self.f_port, p.port)
        set_combo(self.f_dir, p.data_up)
        self.t_index.hi = max(1, p.pixels)
        self.t_spin.setMaximum(1024)
        self._loading = False

    def _update_report(self):
        m = OutputMapper(self.ctrl.cfg)
        r = m.report()
        for i in range(4):
            unis = m.port_universes[i]
            txt = f"{m.port_len[i]} px · U{unis[0]}–U{unis[-1]}" if unis else "neutilizat"
            self.port_w[i][4].setText(txt)
        lines = [f"<span style='color:{T.DANGER}'>✗ {e}</span>" for e in r.errors]
        lines += [f"<span style='color:{T.WARN}'>⚠ {w}</span>" for w in r.warnings]
        lines += [f"<span style='color:{T.MUTED}'>• {i}</span>" for i in r.info]
        lines.append(f"<span style='color:{T.MUTED}'>• Total: {r.total_pixels} pixeli adresabili</span>")
        self.report.setText("<br>".join(lines))

    def _edit(self, fn, delay=250):
        """Queue a config modification (debounced)."""
        if self._loading:
            return
        if self._pending is None:
            self._pending = self.ctrl.cfg.copy()
        fn(self._pending)
        self._apply_timer.start(delay)

    def _apply_pending(self):
        if self._pending is not None:
            cfg = self._pending
            self._pending = None
            self.ctrl.apply_config(cfg, restart_audio=False)

    def on_config(self):
        if self._pending is None:
            self.load()
            self._limits_label()

    # ------------------------------------------------------------- profiles
    def select(self, i: int):
        self.sel = max(0, min(11, i))
        self.table.blockSignals(True)
        self.table.selectRow(self.sel)
        self.table.blockSignals(False)
        self.win.wall.selected = self.sel
        self._load_form()
        self._test_changed()

    def _table_sel(self):
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self.select(rows[0].row())

    def _form_changed(self, *_):
        if self._loading:
            return
        i = self.sel
        vals = dict(enabled=self.f_enabled.isChecked(), port=self.f_port.currentData(), chain_pos=self.f_chain.value(),
                    data_up=self.f_dir.currentData(), pixels=self.f_pixels.value(), skip_pixels=self.f_skip.value(),
                    length_cm=self.f_len.value(), x_cm=self.f_x.value(), bottom_cm=self.f_bottom.value(),
                    brightness=self.f_bright.value() / 100, gain_r=self.f_r.value() / 100,
                    gain_g=self.f_g.value() / 100, gain_b=self.f_b.value() / 100)

        def fn(c):
            for k, v in vals.items():
                setattr(c.profiles[i], k, v)
        self._edit(fn)

    def _pixels_all(self):
        n = self.f_pixels.value()

        def fn(c):
            for p in c.profiles:
                p.pixels = n
            c.wall.matrix_rows = max(c.wall.matrix_rows, min(512, n)) if n > c.wall.matrix_rows else c.wall.matrix_rows
        self._edit(fn, 10)

    def _default_wiring(self):
        def fn(c):
            for i, p in enumerate(c.profiles):
                p.port = i // 3 + 1
                p.chain_pos = i % 3
                p.data_up = (i % 3) % 2 == 0
        self._edit(fn, 10)

    # --------------------------------------------------------------- ports
    def _ports_changed(self, *_):
        vals = [(u.value(), ch.value(), ppu.value(), order.currentData()) for u, ch, ppu, order, _ in self.port_w]

        def fn(c):
            for i, (u, ch, ppu, order) in enumerate(vals):
                c.ports[i].universe, c.ports[i].start_channel = u, ch
                c.ports[i].pixels_per_universe, c.ports[i].color_order = ppu, order
        self._edit(fn)

    def _auto_universes(self):
        m = OutputMapper(self.ctrl.cfg)

        def fn(c):
            u = c.ports[0].universe
            for i in range(4):
                c.ports[i].universe = u
                c.ports[i].start_channel = 1
                need = max(1, -(-m.port_len[i] // c.ports[i].pixels_per_universe))
                u += need
        self._edit(fn, 10)

    # ---------------------------------------------------------------- tests
    def _pick_color(self, col, btn):
        for b in self.t_colors:
            b.setChecked(b is btn)
        self.t_color = col
        self._test_changed()

    def _set_index(self, v, wrap=False):
        p = self.ctrl.cfg.profiles[self.sel]
        hi = 1024 if self.t_kind.currentData() == "count" else max(0, p.pixels - 1)
        if wrap and v > hi:
            v = 0
        v = max(0, min(hi, int(v)))
        self.t_spin.blockSignals(True)
        self.t_spin.setValue(v)
        self.t_spin.blockSignals(False)
        self.t_index.hi = max(1, hi)
        self.t_index.setValue(v)
        self._test_changed()

    def _test_changed(self, *_):
        kind = self.t_kind.currentData()
        if kind == "off":
            self.ctrl.set_test(None)
            self.walk.setChecked(False)
            self.win.wall.show_ports = False
            return
        col = QColor(self.t_color)
        tp = TestPattern(kind=kind, profile=-1 if self.t_all.isChecked() else self.sel,
                         color=(col.redF(), col.greenF(), col.blueF()), index=self.t_spin.value())
        self.win.wall.show_ports = kind in ("ports", "direction")
        self.ctrl.set_test(tp)

    def _apply_count(self):
        n = self.t_spin.value()
        if n <= 0:
            return
        i = self.sel
        self._edit(lambda c: setattr(c.profiles[i], "pixels", n), 10)
        self.win.toast(f"Profil {i + 1}: {n} pixeli")

    # ------------------------------------------------------------ geometry
    def _apply_geometry(self):
        vals = dict(profile_spacing_cm=self.g_spacing.value(), fireplace_gap_cm=self.g_gap.value(),
                    fireplace_width_cm=self.g_fw.value(), fireplace_height_cm=self.g_fh.value(),
                    fireplace_bottom_cm=self.g_fb.value(), wall_width_cm=self.g_ww.value(),
                    wall_height_cm=self.g_wh.value(), matrix_rows=self.g_rows.value())

        def fn(c):
            for k, v in vals.items():
                setattr(c.wall, k, v)
            xs = profile_x_positions(c.wall)
            for i, p in enumerate(c.profiles):
                p.x_cm = xs[i]
                if not c.wall.photo_path:
                    p.view = None
        self._edit(fn, 10)

    def _load_photo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Fotografia peretelui", "", "Imagini (*.jpg *.jpeg *.png *.bmp *.webp)")
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Foto", "Imaginea nu poate fi citită.")
            return
        dst = app_data_dir() / "wall_photo.jpg"
        img.save(str(dst), "JPG", 92)
        self._edit(lambda c: setattr(c.wall, "photo_path", str(dst)), 10)
        self.edit_btn.setChecked(True)
        self.win.toast("Fotografie încărcată – poziționează profilele peste ea")

    def _remove_photo(self):
        self._edit(lambda c: setattr(c.wall, "photo_path", ""), 10)

    def _edit_mode(self, on):
        self.win.wall.edit_mode = on
        self.win.wall.update()

    def _reset_views(self):
        def fn(c):
            for p in c.profiles:
                p.view = None
        self._edit(fn, 10)

    def _views_edited(self, views):
        def fn(c):
            for i, v in enumerate(views):
                c.profiles[i].view = [round(x, 5) for x in v]
        self._edit(fn, 10)

    # -------------------------------------------------------------- limits
    def _limits_changed(self, *_):
        vals = (self.o_lim.value(), self.o_wpm.value(), self.o_gamma.value(), self.o_psu.value())

        def fn(c):
            c.output.power_limit_w, c.output.watts_per_meter, c.output.gamma, c.output.supply_w = vals
        self._edit(fn)

    def _limits_label(self):
        cfg = self.ctrl.cfg
        total_m = sum(p.length_cm for p in cfg.profiles) / 100
        full = total_m * cfg.output.watts_per_meter
        self.power_lbl.setText(
            f"Lungime totală {total_m:.1f} m · consum maxim teoretic {full:.0f} W ({full / 12:.1f} A la 12 V) · "
            f"limită {cfg.output.power_limit_w:.0f} W · sursă {cfg.output.supply_w:.0f} W "
            f"({cfg.output.power_limit_w / max(1, cfg.output.supply_w) * 100:.0f}% din sursă).")

    def tick(self, fo):
        self._limits_label()
        self.power_lbl.setText(self.power_lbl.text() + f"<br><b>Acum: ≈ {fo.power_w:.0f} W</b>"
                               + (" (limitat)" if fo.power_scale < 0.999 else ""))

    def on_show(self):
        self.load()
        self.win.wall.selected = self.sel

    def on_hide(self):
        if self.t_kind.currentData() != "off":
            set_combo(self.t_kind, "off")
            self._test_changed()
        self.walk.setChecked(False)
        self.win.wall.selected = -1
        self.win.wall.show_ports = False


# ===================================================================== NETWORK
class NetworkPage(Page):
    title = "Rețea · Art-Net · SP801E"
    subtitle = "Transmisie Art-Net UDP către controlerul BanlanX SP801E (WiFi)"

    def __init__(self, ctrl, win):
        super().__init__(ctrl, win)
        n = ctrl.cfg.network
        c, l = card("Transmisie")
        self.out = ToggleRow("Trimite cadre către instalație", n.output_enabled,
                             "Dezactivat = doar simulator. La oprire se trimite blackout (oprire controlată).")
        self.out.toggled.connect(lambda v: self.ctrl.set_output_enabled(v))
        l.addWidget(self.out)
        self.stats = label("", "muted", wrap=True)
        l.addWidget(self.stats)
        self.lay.addWidget(c)

        c, l = card("Controler")
        g = QGridLayout()
        self.ip = QLineEdit(n.controller_ip)
        self.ip.setPlaceholderText("ex. 192.168.1.50")
        self.iface = QComboBox()
        self.iface.addItem("Automat", "")
        for ip in local_ipv4_addresses():
            self.iface.addItem(ip, ip)
        set_combo(self.iface, n.interface_ip)
        self.fps = SliderRow("FPS țintă transmisie", 5, 60, n.target_fps, decimals=0, fmt=lambda v: f"{v:.0f} FPS")
        g.addWidget(label("IP controler", "muted"), 0, 0)
        g.addWidget(self.ip, 0, 1)
        g.addWidget(label("Interfață locală", "muted"), 1, 0)
        g.addWidget(self.iface, 1, 1)
        l.addLayout(g)
        l.addWidget(self.fps)
        self.adapt = ToggleRow("Rată adaptivă", n.adaptive_fps,
                               "Limitată la refresh-ul WS2811 al celui mai lung lanț; scade automat la congestie WiFi")
        self.change = ToggleRow("Trimite doar la schimbare (+ keep-alive)", n.send_on_change,
                                "Reduce traficul WiFi în scenele statice")
        self.sync = ToggleRow("ArtSync după fiecare cadru", n.art_sync, "Doar dacă firmware-ul controlerului îl suportă")
        for w in (self.adapt, self.change, self.sync):
            l.addWidget(w)
        save = button("Salvează setările de rețea", "primary")
        save.clicked.connect(self._save)
        l.addWidget(save)
        self.lay.addWidget(c)

        c, l = card("Descoperire automată (ArtPoll)")
        self.scan = button("Caută controlere în rețea")
        self.scan.clicked.connect(self._scan)
        l.addWidget(self.scan)
        self.nodes = QListWidget()
        self.nodes.setMinimumHeight(90)
        l.addWidget(self.nodes)
        r = QHBoxLayout()
        use = button("Folosește IP-ul selectat")
        use.clicked.connect(self._use_node)
        mapb = button("Aplică maparea universurilor din controler")
        mapb.clicked.connect(self._map_node)
        r.addWidget(use)
        r.addWidget(mapb)
        l.addLayout(r)
        self.lay.addWidget(c)

        c, l = card("Verificare compatibilitate", "Rulează înainte de prima transmisie: rețea, ArtPoll, porturi, "
                                                  "universuri, capacitate, rată de cadre.")
        chk = button("Verifică compatibilitatea controlerului", "accent")
        chk.clicked.connect(self._check)
        l.addWidget(chk)
        self.check_out = label("", "muted", wrap=True)
        self.check_out.setTextFormat(Qt.RichText)
        l.addWidget(self.check_out)
        self.apply_fps = button("Aplică FPS recomandat")
        self.apply_fps.setVisible(False)
        self.apply_fps.clicked.connect(self._apply_rec)
        l.addWidget(self.apply_fps)
        self.lay.addWidget(c)

        c, l = card("Despre SP801E")
        l.addWidget(label(
            "BanlanX SP801E: controler WiFi Art-Net cu 4 ieșiri SPI/TTL, max. 1024 pixeli/port (4096 total, "
            "declarat de producător), IC-uri one-wire (WS2811/WS2812B/SK6812…), 5–24 V. Se configurează din "
            "aplicația BanlanX (mod AP sau STA). Pentru Art-Net: activează modul Art-Net în aplicație, setează tipul "
            "IC (WS2811), ordinea culorilor, numărul de pixeli pe port și universul de start al fiecărui port. "
            "Recomandare: mod STA (în rețeaua casei) cu IP rezervat în router, transmisie unicast.", "dim", wrap=True))
        self.lay.addWidget(c)
        self.lay.addStretch(1)
        self.worker = Worker()
        self.worker.done.connect(self._worker_done)
        self._job = ""
        self._rec = None

    def _save(self):
        ip = self.ip.text().strip()
        if ip and not valid_ipv4(ip):
            QMessageBox.warning(self, "IP", "Adresa IP nu este validă.")
            return
        cfg = self.ctrl.cfg.copy()
        n = cfg.network
        n.controller_ip = ip
        n.interface_ip = self.iface.currentData() or ""
        n.target_fps = int(self.fps.value())
        n.adaptive_fps = self.adapt.isChecked()
        n.send_on_change = self.change.isChecked()
        n.art_sync = self.sync.isChecked()
        self.ctrl.apply_config(cfg, restart_audio=False)
        self.win.toast("Setări de rețea salvate")

    def _scan(self):
        self.scan.setEnabled(False)
        self.scan.setText("Caut…")
        self._job = "scan"
        self.worker.run(lambda: self.ctrl.discover(2.0))

    def _check(self):
        self.check_out.setText("Verific…")
        self._job = "check"
        self.worker.run(lambda: run_check(self.ctrl.cfg, self.ctrl.artnet))

    def _worker_done(self, res):
        if self._job == "scan":
            self.scan.setEnabled(True)
            self.scan.setText("Caută controlere în rețea")
            self.nodes.clear()
            if isinstance(res, Exception) or not res:
                self.nodes.addItem("Niciun nod Art-Net nu a răspuns (vezi Verificare compatibilitate).")
                return
            for n in res:
                it = QListWidgetItem(("★ " if n.looks_like_sp801e else "") + n.describe())
                it.setData(Qt.UserRole, n)
                self.nodes.addItem(it)
        elif self._job == "check":
            if isinstance(res, Exception):
                self.check_out.setText(f"Eroare: {res}")
                return
            icons = {"ok": ("✓", T.OK), "warn": ("⚠", T.WARN), "error": ("✗", T.DANGER), "info": ("•", T.MUTED)}
            lines = []
            for c_ in res.checks:
                ic, col = icons[c_.level]
                lines.append(f"<p style='margin:4px 0'><span style='color:{col}'>{ic} <b>{c_.title}</b></span>"
                             f"<br><span style='color:{T.MUTED}'>{c_.detail}</span></p>")
            verdict = (f"<p style='color:{T.OK}'><b>Compatibil – poți activa transmisia.</b></p>" if res.ok else
                       f"<p style='color:{T.DANGER}'><b>Corectează erorile înainte de transmisie.</b></p>")
            self.check_out.setText(verdict + "".join(lines))
            self._rec = res.recommended_fps
            self.apply_fps.setText(f"Aplică FPS recomandat ({res.recommended_fps})")
            self.apply_fps.setVisible(True)

    def _apply_rec(self):
        if self._rec:
            cfg = self.ctrl.cfg.copy()
            cfg.network.target_fps = int(self._rec)
            self.ctrl.apply_config(cfg, restart_audio=False)
            self.fps.setValue(self._rec)

    def _node(self):
        it = self.nodes.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _use_node(self):
        n = self._node()
        if n:
            self.ip.setText(n.ip)
            self._save()

    def _map_node(self):
        n = self._node()
        if n and n.sw_out:
            self.ctrl.apply_node_mapping(n)
            self.ip.setText(n.ip)
            self.win.toast("Universurile porturilor au fost preluate din controler")

    def on_config(self):
        n = self.ctrl.cfg.network
        self.out.setChecked(n.output_enabled)

    def tick(self, fo):
        s = self.ctrl.artnet.stats()
        names = {"disabled": "oprită (doar simulator)", "connecting": "conectare…", "sending": "se trimite (fără confirmare ArtPoll)",
                 "online": "online – controlerul răspunde", "lost": "controlerul nu mai răspunde la ArtPoll", "error": "eroare"}
        txt = (f"Stare: <b>{names.get(s['status'], s['status'])}</b> · țintă {s['target'] or '-'} · "
               f"{s['fps']} FPS · {s['kbps']} kbit/s · pachete {s['packets']} · erori {s['errors']}")
        if s["fps_scale"] < 1:
            txt += f" · rată redusă la {s['fps_scale'] * 100:.0f}%"
        if s["last_error"]:
            txt += f"<br><span style='color:{T.WARN}'>{s['last_error']}</span>"
        self.stats.setText(txt)


# ===================================================================== PHONE
def qr_image(text: str, scale: int = 6) -> QImage | None:
    try:
        import qrcode
    except Exception:
        return None
    q = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(text)
    q.make(fit=True)
    m = q.get_matrix()
    n = len(m)
    img = QImage(n * scale, n * scale, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            if v:
                p.fillRect(x * scale, y * scale, scale, scale, QColor("#0b0d14"))
    p.end()
    return img


class PhonePage(Page):
    title = "Control de pe telefon"
    subtitle = "Interfață web locală, protejată cu PIN, accesibilă doar din rețeaua WiFi a casei"

    def __init__(self, ctrl, win):
        super().__init__(ctrl, win)
        w = ctrl.cfg.web
        c, l = card("Server web local")
        self.en = ToggleRow("Activează controlul de pe telefon", w.enabled)
        self.en.toggled.connect(self._toggle)
        l.addWidget(self.en)
        self.port = spin(1024, 65535, w.port)
        self.port.valueChanged.connect(self._port)
        l.addLayout(hbox(label("Port", "muted"), "stretch", self.port))
        self.pin = label("", "h1")
        regen = button("Generează PIN nou")
        regen.clicked.connect(self._regen)
        l.addLayout(hbox(label("PIN", "muted"), self.pin, "stretch", regen))
        self.status = label("", "muted", wrap=True)
        l.addWidget(self.status)
        self.lay.addWidget(c)
        c, l = card("Scanează cu telefonul", "Telefonul trebuie să fie conectat la aceeași rețea WiFi ca PC-ul.")
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignCenter)
        self.qr.setMinimumHeight(240)
        l.addWidget(self.qr)
        self.urls = label("", "value", wrap=True)
        self.urls.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l.addWidget(self.urls)
        self.lay.addWidget(c)
        c, l = card("Securitate")
        l.addWidget(label(
            "• Serverul acceptă doar adrese din rețele private (192.168.x.x, 10.x.x.x, 172.16–31.x.x).<br>"
            "• Accesul necesită PIN; sesiunea este un cookie semnat (HttpOnly). Un PIN nou deconectează telefoanele.<br>"
            "• Nu deschide/redirecționa portul în router – aplicația nu face niciodată port forwarding sau UPnP.<br>"
            "• La prima pornire Windows poate întreba de firewall: permite DOAR rețelele private.", "dim", wrap=True))
        self.lay.addWidget(c)
        self.lay.addStretch(1)
        self.refresh()

    def _toggle(self, on):
        cfg = self.ctrl.cfg.copy()
        cfg.web.enabled = on
        self.ctrl.apply_config(cfg, restart_audio=False)
        QTimer.singleShot(600, self.refresh)

    def _port(self, v):
        cfg = self.ctrl.cfg.copy()
        cfg.web.port = int(v)
        self.ctrl.apply_config(cfg, restart_audio=False)
        QTimer.singleShot(600, self.refresh)

    def _regen(self):
        cfg = self.ctrl.cfg.copy()
        cfg.web.pin = f"{secrets.randbelow(10 ** 6):06d}"
        self.ctrl.apply_config(cfg, restart_audio=False)
        QTimer.singleShot(600, self.refresh)

    def refresh(self):
        w = self.ctrl.cfg.web
        self.pin.setText(" ".join(w.pin[i:i + 3] for i in (0, 3)))
        web = self.ctrl.web
        if not w.enabled:
            self.status.setText("Serverul este oprit.")
            self.qr.clear()
            self.urls.setText("")
            return
        urls = web.urls if web else []
        err = web.error if web else ""
        self.status.setText(f"<span style='color:{T.DANGER}'>{err}</span>" if err else
                            f"<span style='color:{T.OK}'>Activ</span> pe portul {w.port}")
        self.urls.setText("<br>".join(urls))
        if urls:
            img = qr_image(f"{urls[0]}/?pin={w.pin}")
            if img:
                self.qr.setPixmap(QPixmap.fromImage(img).scaled(220, 220, Qt.KeepAspectRatio, Qt.FastTransformation))

    def on_show(self):
        self.refresh()


# ===================================================================== SETTINGS
class SettingsPage(Page):
    title = "Setări"
    subtitle = "Sursă audio, pornire cu Windows, simulator, configurație"

    def __init__(self, ctrl, win):
        super().__init__(ctrl, win)
        a = ctrl.cfg.audio
        c, l = card("Captură audio")
        self.src = combo([("loopback", "Sunetul sistemului (WASAPI Loopback)"), ("mic", "Microfon / intrare externă"),
                          ("demo", "Piesă demo internă (fără muzică)")], a.source)
        l.addLayout(hbox(label("Sursă", "muted"), self.src))
        self.dev = QComboBox()
        ref = button("↻", tip="Reîmprospătează dispozitivele")
        ref.clicked.connect(self._devices)
        l.addLayout(hbox(label("Dispozitiv", "muted"), self.dev, ref))
        self.block = combo([(256, "256 eșantioane (~5 ms, latență minimă)"), (512, "512 eșantioane (~11 ms, recomandat)"),
                            (1024, "1024 eșantioane (~21 ms, CPU redus)")], a.block_size)
        l.addLayout(hbox(label("Bloc analiză", "muted"), self.block))
        self.gate = SliderRow("Prag zgomot (noise gate)", -90, -30, a.noise_gate_db, fmt=lambda v: f"{v:.0f} dBFS")
        l.addWidget(self.gate)
        ap = button("Aplică sursa audio", "primary")
        ap.clicked.connect(self._apply_audio)
        l.addWidget(ap)
        self.audio_status = label("", "muted", wrap=True)
        l.addWidget(self.audio_status)
        l.addWidget(label("Loopback captează tot ce redă Windows (Spotify, YouTube, VLC, browser…) de pe dispozitivul "
                          "de redare implicit, independent de volum; dacă schimbi căștile/boxele, captura se reconectează "
                          "automat.", "dim", wrap=True))
        self.src.currentIndexChanged.connect(self._devices)
        self.lay.addWidget(c)

        ap_ = ctrl.cfg.app
        c, l = card("Aplicație")
        self.auto = ToggleRow("Pornește automat odată cu Windows", autostart.is_enabled() or ap_.autostart,
                              "Pornește minimizat în zona de notificare" if autostart.is_supported() else
                              "Disponibil doar pe Windows")
        self.auto.toggled.connect(self._autostart)
        self.auto.setEnabled(autostart.is_supported())
        l.addWidget(self.auto)
        self.tray = ToggleRow("Închiderea ferestrei minimizează în tray", ap_.close_to_tray,
                              "Instalația continuă să funcționeze în fundal")
        self.tray.toggled.connect(lambda v: self._app(close_to_tray=v))
        l.addWidget(self.tray)
        self.minst = ToggleRow("Pornește minimizat", ap_.start_minimized)
        self.minst.toggled.connect(lambda v: self._app(start_minimized=v))
        l.addWidget(self.minst)
        self.flame = ToggleRow("Flacără animată în șemineul din simulator", ap_.show_fireplace_flame)
        self.flame.toggled.connect(lambda v: self._app(show_fireplace_flame=v))
        l.addWidget(self.flame)
        self.simfps = combo([(30, "30 FPS"), (60, "60 FPS (recomandat)")], ap_.sim_fps)
        self.simfps.currentIndexChanged.connect(lambda _: self._app(sim_fps=self.simfps.currentData()))
        l.addLayout(hbox(label("Rată simulator / motor efecte", "muted"), self.simfps))
        self.lay.addWidget(c)

        c, l = card("Configurație hardware")
        r = QHBoxLayout()
        for txt, fn in (("Exportă configurația…", self._export), ("Importă configurația…", self._import),
                        ("Valori implicite", self._reset)):
            b = button(txt, "danger" if "implicite" in txt else None)
            b.clicked.connect(fn)
            r.addWidget(b)
        l.addLayout(r)
        l.addWidget(label(f"Datele aplicației: {app_data_dir()}", "dim", wrap=True))
        self.lay.addWidget(c)

        c, l = card("Despre")
        l.addWidget(label(f"<b>LumiBeat Studio {APP_VERSION}</b><br>Vizualizator muzical și controler LED pentru "
                          "peretele cu 12 profile WS2811 și SP801E.<br>Tehnologii gratuite: Python, PySide6 (LGPL), "
                          "NumPy, SciPy, PyOpenGL, FastAPI, Uvicorn, PyAudioWPatch (MIT). Fără abonamente.", "muted",
                          wrap=True))
        self.lay.addWidget(c)
        self.lay.addStretch(1)
        self._devices()

    def _devices(self, *_):
        src = self.src.currentData()
        self.dev.clear()
        self.dev.addItem("Implicit Windows", "")
        if src in ("loopback", "mic"):
            try:
                for name in list_devices().get(src, []):
                    self.dev.addItem(name, name)
            except Exception:
                pass
        self.dev.setEnabled(src != "demo")
        set_combo(self.dev, self.ctrl.cfg.audio.device)

    def _apply_audio(self):
        cfg = self.ctrl.cfg.copy()
        cfg.audio.source = self.src.currentData()
        cfg.audio.device = self.dev.currentData() or ""
        cfg.audio.block_size = int(self.block.currentData())
        cfg.audio.noise_gate_db = round(self.gate.value(), 1)
        self.ctrl.apply_config(cfg, restart_audio=True)
        self.win.toast("Sursa audio a fost repornită")

    def _autostart(self, on):
        ok = autostart.set_enabled(on)
        self._app(autostart=on)
        if not ok and autostart.is_supported():
            QMessageBox.warning(self, "Pornire automată", "Nu am putut scrie în registrul Windows.")

    def _app(self, **kw):
        cfg = self.ctrl.cfg.copy()
        for k, v in kw.items():
            setattr(cfg.app, k, v)
        self.ctrl.apply_config(cfg, restart_audio=False)

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Exportă configurația", "lumibeat-config.json", "JSON (*.json)")
        if path:
            save_json(Path(path), self.ctrl.cfg.to_dict())
            self.win.toast("Configurație exportată")

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importă configurația", "", "JSON (*.json)")
        if path:
            data = load_json(Path(path), None)
            if not isinstance(data, dict):
                QMessageBox.warning(self, "Import", "Fișier invalid.")
                return
            self.ctrl.apply_config(Config.from_dict(data))
            self.win.toast("Configurație importată")

    def _reset(self):
        if QMessageBox.question(self, "Valori implicite", "Resetezi configurația hardware la valorile implicite?\n"
                                "(PIN-ul telefonului și setările audio se păstrează)") != QMessageBox.Yes:
            return
        cfg = Config.default()
        cfg.web = self.ctrl.cfg.web
        cfg.audio = self.ctrl.cfg.audio
        cfg.app = self.ctrl.cfg.app
        self.ctrl.apply_config(cfg)

    def tick(self, fo):
        i = self.ctrl.capture.info()
        lat = self.ctrl.cfg.audio.block_size / max(1, i["sample_rate"]) * 1000
        txt = (f"Stare: <b>{i['status']}</b> · {i['device'] or '-'} · {i['sample_rate']} Hz · {i['channels']} canale · "
               f"latență analiză ≈ {lat:.0f} ms")
        if i["error"]:
            txt += f"<br><span style='color:{T.DANGER}'>{i['error']}</span>"
        self.audio_status.setText(txt)
