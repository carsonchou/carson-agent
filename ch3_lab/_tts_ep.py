import sys, pathlib, soundfile as sf
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from kokoro_onnx import Kokoro
out = pathlib.Path(r'D:\carson-agent\ch3_lab\eps\ep013')
k = Kokoro('_ttslab311/kokoro-v1.0.onnx', '_ttslab311/voices-v1.0.bin')
for n in ('hook', 'original', 'scale', 'replication', 'result', 'close'):
    t = (out / f'narr_{n}.txt').read_text(encoding='utf-8').strip()
    s, sr = k.create(t, voice='am_michael', speed=0.98, lang='en-us')
    sf.write(out / f'seg_{n}.wav', s, sr)
    print(f'  {n:<12}{len(s)/sr:6.1f}s', flush=True)
