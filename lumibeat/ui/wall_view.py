"""Live simulator of the wall: 12 aluminium profiles + fireplace, GPU rendered.

* OpenGL (GLSL 1.20) fragment shader: diffuser, aluminium channel, light spill on the
  wall (3 blur levels), animated fireplace, optional real photo of the wall.
* Edit mode: drag the profiles over the photo (endpoints or whole profile, Shift keeps
  them vertical).
* Software (QPainter) fallback if OpenGL is unavailable.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import QWidget
from scipy.ndimage import gaussian_filter1d

from ..core.config import Config
from ..core.geometry import fireplace_rect, profile_view
from . import theme as T

try:
    from OpenGL import GL
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
    HAVE_GL = True
except Exception:  # pragma: no cover
    HAVE_GL = False
    QOpenGLWidget = QWidget  # type: ignore


# ------------------------------------------------------------------ background image
def make_wall_image(cfg: Config, width: int = 2400) -> QImage:
    w = cfg.wall
    aspect = w.wall_width_cm / w.wall_height_cm
    W = width
    H = int(width / aspect)
    img = QImage(W, H, QImage.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, 0, H)
    g.setColorAt(0, QColor(46, 46, 52))
    g.setColorAt(1, QColor(30, 30, 35))
    p.fillRect(0, 0, W, H, g)
    # plaster texture
    rng = np.random.default_rng(3)
    noise = (rng.random((H // 4, W // 4)) * 14).astype(np.uint8)
    tex = QImage(noise.tobytes(), W // 4, H // 4, W // 4, QImage.Format_Grayscale8).copy()
    p.setOpacity(0.10)
    p.drawImage(QRectF(0, 0, W, H), tex)
    p.setOpacity(1.0)
    # ceiling shadow + floor bounce
    sh = QLinearGradient(0, 0, 0, H * 0.25)
    sh.setColorAt(0, QColor(0, 0, 0, 90))
    sh.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(0, 0, W, int(H * 0.25), sh)
    # baseboard + floor line
    bb = H * 0.97
    p.fillRect(QRectF(0, bb, W, H - bb), QColor(58, 56, 60))
    p.fillRect(QRectF(0, bb, W, 2), QColor(90, 88, 94))
    # fireplace: stone surround + black glass firebox
    fx, fy, fw, fh = fireplace_rect(cfg)
    sx0, sy0, sw, shh = (fx - fw * 0.08) * W, (fy - fh * 0.25) * H, fw * 1.16 * W, (1 - fy + fh * 0.25) * H
    surround = QLinearGradient(0, sy0, 0, H)
    surround.setColorAt(0, QColor(70, 68, 70))
    surround.setColorAt(1, QColor(52, 50, 54))
    p.fillRect(QRectF(sx0, sy0, sw, H * 0.97 - sy0), surround)
    p.fillRect(QRectF(sx0 - W * 0.01, sy0 - H * 0.02, sw + W * 0.02, H * 0.022), QColor(96, 94, 98))
    p.fillRect(QRectF(sx0 - W * 0.01, sy0 - H * 0.02 + H * 0.022, sw + W * 0.02, 3), QColor(20, 20, 24))
    box = QRectF(fx * W, fy * H, fw * W, fh * H)
    p.fillRect(box.adjusted(-6, -6, 6, 6), QColor(14, 14, 16))
    bg = QLinearGradient(0, box.top(), 0, box.bottom())
    bg.setColorAt(0, QColor(8, 8, 10))
    bg.setColorAt(1, QColor(26, 16, 12))
    p.fillRect(box, bg)
    p.end()
    return img


def load_photo(path: str, max_w: int = 2560) -> QImage | None:
    if not path or not Path(path).exists():
        return None
    img = QImage(path)
    if img.isNull():
        return None
    if img.width() > max_w:
        img = img.scaledToWidth(max_w, Qt.SmoothTransformation)
    return img.convertToFormat(QImage.Format_RGB32)


VERT = """
#version 120
attribute vec2 pos;
varying vec2 vuv;
void main() { vuv = pos * 0.5 + 0.5; gl_Position = vec4(pos, 0.0, 1.0); }
"""

FRAG = """
#version 120
varying vec2 vuv;
uniform sampler2D bgTex;
uniform sampler2D ledTex;
uniform vec4 imgRect;
uniform vec4 seg[12];
uniform float rows;
uniform float aspect;
uniform float halfW;
uniform float bgLevel;
uniform float glowGain;
uniform vec4 fireRect;
uniform float fireOn;
uniform float time;

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float vnoise(vec2 p) {
  vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);
  float a = hash(i), b = hash(i + vec2(1.0, 0.0)), c = hash(i + vec2(0.0, 1.0)), d = hash(i + vec2(1.0, 1.0));
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}
vec3 led(float i, float level, float t) {
  float x = (i * 4.0 + level + 0.5) / 48.0;
  float y = (clamp(t, 0.0, 1.0) * (rows - 1.0) + 0.5) / rows;
  vec3 c = texture2D(ledTex, vec2(x, y)).rgb;
  return c * c;
}
void main() {
  vec2 p = (vuv - imgRect.xy) / imgRect.zw;
  if (p.x < 0.0 || p.x > 1.0 || p.y < 0.0 || p.y > 1.0) { gl_FragColor = vec4(0.018, 0.02, 0.03, 1.0); return; }
  vec3 bg = texture2D(bgTex, vec2(p.x, 1.0 - p.y)).rgb;
  bg = pow(bg, vec3(2.2));
  vec3 glow = vec3(0.0);
  vec3 direct = vec3(0.0);
  float alu = 0.0;
  float diff = 0.0;
  vec2 asp = vec2(aspect, 1.0);
  float px = 1.5 / (imgRect.w * 900.0);
  for (int k = 0; k < 12; k++) {
    float i = float(k);
    vec2 a = seg[k].xy;
    vec2 b = seg[k].zw;
    vec2 pa = (p - a) * asp;
    vec2 ba = (b - a) * asp;
    float L2 = max(dot(ba, ba), 1e-6);
    float t = dot(pa, ba) / L2;
    float tc = clamp(t, 0.0, 1.0);
    float d = length(pa - ba * tc);
    float endcap = (t < 0.0 || t > 1.0) ? 1.0 : 0.0;
    float inDiff = (1.0 - smoothstep(halfW * 0.62 - px, halfW * 0.62 + px, d)) * (1.0 - endcap);
    float inAlu = (1.0 - smoothstep(halfW - px, halfW + px, d)) * (1.0 - step(0.012, abs(t - tc) * sqrt(L2)));
    vec3 c0 = led(i, 0.0, t);
    direct += c0 * inDiff * 1.35;
    diff = max(diff, inDiff);
    alu = max(alu, inAlu);
    float s1 = halfW * 2.2;
    float g1 = exp(-d * d / (2.0 * s1 * s1));
    float g2 = exp(-d * d / (2.0 * 0.035 * 0.035));
    float g3 = exp(-d * d / (2.0 * 0.12 * 0.12));
    glow += led(i, 1.0, t) * g1 * 0.55 + led(i, 2.0, t) * g2 * 0.42 + led(i, 3.0, t) * g3 * 0.30;
  }
  // animated fireplace (only for the generated wall, not for a photo)
  vec3 fire = vec3(0.0);
  if (fireOn > 0.5) {
    vec2 q = (p - fireRect.xy) / fireRect.zw;
    if (q.x > 0.0 && q.x < 1.0 && q.y > 0.0 && q.y < 1.0) {
      float n = vnoise(vec2(q.x * 9.0, q.y * 3.0 - time * 1.8)) * 0.6 + vnoise(vec2(q.x * 23.0, q.y * 6.0 - time * 3.1)) * 0.4;
      float shape = (1.0 - q.y * 2.1) + (n - 0.5) * 0.9 + 0.15 * sin(q.x * 31.0 + time);
      float h = clamp(shape, 0.0, 1.0);
      fire = mix(vec3(0.0), vec3(1.0, 0.25, 0.02), smoothstep(0.05, 0.5, h));
      fire = mix(fire, vec3(1.0, 0.75, 0.3), smoothstep(0.5, 0.95, h));
      float bed = smoothstep(0.18, 0.0, q.y) * (0.5 + 0.5 * vnoise(vec2(q.x * 40.0, time * 2.0)));
      fire += vec3(1.0, 0.3, 0.05) * bed * 0.6;
      fire *= 0.7;
    }
    vec2 fc = fireRect.xy + fireRect.zw * vec2(0.5, 0.3);
    vec2 dv = (p - fc) * asp;
    float fl = 0.85 + 0.15 * vnoise(vec2(time * 3.0, 1.0));
    glow += vec3(1.0, 0.45, 0.12) * exp(-dot(dv, dv) / (2.0 * 0.06)) * 0.05 * fl;
  }
  vec3 diffOff = vec3(0.10, 0.10, 0.11);
  vec3 aluCol = vec3(0.42, 0.43, 0.46) * (0.35 + 1.4 * glow);
  vec3 col = bg * (bgLevel + glow * glowGain) + glow * 0.18 + fire;
  col = mix(col, aluCol, alu * (1.0 - diff));
  col = mix(col, diffOff + direct + glow * 0.3, diff);
  col = col / (1.0 + col * 0.12);
  gl_FragColor = vec4(pow(col, vec3(1.0 / 2.2)), 1.0);
}
"""


class WallMixin:
    """Geometry, editing and overlay logic shared by the GL and software views."""

    def _init_common(self, cfg: Config):
        self.cfg = cfg
        self.frame = np.zeros((12, cfg.wall.matrix_rows, 3), np.float32)
        self.edit_mode = False
        self.show_labels = False
        self.show_ports = False
        self.selected = -1
        self._drag = None
        self.photo: QImage | None = None
        self.bg_img: QImage | None = None
        self._bg_dirty = True
        self.t0 = 0.0
        self.time = 0.0
        self.overlay_text = ""
        self.setMouseTracking(True)
        self.setMinimumSize(420, 220)
        self.views = [profile_view(cfg, i) for i in range(12)]
        self.reload_background()

    # ---- config / data
    def set_config(self, cfg: Config):
        self.cfg = cfg
        self.views = [profile_view(cfg, i) for i in range(12)]
        self.reload_background()
        self.update()

    def reload_background(self):
        self.photo = load_photo(self.cfg.wall.photo_path)
        self.bg_img = self.photo if self.photo is not None else make_wall_image(self.cfg)
        self._bg_dirty = True

    def set_frame(self, frame: np.ndarray, t: float = 0.0):
        self.frame = frame
        self.time = t
        self.update()

    # ---- coordinates
    def image_rect(self) -> QRectF:
        W, H = self.width(), self.height()
        if not self.bg_img:
            return QRectF(0, 0, W, H)
        ia = self.bg_img.width() / max(1, self.bg_img.height())
        if W / max(1, H) > ia:
            h = H
            w = h * ia
        else:
            w = W
            h = w / ia
        return QRectF((W - w) / 2, (H - h) / 2, w, h)

    def to_widget(self, x: float, y: float) -> QPointF:
        r = self.image_rect()
        return QPointF(r.left() + x * r.width(), r.top() + y * r.height())

    def to_image(self, pt: QPointF) -> tuple[float, float]:
        r = self.image_rect()
        return ((pt.x() - r.left()) / max(1, r.width()), (pt.y() - r.top()) / max(1, r.height()))

    def profile_half_width(self) -> float:
        """Half width of a profile in image-height units (aluminium channel ≈ 2.4 cm)."""
        return max(0.004, 1.2 / self.cfg.wall.wall_height_cm * (1.0 if self.photo is None else 1.3))

    # ---- editing
    def mousePressEvent(self, e):
        pos = e.position()
        hit = self._hit(pos)
        if self.edit_mode and hit:
            idx, part = hit
            self.selected = idx
            self._drag = (idx, part, pos, list(self.views[idx]))
            self.update()
            return
        if hit:
            self.selected = hit[0]
            self.profileClicked.emit(hit[0])
            self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag:
            idx, part, start, orig = self._drag
            r = self.image_rect()
            dx = (pos.x() - start.x()) / max(1, r.width())
            dy = (pos.y() - start.y()) / max(1, r.height())
            v = list(orig)
            if part in ("bottom", "line"):
                v[0] += dx
                v[1] += dy
            if part in ("top", "line"):
                v[2] += dx
                v[3] += dy
            if e.modifiers() & Qt.ShiftModifier:
                if part == "bottom":
                    v[0] = v[2]
                elif part == "top":
                    v[2] = v[0]
            self.views[idx] = [min(1.2, max(-0.2, c)) for c in v]
            self.update()
            return
        hit = self._hit(pos)
        if self.edit_mode:
            self.setCursor(Qt.SizeAllCursor if hit and hit[1] == "line" else
                           Qt.CrossCursor if hit else Qt.ArrowCursor)
        else:
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = None
            self.viewsEdited.emit([list(v) for v in self.views])

    def _hit(self, pos: QPointF):
        best = None
        bd = 1e9
        for i, v in enumerate(self.views):
            b = self.to_widget(v[0], v[1])
            t = self.to_widget(v[2], v[3])
            for part, pt in (("bottom", b), ("top", t)):
                d = math.hypot(pt.x() - pos.x(), pt.y() - pos.y())
                if d < 12 and d < bd:
                    best, bd = (i, part), d
            # distance to the segment
            ax, ay, bx, by = b.x(), b.y(), t.x(), t.y()
            vx, vy = bx - ax, by - ay
            L2 = max(1e-6, vx * vx + vy * vy)
            tt = max(0.0, min(1.0, ((pos.x() - ax) * vx + (pos.y() - ay) * vy) / L2))
            d = math.hypot(ax + vx * tt - pos.x(), ay + vy * tt - pos.y())
            if d < 9 and d + 4 < bd:
                best, bd = (i, "line"), d + 4
        return best

    # ---- overlay
    def paint_overlay(self, p: QPainter):
        p.setRenderHint(QPainter.Antialiasing)
        if self.edit_mode or self.show_labels or self.show_ports or self.selected >= 0:
            f = QFont(p.font())
            f.setPointSizeF(8.5)
            f.setBold(True)
            p.setFont(f)
            for i, v in enumerate(self.views):
                b = self.to_widget(v[0], v[1])
                t = self.to_widget(v[2], v[3])
                port = self.cfg.profiles[i].port
                col = QColor(T.PORT_COLORS[(port - 1) % 4]) if self.show_ports else QColor(T.A2)
                if self.edit_mode or i == self.selected:
                    pen = QPen(col if i != self.selected else QColor("#ffffff"), 1.4, Qt.DashLine)
                    p.setPen(pen)
                    p.drawLine(b, t)
                if self.edit_mode:
                    p.setPen(QPen(QColor(0, 0, 0, 160), 1))
                    for pt in (b, t):
                        p.setBrush(col if i != self.selected else QColor("#ffffff"))
                        p.drawEllipse(pt, 5.5, 5.5)
                if self.edit_mode or self.show_labels or self.show_ports:
                    tag = f"{i + 1}" + (f" · P{port}" if self.show_ports else "")
                    fm = p.fontMetrics()
                    tw = fm.horizontalAdvance(tag) + 10
                    rr = QRectF(t.x() - tw / 2, t.y() - 24, tw, 17)
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(10, 12, 20, 200))
                    p.drawRoundedRect(rr, 8, 8)
                    p.setPen(col)
                    p.drawText(rr, Qt.AlignCenter, tag)
                    if self.show_ports:
                        up = self.cfg.profiles[i].data_up
                        arrow = "↑" if up else "↓"
                        rr2 = QRectF(b.x() - 9, b.y() + 4, 18, 16)
                        p.setPen(col)
                        p.drawText(rr2, Qt.AlignCenter, arrow)
        if self.overlay_text:
            f = QFont(p.font())
            f.setPointSizeF(8)
            f.setBold(True)
            p.setFont(f)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(self.overlay_text) + 18
            rr = QRectF(12, 12, tw, 22)
            p.setPen(QPen(QColor(255, 255, 255, 30), 1))
            p.setBrush(QColor(10, 12, 20, 170))
            p.drawRoundedRect(rr, 11, 11)
            p.setPen(QColor(T.TEXT))
            p.drawText(rr, Qt.AlignCenter, self.overlay_text)

    def led_texture(self) -> np.ndarray:
        """(rows, 48, 3) uint8: per profile 4 columns = sharp + 3 vertical blur levels, sqrt-encoded."""
        f = np.clip(self.frame, 0, 1.5).astype(np.float32)
        rows = f.shape[1]
        l1 = gaussian_filter1d(f, sigma=max(0.8, rows * 0.012), axis=1, mode="constant")
        l2 = gaussian_filter1d(f, sigma=max(1.5, rows * 0.05), axis=1, mode="constant")
        l3 = gaussian_filter1d(f, sigma=max(3.0, rows * 0.16), axis=1, mode="constant")
        stack = np.stack([f, l1, l2, l3], axis=1)          # (12, 4, rows, 3)
        tex = stack.reshape(48, rows, 3).transpose(1, 0, 2)  # (rows, 48, 3)
        return (np.sqrt(np.clip(tex, 0, 1)) * 255 + 0.5).astype(np.uint8)


class WallViewGL(WallMixin, QOpenGLWidget):
    profileClicked = Signal(int)
    viewsEdited = Signal(list)
    glFailed = Signal(str)

    def __init__(self, cfg: Config, parent=None):
        QOpenGLWidget.__init__(self, parent)
        self._init_common(cfg)
        self.prog = None
        self.ok = True

    def initializeGL(self):
        try:
            self.prog = self._compile()
            self.tex_bg = GL.glGenTextures(1)
            self.tex_led = GL.glGenTextures(1)
            for tex in (self.tex_bg, self.tex_led):
                GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            self.quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], np.float32)
            self._bg_dirty = True
        except Exception as e:  # pragma: no cover - driver specific
            self.ok = False
            self.glFailed.emit(str(e))

    def _compile(self):
        def shader(src, kind):
            s = GL.glCreateShader(kind)
            GL.glShaderSource(s, src)
            GL.glCompileShader(s)
            if not GL.glGetShaderiv(s, GL.GL_COMPILE_STATUS):
                raise RuntimeError(GL.glGetShaderInfoLog(s).decode(errors="replace"))
            return s

        prog = GL.glCreateProgram()
        GL.glAttachShader(prog, shader(VERT, GL.GL_VERTEX_SHADER))
        GL.glAttachShader(prog, shader(FRAG, GL.GL_FRAGMENT_SHADER))
        GL.glBindAttribLocation(prog, 0, "pos")
        GL.glLinkProgram(prog)
        if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
            raise RuntimeError(GL.glGetProgramInfoLog(prog).decode(errors="replace"))
        self.loc = {n: GL.glGetUniformLocation(prog, n) for n in (
            "bgTex", "ledTex", "imgRect", "seg", "rows", "aspect", "halfW", "bgLevel", "glowGain",
            "fireRect", "fireOn", "time")}
        return prog

    def _upload_bg(self):
        img = self.bg_img.convertToFormat(QImage.Format_RGBA8888)
        ptr = img.constBits()
        data = bytes(ptr)[: img.width() * img.height() * 4]
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex_bg)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, img.width(), img.height(), 0, GL.GL_RGBA,
                        GL.GL_UNSIGNED_BYTE, data)
        self._bg_dirty = False

    def paintGL(self):
        p = QPainter(self)
        if self.ok and self.prog:
            p.beginNativePainting()
            try:
                self._draw_gl()
            except Exception as e:  # pragma: no cover
                self.ok = False
                self.glFailed.emit(str(e))
            finally:
                GL.glUseProgram(0)
                GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
                GL.glActiveTexture(GL.GL_TEXTURE0)
                p.endNativePainting()
        self.paint_overlay(p)
        p.end()

    def _draw_gl(self):
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_BLEND)
        if self._bg_dirty:
            self._upload_bg()
        tex = self.led_texture()
        rows = tex.shape[0]
        GL.glActiveTexture(GL.GL_TEXTURE1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex_led)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, 48, rows, 0, GL.GL_RGB, GL.GL_UNSIGNED_BYTE,
                        np.ascontiguousarray(tex))
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex_bg)
        GL.glUseProgram(self.prog)
        L = self.loc
        GL.glUniform1i(L["bgTex"], 0)
        GL.glUniform1i(L["ledTex"], 1)
        r = self.image_rect()
        W, H = max(1, self.width()), max(1, self.height())
        # widget uv (y up)
        GL.glUniform4f(L["imgRect"], r.left() / W, 1 - r.bottom() / H, r.width() / W, r.height() / H)
        segs = []
        for v in self.views:
            segs += [v[0], 1 - v[1], v[2], 1 - v[3]]
        GL.glUniform4fv(L["seg"], 12, np.array(segs, np.float32))
        GL.glUniform1f(L["rows"], float(rows))
        GL.glUniform1f(L["aspect"], self.bg_img.width() / max(1, self.bg_img.height()))
        GL.glUniform1f(L["halfW"], self.profile_half_width())
        has_photo = self.photo is not None
        GL.glUniform1f(L["bgLevel"], self.cfg.wall.photo_brightness if has_photo else 0.55)
        GL.glUniform1f(L["glowGain"], 2.6 if has_photo else 3.2)
        fx, fy, fw, fh = fireplace_rect(self.cfg)
        GL.glUniform4f(L["fireRect"], fx, 1 - (fy + fh), fw, fh)
        GL.glUniform1f(L["fireOn"], 0.0 if has_photo or not self.cfg.app.show_fireplace_flame else 1.0)
        GL.glUniform1f(L["time"], float(self.time))
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 0, self.quad)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glDisableVertexAttribArray(0)

    def reload_background(self):
        WallMixin.reload_background(self)
        self.update()


class WallViewSoft(WallMixin, QWidget):
    """QPainter fallback (no GPU)."""

    profileClicked = Signal(int)
    viewsEdited = Signal(list)
    glFailed = Signal(str)

    def __init__(self, cfg: Config, parent=None):
        QWidget.__init__(self, parent)
        self._init_common(cfg)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#050608"))
        r = self.image_rect()
        p.setOpacity(0.55)
        p.drawImage(r, self.bg_img)
        p.setOpacity(1.0)
        p.setRenderHint(QPainter.Antialiasing)
        f = np.clip(self.frame, 0, 1) ** (1 / 2.2)
        rows = f.shape[1]
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        seg = max(1, rows // 40)
        for i, v in enumerate(self.views):
            b = self.to_widget(v[0], v[1])
            t = self.to_widget(v[2], v[3])
            for r0 in range(0, rows, seg):
                c = f[i, r0:r0 + seg].mean(axis=0)
                if c.sum() < 0.02:
                    continue
                k0 = r0 / rows
                k1 = (r0 + seg) / rows
                p0 = QPointF(b.x() + (t.x() - b.x()) * k0, b.y() + (t.y() - b.y()) * k0)
                p1 = QPointF(b.x() + (t.x() - b.x()) * k1, b.y() + (t.y() - b.y()) * k1)
                qc = QColor.fromRgbF(*c)
                g = QColor(qc)
                g.setAlphaF(0.12)
                p.setPen(QPen(g, r.width() * 0.04, Qt.SolidLine, Qt.FlatCap))
                p.drawLine(p0, p1)
                p.setPen(QPen(qc, max(2.0, r.width() * 0.004), Qt.SolidLine, Qt.FlatCap))
                p.drawLine(p0, p1)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        self.paint_overlay(p)


def create_wall_view(cfg: Config, force_software: bool = False):
    if HAVE_GL and not force_software:
        return WallViewGL(cfg)
    return WallViewSoft(cfg)
