"""Audio capture backends.

* ``loopback`` – WASAPI loopback of the default (or chosen) Windows playback device,
  i.e. whatever Spotify, YouTube, VLC, a browser or any app is playing.
  Implemented with PyAudioWPatch (PortAudio fork with WASAPI loopback, MIT licence).
* ``mic``      – microphone / line-in (WASAPI shared mode on Windows,
  sounddevice/PortAudio elsewhere).
* ``demo``     – built-in procedural track, for the simulator without music.

The capture callback only queues raw blocks; a dedicated processing thread runs
the analyser.  WASAPI loopback delivers *no* packets while nothing is playing,
so the processing thread feeds silence on timeout - analysis, standby and the
LED output never stall.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Callable

import numpy as np

from .analysis import AudioAnalyzer
from .demo import DemoSynth

try:  # Windows: WASAPI loopback capable PortAudio fork
    import pyaudiowpatch as pyaudio  # type: ignore
    HAVE_PAW = True
except Exception:  # pragma: no cover - not available on Linux CI
    pyaudio = None
    HAVE_PAW = False

try:
    import sounddevice as sd  # type: ignore
    HAVE_SD = True
except Exception:
    sd = None
    HAVE_SD = False


def list_devices() -> dict[str, list[str]]:
    """Names of usable loopback (playback) and input devices."""
    res: dict[str, list[str]] = {"loopback": [], "mic": []}
    if HAVE_PAW:
        p = pyaudio.PyAudio()
        try:
            try:
                wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                wasapi_idx = wasapi["index"]
            except OSError:
                wasapi_idx = None
            for i in range(p.get_device_count()):
                d = p.get_device_info_by_index(i)
                if wasapi_idx is not None and d.get("hostApi") != wasapi_idx:
                    continue
                if d.get("isLoopbackDevice"):
                    res["loopback"].append(d["name"])
                elif d.get("maxInputChannels", 0) > 0:
                    res["mic"].append(d["name"])
        finally:
            p.terminate()
    elif HAVE_SD:
        try:
            for d in sd.query_devices():
                if d.get("max_input_channels", 0) > 0:
                    res["mic"].append(d["name"])
        except Exception:
            pass
    return res


class AudioCapture:
    def __init__(self, analyzer: AudioAnalyzer, on_status: Callable[[str], None] | None = None):
        self.analyzer = analyzer
        self.on_status = on_status
        self.source = "none"
        self.device_name = ""
        self.status = "oprit"
        self.error = ""
        self.sample_rate = 48000
        self.channels = 2
        self._q: queue.Queue = queue.Queue(maxsize=64)
        self._stop = threading.Event()
        self._proc: threading.Thread | None = None
        self._feeder: threading.Thread | None = None
        self._pa = None
        self._stream = None
        self._sd_stream = None
        self._lock = threading.Lock()
        self._want: tuple[str, str] = ("none", "")
        self._watch_default = ""
        self.block = 512
        self.overruns = 0
        self._last_packet = time.monotonic()
        self._last_restart = time.monotonic()

    # ------------------------------------------------------------------ public
    def start(self, source: str, device: str = "", block: int = 512) -> None:
        with self._lock:
            self._shutdown_locked()
            self._want = (source, device)
            self.block = int(block)
            self._stop.clear()
            self.error = ""
            ok = False
            try:
                if source == "loopback":
                    ok = self._open_loopback(device)
                elif source == "mic":
                    ok = self._open_mic(device)
                elif source == "demo":
                    ok = self._open_demo()
            except Exception as e:  # pragma: no cover - device specific
                self.error = str(e)
                ok = False
            if not ok and source != "demo":
                self.status = "eroare"
                if not self.error:
                    self.error = "Sursa audio nu este disponibilă."
            self.source = source if ok else "none"
            self.analyzer.reset(self.sample_rate, self.block)
            self._proc = threading.Thread(target=self._process_loop, name="audio-proc", daemon=True)
            self._proc.start()
        self._notify()

    def stop(self) -> None:
        with self._lock:
            self._shutdown_locked()
            self.status = "oprit"
        self._notify()

    def restart(self) -> None:
        self.start(*self._want, block=self.block)

    def info(self) -> dict:
        return {
            "source": self.source,
            "device": self.device_name,
            "status": self.status,
            "error": self.error,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
        }

    # --------------------------------------------------------------- backends
    def _open_loopback(self, device: str) -> bool:
        if not HAVE_PAW:
            self.error = "Captura WASAPI Loopback este disponibilă doar pe Windows (PyAudioWPatch)."
            return False
        self._pa = pyaudio.PyAudio()
        info = None
        if device:
            for lb in self._pa.get_loopback_device_info_generator():
                if lb["name"] == device or device in lb["name"]:
                    info = lb
                    break
        if info is None:
            try:
                info = self._pa.get_default_wasapi_loopback()
            except Exception:
                info = None
        if info is None:
            wasapi = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            spk = self._pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
            for lb in self._pa.get_loopback_device_info_generator():
                if spk["name"] in lb["name"]:
                    info = lb
                    break
        if info is None:
            self.error = "Nu am găsit niciun dispozitiv de redare pentru loopback."
            return False
        self._watch_default = "" if device else (self._default_output_name() or "default")
        return self._open_pa_stream(info, loopback=True)

    def _open_mic(self, device: str) -> bool:
        if HAVE_PAW:
            self._pa = pyaudio.PyAudio()
            info = None
            try:
                wasapi = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
                idx = wasapi["index"]
            except OSError:
                idx = None
            for i in range(self._pa.get_device_count()):
                d = self._pa.get_device_info_by_index(i)
                if d.get("isLoopbackDevice") or d.get("maxInputChannels", 0) <= 0:
                    continue
                if idx is not None and d.get("hostApi") != idx:
                    continue
                if not device or d["name"] == device:
                    info = d
                    if device:
                        break
                    # prefer the Windows default input
                    if idx is not None and i == wasapi.get("defaultInputDevice"):
                        break
            if info is None:
                self.error = "Nu am găsit niciun microfon / intrare audio."
                return False
            return self._open_pa_stream(info, loopback=False)
        if HAVE_SD:
            dev = device or None
            info = sd.query_devices(dev, "input")
            self.sample_rate = int(info["default_samplerate"])
            self.channels = min(2, int(info["max_input_channels"]))
            self.device_name = info["name"]

            def cb(indata, frames, t, status):  # pragma: no cover - hardware
                self._push(indata.copy())

            self._sd_stream = sd.InputStream(device=dev, channels=self.channels, samplerate=self.sample_rate,
                                             blocksize=self.block, dtype="float32", callback=cb, latency="low")
            self._sd_stream.start()
            self.status = "activ"
            return True
        self.error = "Nicio bibliotecă de captură audio disponibilă."
        return False

    def _open_pa_stream(self, info: dict, loopback: bool) -> bool:
        self.sample_rate = int(info["defaultSampleRate"])
        self.channels = max(1, min(2, int(info["maxInputChannels"])))
        self.device_name = info["name"]
        ch = int(info["maxInputChannels"])

        def cb(in_data, frame_count, time_info, status):  # pragma: no cover - hardware
            a = np.frombuffer(in_data, dtype=np.float32)
            if ch > 0:
                a = a.reshape(-1, ch)[:, :2]
            self._push(a)
            return (None, pyaudio.paContinue)

        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=ch,
            rate=self.sample_rate,
            input=True,
            input_device_index=info["index"],
            frames_per_buffer=self.block,
            stream_callback=cb,
        )
        self._stream.start_stream()
        self.status = "activ"
        return True

    def _open_demo(self) -> bool:
        self.sample_rate = 48000
        self.channels = 2
        self.device_name = "Piesă demo LumiBeat (124 BPM)"
        synth = DemoSynth(self.sample_rate)
        blk = self.block

        def feeder():
            t0 = time.perf_counter()
            n = 0
            while not self._stop.is_set():
                self._push(synth.render(blk))
                n += blk
                target = t0 + n / self.sample_rate
                dt = target - time.perf_counter()
                if dt > 0:
                    time.sleep(dt)
                elif dt < -0.5:   # we fell behind (debugger, sleep) - resync
                    t0 = time.perf_counter()
                    n = 0

        self._feeder = threading.Thread(target=feeder, name="audio-demo", daemon=True)
        self._feeder.start()
        self.status = "activ"
        return True

    # ---------------------------------------------------------------- helpers
    def _push(self, a: np.ndarray) -> None:
        self._last_packet = time.monotonic()
        try:
            self._q.put_nowait((a, time.perf_counter()))
        except queue.Full:
            self.overruns += 1
            try:  # drop the oldest block to keep latency low
                self._q.get_nowait()
                self._q.put_nowait((a, time.perf_counter()))
            except queue.Empty:
                pass

    def _default_output_name(self) -> str:
        if not HAVE_PAW or self._pa is None:
            return ""
        try:
            wasapi = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            return self._pa.get_device_info_by_index(wasapi["defaultOutputDevice"])["name"]
        except Exception:
            return ""

    def _process_loop(self) -> None:
        silence = np.zeros((self.block, 2), np.float32)
        last_check = time.monotonic()
        timeout = self.block / self.sample_rate * 2.5
        while not self._stop.is_set():
            try:
                a, ts = self._q.get(timeout=timeout)
            except queue.Empty:
                a, ts = silence, None   # loopback: nothing is playing
            try:
                self.analyzer.process(a, ts)
            except Exception as e:  # pragma: no cover
                self.error = f"Analiză audio: {e}"
            now = time.monotonic()
            if now - last_check > 3.0:
                last_check = now
                self._watchdog()

    def _watchdog(self) -> None:
        """Keep the capture alive.

        * restart a stream that died (device unplugged, driver reset)
        * loopback of the *default* device: WASAPI delivers no packets while that device is
          silent.  If nothing arrived for a while, re-resolve the default playback device
          (the user may have switched speakers / headphones) by restarting the stream."""
        if self.source not in ("loopback", "mic"):
            return
        dead = False
        try:
            if self._stream is not None and not self._stream.is_active():
                dead = True
        except Exception:
            dead = True
        now = time.monotonic()
        stale = (self.source == "loopback" and bool(self._watch_default) and now - self._last_packet > 8.0
                 and now - self._last_restart > 8.0)
        if dead or stale:
            self._last_restart = now
            threading.Thread(target=self.restart, daemon=True).start()

    def _shutdown_locked(self) -> None:
        self._stop.set()
        for th in (self._feeder, self._proc):
            if th and th.is_alive() and th is not threading.current_thread():
                th.join(timeout=1.0)
        self._feeder = None
        self._proc = None
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None
        if self._sd_stream is not None:
            try:
                self._sd_stream.stop()
                self._sd_stream.close()
            except Exception:
                pass
            self._sd_stream = None
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

    def _notify(self) -> None:
        if self.on_status:
            try:
                self.on_status(self.status)
            except Exception:
                pass

