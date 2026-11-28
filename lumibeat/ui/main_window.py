"""Main window: navigation rail, live stage (wall simulator), page panel and master bar."""
from __future__ import annotations

import time

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMainWindow,
                               QMenu, QMessageBox, QScrollArea, QSplitter, QStackedWidget, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

from ..core.config import APP_NAME
from ..effects import REGISTRY, ambient_effect_ids, music_effect_ids
from . import theme as T
from .pages import AmbientPage, MusicPage, PartyMeter, PartyPage, StudioPage
from .setup_pages import HardwarePage, NetworkPage, PhonePage, SettingsPage
from .thumbs import ThumbRenderer
from .wall_view import WallViewSoft, create_wall_view
from .widgets import BigToggleButton, NavButton, Pill, SliderRow, SpectrumBar, Toggle, button, label

STROBE_WARNING = (
    "<b>Avertisment – efecte stroboscopice</b><br><br>"
    "Luminile intermitente rapide pot declanșa crize la persoanele cu <b>epilepsie fotosensibilă</b>, "
    "pot provoca disconfort, dureri de cap și pot speria animalele de companie.<br><br>"
    "Folosește stroboscopul doar dacă toți cei prezenți sunt de acord. "
    "Setarea se dezactivează automat la repornirea aplicației.<br><br>Activezi efectele stroboscopice?")

MODE_NAMES = {"music": "Music", "party": "Party", "ambient": "Ambient", "studio": "Studio"}


class Bridge(QObject):
    event = Signal(str, object)


