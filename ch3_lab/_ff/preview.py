import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import numpy as np, imageio.v2 as iio
import make_short as M
plt = M._plt()
picks = [("row", 4), ("row", 13), ("slug", "ego_depletion"),
         ("slug", "romantic_red"), ("row", 1), ("row", 12)]
tiles = []
for kind, v in picks:
    D = M.collect(**{kind: v}) if kind == "slug" else M.collect(row=v)
    D["_fs"] = M.fit_sizes(plt, D)
    buf = M.render(plt, "q", 0.0, 6.0, D)     # 第 0 幀 = feed 裡看到的那一幀
    iio.imwrite(f"_ff/new_{D['key']}.png", buf)
    tiles.append(buf[::4, ::4])
h = min(t.shape[0] for t in tiles)
row1 = np.concatenate([np.pad(t[:h], ((0,0),(0,6),(0,0)), constant_values=60) for t in tiles[:3]], axis=1)
row2 = np.concatenate([np.pad(t[:h], ((0,0),(0,6),(0,0)), constant_values=60) for t in tiles[3:]], axis=1)
w = min(row1.shape[1], row2.shape[1])
iio.imwrite("_ff/_sheet.png", np.concatenate(
    [np.pad(r[:, :w], ((0,8),(0,0),(0,0)), constant_values=60) for r in (row1,row2)], axis=0))
print("ok ->_ff/_sheet.png")
