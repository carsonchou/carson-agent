import pathlib, sys, soundfile as sf
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from kokoro_onnx import Kokoro
ROOT = pathlib.Path("ch3_lab")
k = Kokoro("_ttslab311/kokoro-v1.0.onnx", "_ttslab311/voices-v1.0.bin")
tot = 0.0
for name in ("hook","spread","replication","result","close"):
    t = (ROOT / f"narr_{name}.txt").read_text(encoding="utf-8").strip()
    s, sr = k.create(t, voice="am_michael", speed=0.98, lang="en-us")
    sf.write(ROOT / f"seg_{name}.wav", s, sr)
    d = len(s) / sr
    tot += d
    print(f"{name:<12} {d:6.2f}s  ({len(t.split())/d*60:.0f} wpm)")
print(f"合計旁白 {tot:.1f}s")