class Toast(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet(f"background: {T.SURFACE3}; border: 1px solid {T.BORDER2}; border-radius: 12px;"
                           f"padding: 10px 18px; color: {T.TEXT}; font-weight: 600;")
        self.eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.eff)
        self.anim = QPropertyAnimation(self.eff, b"opacity", self)
        self.anim.setDuration(250)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._fade)
        self.hide()

    def show_msg(self, text: str, ms: int = 2200):
        self.setText(text)
        self.adjustSize()
        p = self.parentWidget()
        self.move((p.width() - self.width()) // 2, p.height() - self.height() - 110)
        self.raise_()
        self.show()
        self.anim.stop()
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()
        self.timer.start(ms)

    def _fade(self):
        self.anim.stop()
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.start()
        QTimer.singleShot(260, self.hide)


class MainWindow(QMainWindow):
    def __init__(self, ctrl, icon: QIcon | None = None, software_gl: bool = False):
        super().__init__()
        self.ctrl = ctrl
        self.app_icon = icon or QIcon()
        self.quitting = False
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(self.app_icon)
        self.resize(1560, 940)
        self.setMinimumSize(1180, 720)
        self.bridge = Bridge()
        self.bridge.event.connect(self._on_event)
        ctrl.on(lambda what, data: self.bridge.event.emit(what, data))

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # ---------------- navigation rail
        self.rail = QFrame()
        self.rail.setFixedWidth(88)
        self.rail.setStyleSheet(f"QFrame {{ background: {T.BG2}; border-right: 1px solid {T.BORDER}; }}")
        rl = QVBoxLayout(self.rail)
        rl.setContentsMargins(5, 14, 5, 14)
        rl.setSpacing(4)
        logo = QLabel()
        logo.setPixmap(self.app_icon.pixmap(QSize(46, 46)))
        logo.setAlignment(Qt.AlignCenter)
        rl.addWidget(logo)
        rl.addSpacing(10)
        self.nav_buttons = []
        nav = [("music", "Music"), ("party", "Party"), ("ambient", "Ambient"), ("studio", "Studio"), None,
               ("wall", "Instalație"), ("network", "Rețea"), ("phone", "Telefon"), ("settings", "Setări")]
        idx = 0
        for item in nav:
            if item is None:
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(f"background: {T.BORDER};")
                rl.addSpacing(6)
                rl.addWidget(sep)
                rl.addSpacing(6)
                continue
            b = NavButton(*item)
            b.clicked.connect(lambda _=False, i=idx: self.show_page(i))
            rl.addWidget(b, 0, Qt.AlignHCenter)
            self.nav_buttons.append(b)
            idx += 1
        rl.addStretch(1)
        h.addWidget(self.rail)

        # ---------------- main column
        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(18, 12, 18, 12)
        cl.setSpacing(12)
        h.addWidget(col, 1)

        header = QHBoxLayout()
        tcol = QVBoxLayout()
        tcol.setSpacing(0)
        self.h_title = label("Music", "h1")
        self.h_sub = label("", "muted")
        tcol.addWidget(self.h_title)
        tcol.addWidget(self.h_sub)
        header.addLayout(tcol, 1)
        self.p_mode = Pill("Music", T.A1)
        self.p_audio = Pill("Audio", T.MUTED)
        self.p_bpm = Pill("-- BPM", T.A3)
        self.p_net = Pill("Simulator", T.MUTED)
        self.p_fps = Pill("60 FPS", T.MUTED)
        self.p_power = Pill("0 W", T.WARN)
        for p in (self.p_mode, self.p_audio, self.p_bpm, self.p_net, self.p_fps, self.p_power):
            header.addWidget(p)
        cl.addLayout(header)

        self.split = QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(12)
        cl.addWidget(self.split, 1)

        # stage
        stage = QFrame()
        stage.setProperty("card", "true")
        sl = QVBoxLayout(stage)
        sl.setContentsMargins(10, 10, 10, 10)
        sl.setSpacing(8)
        self.wall = create_wall_view(ctrl.cfg, force_software=software_gl)
        self.wall.glFailed.connect(self._gl_failed)
        sl.addWidget(self.wall, 1)
        self.wall_holder = sl
        info = QHBoxLayout()
        self.now = label("", "h2")
        self.now_sub = label("", "muted")
        info.addWidget(self.now)
        info.addWidget(self.now_sub, 1)
        self.full_btn = button("⛶  Scenă", "ghost", tip="Mod scenă pe tot ecranul (F11 / Esc)")
        self.full_btn.clicked.connect(self.toggle_stage_mode)
        info.addWidget(self.full_btn)
        sl.addLayout(info)
        dash = QHBoxLayout()
        dash.setSpacing(16)
        self.meter = PartyMeter()
        self.meter.setFixedWidth(440)
        self.meter.setMinimumHeight(150)
        dash.addWidget(self.meter)
        self.spectrum = SpectrumBar()
        self.spectrum.setMaximumHeight(190)
        dash.addWidget(self.spectrum, 1)
        sl.addLayout(dash)
        self.stage = stage
        stage.installEventFilter(self)
        self.split.addWidget(stage)

        # pages
        self.stack = QStackedWidget()
        self.pages = [MusicPage(ctrl, self), PartyPage(ctrl, self), AmbientPage(ctrl, self), StudioPage(ctrl, self),
                      HardwarePage(ctrl, self), NetworkPage(ctrl, self), PhonePage(ctrl, self),
                      SettingsPage(ctrl, self)]
        for pg in self.pages:
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setWidget(pg)
            sa.setFrameShape(QFrame.NoFrame)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.stack.addWidget(sa)
        self.stack.setMinimumWidth(470)
        self.split.addWidget(self.stack)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
        self.split.setSizes([900, 560])

        # master bar
        self.master = QFrame()
        self.master.setProperty("card", "true")
        ml = QHBoxLayout(self.master)
        ml.setContentsMargins(14, 10, 16, 10)
        ml.setSpacing(18)
        st = ctrl.state()
        self.led_btn = BigToggleButton("LED", "pornit / oprit", 54)
        self.led_btn.setFixedWidth(130)
        self.led_btn.setChecked(st.led_on)
        self.led_btn.toggled.connect(lambda on: self.ctrl.set_state(led_on=on))
        ml.addWidget(self.led_btn)
        self.s_bri = SliderRow("Luminozitate", 0, 1, st.brightness, fmt=lambda v: f"{v * 100:.0f}%")
        self.s_int = SliderRow("Intensitate", 0, 1.5, st.intensity, fmt=lambda v: f"{v * 100:.0f}%")
        self.s_spd = SliderRow("Viteză", 0.1, 3.0, st.speed, fmt=lambda v: f"{v:.2f}×")
        self.s_sen = SliderRow("Sensibilitate audio", 0.2, 3.0, st.sensitivity, fmt=lambda v: f"{v:.2f}×")
        for s, k in ((self.s_bri, "brightness"), (self.s_int, "intensity"), (self.s_spd, "speed"),
                     (self.s_sen, "sensitivity")):
            s.valueChanged.connect(lambda v, key=k: self.ctrl.set_state(**{key: round(v, 3)}))
            s.setMinimumWidth(150)
            ml.addWidget(s, 1)
        sc = QVBoxLayout()
        sc.setSpacing(2)
        sc.addWidget(label("Stroboscop", "muted"))
        self.strobe = Toggle(False, warn=True)
        self.strobe.toggled.connect(self._strobe)
        sc.addWidget(self.strobe)
        ml.addLayout(sc)
        oc = QVBoxLayout()
        oc.setSpacing(2)
        oc.addWidget(label("Transmisie LED", "muted"))
        self.out_toggle = Toggle(ctrl.cfg.network.output_enabled)
        self.out_toggle.toggled.connect(lambda v: self.ctrl.set_output_enabled(v))
        oc.addWidget(self.out_toggle)
        ml.addLayout(oc)
        cl.addWidget(self.master)

        self.toast_w = Toast(root)
        self._stage_mode = False
        self.cur_page = 0
        self.show_page(0)

        # timers
        self.frame_timer = QTimer(self)
        self.frame_timer.setTimerType(Qt.PreciseTimer)
        self.frame_timer.timeout.connect(self._frame)
        self.frame_timer.start(16)
        self.slow_timer = QTimer(self)
        self.slow_timer.timeout.connect(self._slow)
        self.slow_timer.start(200)
        self._last_beat = 0
        self._beat_pulse = 0.0
        self._last_t = -1.0

        self.thumbs = ThumbRenderer(ctrl.cfg, music_effect_ids() + ambient_effect_ids())
        self.thumbs.ready.connect(self._thumb)
        QTimer.singleShot(400, self.thumbs.start)

        QShortcut(QKeySequence(Qt.Key_F11), self, self.toggle_stage_mode)
        QShortcut(QKeySequence(Qt.Key_Escape), self, lambda: self._stage_mode and self.toggle_stage_mode())
        QShortcut(QKeySequence("Ctrl+B"), self, lambda: self.ctrl.toggle_led())
        self._setup_tray()

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is self.stage and ev.type() == QEvent.Resize:
            QTimer.singleShot(0, self._fit_wall)
        return super().eventFilter(obj, ev)

    def _fit_wall(self):
        img = getattr(self.wall, "bg_img", None)
        if img is None or img.height() == 0:
            return
        aspect = img.width() / img.height()
        avail = self.stage.height() - 20 - 34 - 160
        ideal = int(self.wall.width() / aspect) + 2
        self.wall.setMaximumHeight(max(220, min(avail, ideal)))

    # ------------------------------------------------------------------ pages
    def show_page(self, i: int):
        old = self.pages[self.cur_page]
        if old is not self.pages[i] and hasattr(old, "on_hide"):
            old.on_hide()
        self.cur_page = i
        self.stack.setCurrentIndex(i)
        for k, b in enumerate(self.nav_buttons):
            b.setChecked(k == i)
        pg = self.pages[i]
        self.h_title.setText(pg.title)
        self.h_sub.setText(pg.subtitle)
        self.wall.show_labels = i >= 4
        pg.on_show()

    def toast(self, msg: str):
        self.toast_w.show_msg(msg)

    # ---------------------------------------------------------------- events
    def _on_event(self, what: str, data):
        if what == "state":
            st = self.ctrl.state()
            self.led_btn.blockSignals(True)
            self.led_btn.setChecked(st.led_on)
            self.led_btn.blockSignals(False)
            for s, v in ((self.s_bri, st.brightness), (self.s_int, st.intensity), (self.s_spd, st.speed),
                         (self.s_sen, st.sensitivity)):
                s.setValue(v)
            self.strobe.setCheckedSilent(st.strobe_enabled)
            self._update_tray(st)
            for pg in self.pages:
                pg.on_state(data or {})
        elif what == "config":
            self.wall.set_config(self.ctrl.cfg)
            self._fit_wall()
            self.out_toggle.setCheckedSilent(self.ctrl.cfg.network.output_enabled)
            for pg in self.pages:
                pg.on_config()
        elif what == "presets":
            self.pages[3].refresh_presets()

    def _thumb(self, eid, img):
        self.pages[0].set_thumb(eid, img)
        self.pages[2].set_thumb(eid, img)

    def _strobe(self, on: bool):
        if on:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Efecte stroboscopice")
            box.setText(STROBE_WARNING)
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            box.setDefaultButton(QMessageBox.No)
            box.button(QMessageBox.Yes).setText("Da, activez")
            box.button(QMessageBox.No).setText("Nu")
            if box.exec() != QMessageBox.Yes:
                self.strobe.setCheckedSilent(False)
                return
        self.ctrl.set_strobe(on)

    def _gl_failed(self, msg: str):
        # replace the GPU view by the software renderer
        old = self.wall
        self.wall = WallViewSoft(self.ctrl.cfg)
        self.wall.glFailed.connect(self._gl_failed)
        idx = self.wall_holder.indexOf(old)
        self.wall_holder.insertWidget(idx, self.wall, 1)
        old.hide()
        old.deleteLater()
        hp = self.pages[4]
        self.wall.profileClicked.connect(hp.select)
        self.wall.viewsEdited.connect(hp._views_edited)
        self.toast("OpenGL indisponibil – simulatorul folosește randarea software")

    # ---------------------------------------------------------------- frames
    def _frame(self):
        if not self.isVisible() or self.isMinimized():
            return
        fo = self.ctrl.engine.latest
        if fo.t == self._last_t:
            return
        self._last_t = fo.t
        self.wall.overlay_text = (fo.effect_name.upper() if fo.effect == "scan" else "TEST CALIBRARE ACTIV") \
            if fo.test else ""
        self.wall.set_frame(fo.preview, fo.t)
        a = fo.audio
        if a.beat_count != self._last_beat:
            self._last_beat = a.beat_count
            self._beat_pulse = 1.0
        self._beat_pulse *= 0.85
        self.spectrum.set_data(a.bands, a.bands_peak, self._beat_pulse, a.level)
        self.meter.update_from(fo)
        self.p_bpm.pulse = self._beat_pulse
        self.p_bpm.update()

    def _slow(self):
        if not self.isVisible():
            return
        fo = self.ctrl.engine.latest
        st = self.ctrl.state()
        a = fo.audio
        self.p_mode.set(MODE_NAMES.get(st.mode, st.mode) + ("" if st.led_on else " · LED oprit"),
                        T.A1 if st.led_on else T.DIM)
        ci = self.ctrl.capture.info()
        src = {"loopback": "Sistem (Loopback)", "mic": "Microfon", "demo": "Demo", "none": "Fără audio"}.get(ci["source"], ci["source"])
        self.p_audio.set(f"{src} · {a.level * 100:.0f}%" if ci["source"] != "none" else "Audio indisponibil",
                         T.OK if ci["source"] != "none" and not a.silent else (T.DANGER if ci["source"] == "none" else T.MUTED))
        self.p_bpm.set(f"{a.bpm:.0f} BPM" if a.bpm > 0 and not a.silent else "-- BPM")
        s = self.ctrl.artnet.stats()
        if not self.ctrl.cfg.network.output_enabled:
            self.p_net.set("Simulator", T.MUTED)
        else:
            col = {"online": T.OK, "sending": T.A2, "lost": T.WARN, "error": T.DANGER}.get(s["status"], T.MUTED)
            self.p_net.set(f"Art-Net {s['fps']:.0f} FPS", col)
        self.p_fps.set(f"{self.ctrl.engine.fps:.0f} FPS", T.MUTED)
        self.p_power.set(f"{fo.power_w:.0f} W", T.WARN if fo.power_scale < 0.999 else T.MUTED)
        name = fo.effect_name
        self.now.setText(name)
        sub = []
        if st.mode == "party":
            sub += [fo.style, fo.section]
        if fo.standby:
            sub.append("standby ambiental")
        if fo.safety_limited:
            sub.append("protecție anti-flash activă")
        if self.ctrl.engine.error:
            sub.append("eroare: " + self.ctrl.engine.error)
        self.now_sub.setText("   ·   ".join(x for x in sub if x))
        self.pages[self.cur_page].tick(fo)

    # ------------------------------------------------------------ stage mode
    def toggle_stage_mode(self):
        self._stage_mode = not self._stage_mode
        for w in (self.rail, self.stack, self.master):
            w.setVisible(not self._stage_mode)
        self.h_title.setVisible(not self._stage_mode)
        self.h_sub.setVisible(not self._stage_mode)
        if self._stage_mode:
            self.showFullScreen()
        else:
            self.showNormal()

    # ------------------------------------------------------------------ tray
    def _setup_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self.app_icon, self)
        self.tray.setToolTip(APP_NAME)
        m = QMenu()
        a_show = QAction("Deschide LumiBeat Studio", m)
        a_show.triggered.connect(self.bring_to_front)
        self.a_led = QAction("LED pornite", m, checkable=True)
        self.a_led.triggered.connect(lambda on: self.ctrl.set_state(led_on=on))
        a_party = QAction("Party · Auto DJ", m)
        a_party.triggered.connect(lambda: self.ctrl.set_state(mode="party", party_preset="auto_dj"))
        a_amb = QAction("Ambient · Fireplace", m)
        a_amb.triggered.connect(lambda: self.ctrl.set_state(mode="ambient", ambient_scene="amb_fireplace"))
        a_music = QAction("Music", m)
        a_music.triggered.connect(lambda: self.ctrl.set_state(mode="music"))
        a_quit = QAction("Ieșire", m)
        a_quit.triggered.connect(self.quit_app)
        for a in (a_show, None, self.a_led, a_music, a_party, a_amb, None, a_quit):
            if a is None:
                m.addSeparator()
            else:
                m.addAction(a)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.bring_to_front() if r in (QSystemTrayIcon.Trigger,
                                                                              QSystemTrayIcon.DoubleClick) else None)
        self._update_tray(self.ctrl.state())
        self.tray.show()

    def _update_tray(self, st):
        if self.tray:
            self.a_led.setChecked(st.led_on)

    def bring_to_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        self.quitting = True
        self.close()
        QApplication.quit()

    def closeEvent(self, e):
        if not self.quitting and self.ctrl.cfg.app.close_to_tray and self.tray is not None:
            e.ignore()
            self.hide()
            if not getattr(self, "_tray_hint", False):
                self._tray_hint = True
                self.tray.showMessage(APP_NAME, "Aplicația rulează în continuare în zona de notificare. "
                                      "Folosește «Ieșire» din meniul iconiței pentru a o închide.",
                                      self.app_icon, 4000)
            return
        self.quitting = True
        e.accept()
        QApplication.quit()

    def showEvent(self, e):
        super().showEvent(e)
        T.dark_titlebar(self)
