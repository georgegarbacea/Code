"""Calibration wizard: makes the real wall light up exactly like the simulator.

The wizard addresses the *physical* DATA chain of every port (independent of the current
profile configuration), so it works even when ports, order, direction or pixel count are
wrong.  The user only answers simple questions:

1. how many pixels fill one profile (count from the start of port 1)
2. for every segment of every port: which profile lit up, and is the green end at the
   bottom or at the top
3. a final visual check

From the answers it writes port, chain position, DATA direction and pixel count of every
profile, and the height of the virtual matrix.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from ..core.mapping import TestPattern
from . import theme as T
from .widgets import button, label

SEGMENTS_PER_PORT = 3


def big(text: str, size: int = 22, color: str = T.TEXT) -> QLabel:
    l = QLabel(text)
    l.setWordWrap(True)
    l.setStyleSheet(f"font-size: {size}px; font-weight: 700; color: {color};")
    return l


def para(text: str) -> QLabel:
    l = QLabel(text)
    l.setWordWrap(True)
    l.setTextFormat(Qt.RichText)
    l.setStyleSheet(f"font-size: 14px; color: {T.TEXT}; line-height: 140%;")
    return l


class WallPicker(QWidget):
    """12 buttons laid out like the wall: 6 | fireplace | 6."""

    def __init__(self, on_pick):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = []
        for i in range(12):
            if i == 6:
                fp = QLabel("🔥\nșemineu")
                fp.setAlignment(Qt.AlignCenter)
                fp.setStyleSheet(f"color: {T.WARN}; font-size: 11px; padding: 0 8px;")
                h.addWidget(fp)
            b = QPushButton(str(i + 1))
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumSize(34, 70)
            b.setStyleSheet("font-size: 16px; font-weight: 700;")
            b.clicked.connect(lambda _=False, k=i: on_pick(k))
            self.group.addButton(b, i)
            self.buttons.append(b)
            h.addWidget(b, 1)

    def set_state(self, selected: int | None, used: set[int]):
        self.group.setExclusive(False)
        for i, b in enumerate(self.buttons):
            b.setChecked(i == selected)
            b.setText(f"{i + 1}\n✓" if i in used and i != selected else str(i + 1))
        self.group.setExclusive(True)


class CalibrationWizard(QDialog):
    def __init__(self, ctrl, win):
        super().__init__(win)
        self.ctrl = ctrl
        self.win = win
        self.setWindowTitle("Asistent calibrare – LumiBeat Studio")
        self.setMinimumSize(720, 600)
        self.n = max(1, min(400, ctrl.cfg.profiles[0].pixels if ctrl.cfg.profiles[0].pixels != 84 else 20))
        self.steps = [(p, k) for p in range(4) for k in range(SEGMENTS_PER_PORT)]
        self.si = 0
        self.assign: dict[tuple[int, int], tuple[int, bool]] = {}
        self.skip_ports: set[int] = set()
        self.sel_profile: int | None = None
        self.sel_up: bool | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(14)
        self.title = big("Asistent calibrare", 24)
        self.progress = label("", "muted")
        lay.addWidget(self.title)
        lay.addWidget(self.progress)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {T.BORDER};")
        lay.addWidget(line)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self._build_intro()
        self._build_count()
        self._build_segments()
        self._build_summary()
        self._build_verify()
        self.go(0)

    # ------------------------------------------------------------------ pages
    def _page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)
        self.stack.addWidget(w)
        return v

    def _build_intro(self):
        v = self._page()
        v.addWidget(big("Facem peretele să se aprindă exact ca în simulator", 18))
        v.addWidget(para(
            "Asistentul aprinde pe rând bucăți din banda LED. Tu doar te uiți la perete și apeși "
            "<b>pe ce profil</b> s-a aprins și <b>unde e capătul verde</b> (jos sau sus).<br><br>"
            "La final aplicația setează singură: portul, ordinea în lanțul DATA, direcția și numărul de "
            "pixeli pentru toate cele 12 profile.<br><br>"
            "Profilele sunt numerotate <b>de la stânga la dreapta, 1 → 12</b>, privind peretele "
            "(1–6 în stânga șemineului, 7–12 în dreapta).<br><br>"
            "⏱ Durează 2–3 minute. Transmisia către LED-uri se pornește automat."))
        v.addStretch(1)
        b = button("Începe", "primary")
        b.setMinimumHeight(48)
        b.clicked.connect(self.start)
        v.addWidget(b)

    def _build_count(self):
        v = self._page()
        v.addWidget(big("Pasul 1 · Câți pixeli are un profil?", 18))
        v.addWidget(para(
            "S-a aprins <b>începutul primului profil de pe portul 1</b> (alb, cu ultimul punct <b style='color:#ff5c6c'>roșu</b>).<br>"
            "Apasă <b>+</b> până când lumina umple <b>exact un profil</b>, de la un capăt la celălalt, "
            "cu punctul roșu chiar în capăt.<br>Dacă lumina trece pe profilul următor, apasă <b>−</b>."))
        row = QHBoxLayout()
        row.addStretch(1)
        for d in (-10, -1):
            b = button(f"{d}")
            b.setMinimumSize(70, 56)
            b.setStyleSheet("font-size: 18px; font-weight: 700;")
            b.clicked.connect(lambda _=False, dd=d: self.change_n(dd))
            row.addWidget(b)
        self.n_lbl = big("20", 46, T.A2)
        self.n_lbl.setAlignment(Qt.AlignCenter)
        self.n_lbl.setMinimumWidth(140)
        row.addWidget(self.n_lbl)
        for d in (1, 10):
            b = button(f"+{d}")
            b.setMinimumSize(70, 56)
            b.setStyleSheet("font-size: 18px; font-weight: 700;")
            b.clicked.connect(lambda _=False, dd=d: self.change_n(dd))
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(label("pixeli", "muted"), 0, Qt.AlignHCenter)
        v.addStretch(1)
        nothing = button("Nu se aprinde nimic pe perete")
        nothing.clicked.connect(self.nothing_lit)
        self.count_help = para("")
        v.addWidget(self.count_help)
        v.addWidget(nothing)
        ok = button("Gata – lumina umple exact un profil", "primary")
        ok.setMinimumHeight(48)
        ok.clicked.connect(self.count_done)
        v.addWidget(ok)

    def _build_segments(self):
        v = self._page()
        self.seg_title = big("", 18)
        v.addWidget(self.seg_title)
        v.addWidget(para("Pe perete s-a aprins un profil: capătul <b style='color:#3ddc97'>VERDE</b> e începutul, "
                         "capătul <b style='color:#ff5c6c'>ROȘU</b> e sfârșitul."))
        v.addWidget(label("1. PE CE PROFIL S-A APRINS?", "section"))
        self.picker = WallPicker(self.pick_profile)
        v.addWidget(self.picker)
        v.addWidget(label("2. UNDE E CAPĂTUL VERDE?", "section"))
        r = QHBoxLayout()
        self.b_down = button("⬇  Jos")
        self.b_up = button("⬆  Sus")
        for b, up in ((self.b_down, True), (self.b_up, False)):
            b.setCheckable(True)
            b.setMinimumHeight(54)
            b.setStyleSheet("font-size: 17px; font-weight: 700;")
            b.clicked.connect(lambda _=False, u=up: self.pick_dir(u))
            r.addWidget(b)
        v.addLayout(r)
        v.addStretch(1)
        r2 = QHBoxLayout()
        back = button("← Înapoi")
        back.clicked.connect(self.seg_back)
        none = button("Nu s-a aprins nimic")
        none.setToolTip("Portul are mai puține profile – trece la portul următor")
        none.clicked.connect(self.seg_none)
        r2.addWidget(back)
        r2.addWidget(none)
        v.addLayout(r2)

    def _build_summary(self):
        v = self._page()
        v.addWidget(big("Verifică și aplică", 18))
        self.summary = para("")
        v.addWidget(self.summary, 1)
        r = QHBoxLayout()
        again = button("Reia de la început")
        again.clicked.connect(self.start)
        apply_b = button("Aplică setările", "primary")
        apply_b.setMinimumHeight(48)
        apply_b.clicked.connect(self.apply)
        r.addWidget(again)
        r.addWidget(apply_b, 1)
        v.addLayout(r)

    def _build_verify(self):
        v = self._page()
        v.addWidget(big("Verificare finală", 18))
        v.addWidget(para(
            "Acum pe perete rulează testul de direcție. Pe <b>fiecare</b> profil trebuie să vezi:<br>"
            "• <b style='color:#ff5c6c'>roșu jos</b>, <b style='color:#4f8bff'>albastru sus</b><br>"
            "• un <b>punct alb care urcă</b><br><br>"
            "Dacă e așa, peretele e calibrat: efectele vor arăta exact ca în simulator."))
        v.addStretch(1)
        r = QHBoxLayout()
        no = button("Nu, ceva nu e bine – reiau")
        no.clicked.connect(self.start)
        yes = button("Da, arată corect ✓", "primary")
        yes.setMinimumHeight(48)
        yes.clicked.connect(self.finish)
        r.addWidget(no)
        r.addWidget(yes, 1)
        v.addLayout(r)

    # ------------------------------------------------------------------ flow
    def go(self, i: int):
        self.stack.setCurrentIndex(i)
        names = ["Început", "Pasul 1 din 3 · numărul de pixeli", "Pasul 2 din 3 · ordinea și direcția",
                 "Pasul 3 din 3 · aplicare", "Verificare"]
        self.progress.setText(names[i])

    def start(self):
        self.ctrl.engine.scan_universe = None
        if not self.ctrl.cfg.network.output_enabled:
            self.ctrl.set_output_enabled(True)
        self.assign.clear()
        self.skip_ports.clear()
        self.si = 0
        self.go(1)
        self.show_count()

    def change_n(self, d: int):
        self.n = max(1, min(400, self.n + d))
        self.show_count()

    def show_count(self):
        self.n_lbl.setText(str(self.n))
        self.ctrl.set_test(TestPattern(kind="chaincount", port=0, index=self.n))

    def nothing_lit(self):
        c = self.ctrl.cfg
        self.count_help.setText(
            f"<span style='color:{T.WARN}'>Verifică: <b>Transmisie LED</b> e pornită, aplicația BanlanX e închisă pe "
            f"telefon, iar universul de start al portului 1 în LumiBeat (acum <b>{c.ports[0].universe}</b>) e același "
            f"ca în BanlanX. Poți folosi «Scanare universuri» din pagina Rețea.</span>")

    def count_done(self):
        self.go(2)
        self.si = 0
        self.show_segment()

    def current_step(self):
        while self.si < len(self.steps) and self.steps[self.si][0] in self.skip_ports:
            self.si += 1
        return self.steps[self.si] if self.si < len(self.steps) else None

    def show_segment(self):
        st = self.current_step()
        if st is None:
            self.show_summary()
            return
        p, k = st
        self.seg_title.setText(f"Portul {p + 1} · bucata {k + 1} din {SEGMENTS_PER_PORT}")
        prev = self.assign.get(st)
        self.sel_profile = prev[0] if prev else None
        self.sel_up = prev[1] if prev else None
        used = {a[0] for s, a in self.assign.items() if s != st}
        self.picker.set_state(self.sel_profile, used)
        self.b_down.setChecked(self.sel_up is True)
        self.b_up.setChecked(self.sel_up is False)
        self.ctrl.set_test(TestPattern(kind="chain", port=p, index=k * self.n, length=self.n))
        done = len(self.assign)
        self.progress.setText(f"Pasul 2 din 3 · ordinea și direcția  ({done} din 12 profile identificate)")

    def pick_profile(self, i: int):
        self.sel_profile = i
        used = {a[0] for s, a in self.assign.items() if s != self.current_step()}
        self.picker.set_state(i, used)
        self._maybe_next()

    def pick_dir(self, up: bool):
        self.sel_up = up
        self.b_down.setChecked(up)
        self.b_up.setChecked(not up)
        self._maybe_next()

    def _maybe_next(self):
        if self.sel_profile is None or self.sel_up is None:
            return
        st = self.current_step()
        # a profile can belong to only one segment
        for s in [s for s, a in self.assign.items() if a[0] == self.sel_profile and s != st]:
            del self.assign[s]
        self.assign[st] = (self.sel_profile, self.sel_up)
        self.si += 1
        QTimer.singleShot(250, self.show_segment)

    def seg_back(self):
        if self.si == 0:
            self.go(1)
            self.show_count()
            return
        self.si -= 1
        while self.si > 0 and self.steps[self.si][0] in self.skip_ports:
            self.si -= 1
        self.skip_ports.discard(self.steps[self.si][0])
        self.show_segment()

    def seg_none(self):
        st = self.current_step()
        if st is None:
            return
        p, k = st
        for kk in range(k, SEGMENTS_PER_PORT):
            self.assign.pop((p, kk), None)
        self.skip_ports.add(p)
        self.show_segment()

    def show_summary(self):
        self.ctrl.set_test(None)
        self.go(3)
        rows = []
        by_profile = {a[0]: (s, a[1]) for s, a in self.assign.items()}
        for i in range(12):
            if i in by_profile:
                (p, k), up = by_profile[i]
                rows.append(f"<tr><td><b>Profil {i + 1}</b></td><td>Port {p + 1}</td><td>poziția {k + 1}</td>"
                            f"<td>{'↑ DATA intră jos' if up else '↓ DATA intră sus'}</td></tr>")
            else:
                rows.append(f"<tr><td><b>Profil {i + 1}</b></td><td colspan=3 style='color:{T.WARN}'>"
                            "neidentificat – va fi dezactivat</td></tr>")
        warn = ""
        per_port = [sum(1 for (p, _k) in self.assign if p == port) * self.n for port in range(4)]
        need = max(1, math.ceil(max(per_port) / 170)) if max(per_port) else 1
        cfg = self.ctrl.cfg
        starts = [pc.universe for pc in cfg.ports]
        gaps = [starts[i + 1] - starts[i] for i in range(3)]
        have = min(gaps) if all(g > 0 for g in gaps) else need
        if need > have:
            warn = (f"<p style='color:{T.WARN}'>⚠ Un port are {max(per_port)} pixeli și are nevoie de <b>{need}</b> "
                    f"universuri. În BanlanX pune <b>Uni Count = {need}</b> la fiecare port, iar în LumiBeat "
                    f"universurile de start vor fi setate automat la "
                    f"{', '.join(str(starts[0] + need * i) for i in range(4))}.</p>")
        self._need_universes = need if need > have else None
        self.summary.setText(
            f"<p>Pixeli pe profil: <b>{self.n}</b>  ·  profile identificate: <b>{len(self.assign)} din 12</b></p>"
            f"<table cellspacing=0 cellpadding=5>{''.join(rows)}</table>{warn}")

    def apply(self):
        cfg = self.ctrl.cfg.copy()
        by_profile = {a[0]: (s, a[1]) for s, a in self.assign.items()}
        for i, pr in enumerate(cfg.profiles):
            pr.pixels = self.n
            pr.skip_pixels = 0
            if i in by_profile:
                (p, k), up = by_profile[i]
                pr.port, pr.chain_pos, pr.data_up, pr.enabled = p + 1, k, up, True
            else:
                pr.enabled = False
                pr.chain_pos = 50 + i       # keep it at the end of its chain
        cfg.wall.matrix_rows = int(max(8, min(512, self.n)))
        if self._need_universes:
            base = cfg.ports[0].universe
            for i, pc in enumerate(cfg.ports):
                pc.universe = base + self._need_universes * i
            cfg.network.universes_per_port = self._need_universes
        self.ctrl.apply_config(cfg, restart_audio=False)
        self.go(4)
        self.ctrl.set_test(TestPattern(kind="direction", profile=-1))

    def finish(self):
        self.ctrl.set_test(None)
        self.win.toast("Calibrare salvată – peretele urmează acum simulatorul")
        self.accept()

    def closeEvent(self, e):
        self.ctrl.set_test(None)
        super().closeEvent(e)

    def reject(self):
        self.ctrl.set_test(None)
        super().reject()
