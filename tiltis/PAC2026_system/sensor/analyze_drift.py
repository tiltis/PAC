"""measure_drift.py drift 결과(CSV)를 요약하고 그래프로 그린다. matplotlib이 있는 파이썬에서 실행.

    python analyze_drift.py <drift_*.csv>      # → 같은 폴더에 <이름>.png, 요약은 화면에 출력
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np

INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"  # 범주 색 1·2·3번(고정 순서)


def load(path):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {k: np.array([float(r[k]) for r in rows]) for k in rows[0]}


def summarize(d):
    t, c, fr, fpa, sd = d["t_min"], d["center_mean"], d["frame_mean"], d["fpa_c"], d["temporal_std"]
    dc = c - c[0]
    slope = np.polyfit(t, c, 1)[0]  # 카운트/분
    resid = c - np.polyval(np.polyfit(t, c, 1), t)
    last10 = t >= t[-1] - 10
    step = np.abs(np.diff(c))
    out = {
        "samples": int(len(t)), "minutes": round(float(t[-1]), 1),
        "center_range_counts": round(float(c.max() - c.min()), 1),
        "center_slope_counts_per_10min": round(float(slope * 10), 1),
        "center_resid_std_counts": round(float(resid.std()), 1),
        "center_step_median_counts": round(float(np.median(step)), 1),
        "center_step_max_counts": round(float(step.max()), 1),
        "last10_center_range_counts": round(float(c[last10].max() - c[last10].min()), 1),
        "frame_range_counts": round(float(fr.max() - fr.min()), 1),
        "fpa_start_c": float(fpa[0]), "fpa_end_c": float(fpa[-1]),
        "fpa_range_c": round(float(fpa.max() - fpa.min()), 2),
        "corr_center_vs_fpa": round(float(np.corrcoef(c, fpa)[0, 1]), 2) if fpa.std() > 0 else None,
        "temporal_std_median": round(float(np.median(sd)), 2),
    }
    return out, dc, fr - fr[0]


def plot(d, dc, dfr, out_png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": INK2, "axes.labelcolor": INK2,
                         "xtick.color": INK2, "ytick.color": INK2, "font.family": ["Malgun Gothic", "DejaVu Sans"]})
    t = d["t_min"]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 5.6), sharex=True, gridspec_kw={"height_ratios": [3, 2]},
                                 facecolor=SURFACE)
    for ax in (a1, a2):
        ax.set_facecolor(SURFACE)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    a1.plot(t, dc, color=BLUE, linewidth=2, marker="o", markersize=3.5, label="가운데 40×40 영역")
    a1.plot(t, dfr, color=ORANGE, linewidth=2, marker="o", markersize=3.5, label="화면 전체")
    a1.axhline(0, color=INK2, linewidth=0.8)
    a1.set_ylabel("첫 측정 대비 변화 (원시 카운트)")
    a1.set_title("Boson 원시값 변화 (매 측정 직전 FFC)", loc="left", color=INK, fontsize=11)
    a1.legend(frameon=False, loc="best", labelcolor=INK2)
    a1.annotate(f"{dc[-1]:+.0f}", (t[-1], dc[-1]), xytext=(4, 0), textcoords="offset points", color=INK2, va="center")
    a2.plot(t, d["fpa_c"], color=AQUA, linewidth=2, marker="o", markersize=3.5)
    a2.set_ylabel("검출기(FPA) 온도 °C")
    a2.set_title("Boson 검출기 온도 (대상 온도 아님)", loc="left", color=INK, fontsize=11)
    a2.set_xlabel("경과 시간 (분)")
    fig.tight_layout()
    fig.savefig(out_png, dpi=130, facecolor=SURFACE)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    path = Path(sys.argv[1])
    d = load(path)
    summary, dc, dfr = summarize(d)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    png = path.with_suffix(".png")
    plot(d, dc, dfr, png)
    print("saved", png)


if __name__ == "__main__":
    main()
