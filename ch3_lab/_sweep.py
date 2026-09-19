import sys, pathlib, soundfile as sf
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from kokoro_onnx import Kokoro

TEXT = ("In nineteen ninety-eight, a study asked people to resist a plate of warm cookies. "
        "Then it gave them an impossible puzzle. The people who resisted gave up sooner. "
        "The conclusion: willpower is a finite resource. It was cited over four thousand times. "
        "Then twenty-three laboratories ran it again, and the effect was zero point zero four.")
VOICES = ["am_michael","am_adam","am_eric","am_onyx","am_puck","am_liam",
          "bm_george","bm_lewis","bm_fable","af_bella","af_heart","af_nova","bf_emma"]
k = Kokoro("_ttslab311/kokoro-v1.0.onnx", "_ttslab311/voices-v1.0.bin")
out = pathlib.Path("ch3_lab")
for v in VOICES:
    try:
        s, sr = k.create(TEXT, voice=v, speed=1.0, lang="en-us")
        sf.write(out / f"sw_{v}.wav", s, sr)
        print(f"OK {v} {len(s)/sr:.1f}s", flush=True)
    except Exception as e:
        print(f"FAIL {v} {str(e)[:70]}", flush=True)
