import os
import tempfile

import numpy as np
import pytest

os.environ.setdefault("LUMIBEAT_HOME", tempfile.mkdtemp(prefix="lumibeat-test-"))

from lumibeat.audio.analysis import AudioAnalyzer  # noqa: E402
from lumibeat.audio.demo import DemoSynth  # noqa: E402
from lumibeat.core.artnet import build_artdmx, parse_artpollreply  # noqa: E402
from lumibeat.core.config import Config  # noqa: E402
from lumibeat.core.geometry import build_geometry  # noqa: E402
from lumibeat.core.mapping import OutputMapper, TestPattern as Pattern  # noqa: E402
from lumibeat.core.party import PARTY_PRESETS  # noqa: E402
from lumibeat.core.presets import PresetStore  # noqa: E402
from lumibeat.core.state import ShowState  # noqa: E402
from lumibeat.effects import REGISTRY, Ctx, Palette  # noqa: E402
from lumibeat.audio.analysis import AudioFeatures  # noqa: E402


def test_default_layout_matches_installation():
    c = Config.default()
    assert len(c.profiles) == 12
    assert [p.port for p in c.profiles] == [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4]
    assert [p.data_up for p in c.profiles[:3]] == [True, False, True]
    xs = [p.x_cm for p in c.profiles]
    assert xs == sorted(xs)
    # 30 cm spacing inside each group, symmetric around the wall centre
    assert pytest.approx(xs[1] - xs[0]) == 30
    assert pytest.approx(xs[0] + xs[11]) == c.wall.wall_width_cm


def test_geometry_symmetry():
    g = build_geometry(Config.default())
    assert g.shape == (12, 84, 3)
    assert list(g.side[:6]) == [-1] * 6 and list(g.side[6:]) == [1] * 6
    assert list(g.inner[:6]) == [5, 4, 3, 2, 1, 0]
    assert list(g.mirror) == list(range(11, -1, -1))


def test_mapping_serpentine_and_universes():
    c = Config.default()
    m = OutputMapper(c)
    assert m.port_len == [252, 252, 252, 252]
    assert m.port_universes[0] == [0, 1]
    # physical bottom pixel of every profile is virtual row 0
    for s in m.segments:
        start = s.start
        pos = m.g_pos[start:start + s.pixels]
        assert (pos[0] == 0) == s.data_up


def test_mapping_respects_start_channel_and_universe():
    c = Config.default()
    c.ports[1].universe = 10
    c.ports[1].start_channel = 4
    m = OutputMapper(c)
    assert m.port_universes[1][0] == 10
    sl = [s for s in m.slices if s.port == 1][0]
    assert sl.channel_offset == 3
    assert sl.count == 169  # (512-3)//3 = 169 pixels fit in the first universe


def test_mapping_overlap_detected():
    c = Config.default()
    c.ports[1].universe = 0
    rep = OutputMapper(c).report()
    assert not rep.ok


def test_count_test_pattern():
    c = Config.default()
    m = OutputMapper(c)
    tp = Pattern(kind="count", profile=1, index=10)
    col = m.test_colors(tp)
    seg = [s for s in m.segments if s.profile == 1][0]
    lit = col[seg.start:seg.start + seg.pixels].sum(axis=1) > 0
    assert lit.sum() == 10 and lit[:10].all()


def test_artdmx_header():
    p = build_artdmx(5, b"\x01\x02\x03", 1)
    assert p[:8] == b"Art-Net\x00" and len(p) == 18 + 4  # padded to even


def test_artpollreply_parse():
    pkt = bytearray(239)
    pkt[:8] = b"Art-Net\x00"
    pkt[8:10] = b"\x00\x21"
    pkt[10:14] = bytes([10, 0, 0, 7])
    pkt[173] = 4
    pkt[190:194] = bytes([1, 2, 3, 4])
    n = parse_artpollreply(bytes(pkt), "10.0.0.7")
    assert n.ip == "10.0.0.7" and n.sw_out == [1, 2, 3, 4]


def test_bpm_on_demo_track():
    an = AudioAnalyzer(48000, 512)
    syn = DemoSynth()
    for _ in range(int(40 * 48000 / 512)):
        an.process(syn.render(512))
    assert abs(an.features.bpm - 124) < 2.5
    assert an.features.drop_count >= 1


def test_all_effects_render():
    g = build_geometry(Config.default(), 48)
    music = [k for k, v in REGISTRY.items() if v.category in ("music", "special")]
    assert len(music) >= 30
    for k, cls in REGISTRY.items():
        e = cls(g)
        for i in range(10):
            f = AudioFeatures(level=0.5, bass=0.6, bands=np.full(32, 0.5, np.float32), bpm=120, beat_phase=i / 10)
            out = e.frame(Ctx(g=g, dt=1 / 60, audio=f, palette=Palette.named(cls.palette), beat=i == 0, kick=i == 0))
            assert out.shape == g.shape and np.isfinite(out).all(), k


def test_party_pools_valid():
    for pid, p in PARTY_PRESETS.items():
        for pool in p["pools"].values():
            for e in pool:
                assert e in REGISTRY, (pid, e)


def test_presets_roundtrip(tmp_path):
    store = PresetStore(tmp_path / "p.json")
    st = ShowState(mode="ambient", ambient_scene="ocean", ambient_temp=3000)
    p = store.create("Seara", st)
    store2 = PresetStore(tmp_path / "p.json")
    vals = PresetStore.apply_values(store2.get(p["id"]))
    assert vals["mode"] == "ambient" and vals["ambient_scene"] == "ocean"
    exp = tmp_path / "e.json"
    assert store2.export(exp) == 1
    assert store2.import_file(exp) == 1


def test_strobe_never_persisted():
    st = ShowState(strobe_enabled=True)
    assert "strobe_enabled" not in st.to_dict(persist=True)
    assert ShowState.from_dict({"strobe_enabled": True}).strobe_enabled is False


def test_full_packets_and_universe_padding():
    c = Config.default()
    c.network.full_packets = True
    c.network.universes_per_port = 3
    c.ports = [type(c.ports[0])(number=i + 1, universe=1 + 3 * i) for i in range(4)]
    m = OutputMapper(c)
    assert m.port_universes[0] == [1, 2, 3]
    assert m.port_universes[3] == [10, 11, 12]
    unis = m.map(np.ones((12, c.wall.matrix_rows, 3), np.float32), 1.0)
    assert sorted(unis) == list(range(1, 13))
    assert all(len(v) == 512 for v in unis.values())
    assert m.report().ok
