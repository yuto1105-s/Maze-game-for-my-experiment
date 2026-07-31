"""
analyze_movement.py
====================
迷路の3Dマップ内でプレイヤーが移動した位置ログ（player_logs.db の player_logs テーブル）を
Pythonで読み込み、時間経過とともに「赤 → 青」に色が変化する軌跡グラフを描画するスクリプトです。

前提:
    server.js 側で以下のテーブルに位置ログが記録されています。
        player_logs(id, player_id, color, time, x, y, z, rx, ry, rz)
    time 列は ISO8601形式の文字列 (例: "2026-07-30T12:34:56.789Z") です。

使い方:
    # 1. 必要なライブラリをインストール（初回のみ）
    pip install pandas matplotlib --break-system-packages

    # 2. server.js と同じディレクトリ（player_logs.db がある場所）で実行
    python3 analyze_movement.py

    # プレイヤーを指定したい場合
    python3 analyze_movement.py --player <player_id>

    # DBファイルの場所を指定したい場合
    python3 analyze_movement.py --db /path/to/player_logs.db

出力:
    ./movement_output/ 以下に、プレイヤーごとに
        - <player_id>_trajectory_topdown.png  (上から見た軌跡: X-Z平面、赤→青のグラデーション)
        - <player_id>_trajectory_3d.png       (Y軸=高さも含めた3D軌跡)
    を生成し、あわせて移動距離・所要時間・平均速度などの簡単な統計をコンソールに表示します。
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # 画面がない環境でも画像保存できるようにする
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap
from mpl_toolkits.mplot3d.art3d import Line3DCollection

# 日本語ラベルが文字化けしないよう、実行環境にあるCJK対応フォントを自動検出して使用する
_JP_FONT_CANDIDATES = [
    "Yu Gothic", "Meiryo", "MS Gothic", "Hiragino Sans", "Hiragino Kaku Gothic Pro",
    "Noto Sans CJK JP", "Noto Sans JP", "IPAexGothic", "IPAGothic", "TakaoGothic",
]
_available = {f.name for f in fm.fontManager.ttflist}
for _name in _JP_FONT_CANDIDATES:
    if _name in _available:
        matplotlib.rcParams["font.family"] = _name
        break
matplotlib.rcParams["axes.unicode_minus"] = False

# 「赤 → 青」のカスタムカラーマップ（時間経過を表現）
RED_TO_BLUE = LinearSegmentedColormap.from_list("red_to_blue", ["#E53935", "#3949AB", "#1E88E5"])


def parse_time(series: pd.Series) -> pd.Series:
    """ISO8601文字列を datetime に変換する（末尾Zにも対応）。"""
    return pd.to_datetime(series, utc=True, errors="coerce")


def load_logs(db_path: str, player_id: str | None) -> pd.DataFrame:
    if not os.path.exists(db_path):
        sys.exit(f"[エラー] DBファイルが見つかりません: {db_path}")

    conn = sqlite3.connect(db_path)
    query = "SELECT player_id, color, time, x, y, z, rx, ry, rz FROM player_logs"
    params = ()
    if player_id:
        query += " WHERE player_id = ?"
        params = (player_id,)
    query += " ORDER BY player_id, time"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if df.empty:
        sys.exit("[エラー] 該当する移動ログが見つかりませんでした。")

    df["time"] = parse_time(df["time"])
    df = df.dropna(subset=["time"]).reset_index(drop=True)
    return df


def summarize(df: pd.DataFrame) -> dict:
    """移動距離・所要時間・平均速度を計算する。"""
    dx = df["x"].diff()
    dy = df["y"].diff()
    dz = df["z"].diff()
    step_dist = np.sqrt(dx**2 + dy**2 + dz**2).fillna(0)
    total_dist = step_dist.sum()

    duration = (df["time"].iloc[-1] - df["time"].iloc[0]).total_seconds()
    avg_speed = total_dist / duration if duration > 0 else 0.0

    return {
        "points": len(df),
        "start_time": df["time"].iloc[0],
        "end_time": df["time"].iloc[-1],
        "duration_sec": duration,
        "total_distance": total_dist,
        "avg_speed": avg_speed,
    }


def plot_topdown(df: pd.DataFrame, out_path: str, title: str):
    """X-Z平面（上から見た地図）の軌跡を、時間経過に応じて赤→青のグラデーションで描画。"""
    x = df["x"].to_numpy()
    z = df["z"].to_numpy()
    t = df["time"].astype("int64").to_numpy().astype(float)
    t_norm = (t - t.min()) / (t.max() - t.min()) if t.max() > t.min() else np.zeros_like(t)

    points = np.array([x, z]).T.reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)

    fig, ax = plt.subplots(figsize=(8, 8))
    lc = LineCollection(segments, cmap=RED_TO_BLUE, linewidths=2.5)
    lc.set_array(t_norm[:-1])
    ax.add_collection(lc)

    # 開始・終了地点をマーカー表示
    ax.scatter(x[0], z[0], c="#E53935", s=90, marker="o", edgecolor="black", zorder=5, label="開始")
    ax.scatter(x[-1], z[-1], c="#1E88E5", s=90, marker="X", edgecolor="black", zorder=5, label="現在/終了")

    ax.set_xlim(x.min() - 2, x.max() + 2)
    ax.set_ylim(z.min() - 2, z.max() + 2)
    ax.set_xlabel("X 座標")
    ax.set_ylabel("Z 座標")
    ax.set_title(title)
    ax.set_aspect("equal", adjustable="box")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)

    cbar = fig.colorbar(lc, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("経過時間（赤 = 開始 → 青 = 終了）")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_3d(df: pd.DataFrame, out_path: str, title: str):
    """X, Y(高さ), Z を使った3D軌跡を、時間経過に応じて赤→青のグラデーションで描画。"""
    x = df["x"].to_numpy()
    y = df["y"].to_numpy()
    z = df["z"].to_numpy()
    t = df["time"].astype("int64").to_numpy().astype(float)
    t_norm = (t - t.min()) / (t.max() - t.min()) if t.max() > t.min() else np.zeros_like(t)

    points = np.array([x, z, y]).T.reshape(-1, 1, 3)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)

    fig = plt.figure(figsize=(9, 8))
    ax = fig.add_subplot(111, projection="3d")
    lc = Line3DCollection(segments, cmap=RED_TO_BLUE, linewidths=2.0)
    lc.set_array(t_norm[:-1])
    ax.add_collection3d(lc)

    ax.scatter(x[0], z[0], y[0], c="#E53935", s=60, label="開始")
    ax.scatter(x[-1], z[-1], y[-1], c="#1E88E5", s=60, marker="X", label="現在/終了")

    ax.set_xlim(x.min() - 2, x.max() + 2)
    ax.set_ylim(z.min() - 2, z.max() + 2)
    ax.set_zlim(y.min() - 1, y.max() + 1)
    ax.set_xlabel("X")
    ax.set_ylabel("Z")
    ax.set_zlabel("Y (高さ)")
    ax.set_title(title)
    ax.legend()

    cbar = fig.colorbar(lc, ax=ax, fraction=0.04, pad=0.08)
    cbar.set_label("経過時間（赤 = 開始 → 青 = 終了）")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="迷路プレイヤーの移動ログを分析・可視化する")
    parser.add_argument("--db", default="player_logs.db", help="SQLite DBファイルのパス（既定: player_logs.db）")
    parser.add_argument("--player", default=None, help="特定の player_id のみ分析したい場合に指定")
    parser.add_argument("--out", default="movement_output", help="出力フォルダ（既定: movement_output）")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    df_all = load_logs(args.db, args.player)

    for player_id, group in df_all.groupby("player_id"):
        group = group.sort_values("time").reset_index(drop=True)
        stats = summarize(group)

        print(f"\n=== プレイヤー: {player_id} ===")
        print(f"  記録ポイント数     : {stats['points']}")
        print(f"  開始時刻            : {stats['start_time']}")
        print(f"  終了時刻            : {stats['end_time']}")
        print(f"  所要時間 (秒)       : {stats['duration_sec']:.1f}")
        print(f"  総移動距離 (単位)   : {stats['total_distance']:.2f}")
        print(f"  平均速度 (単位/秒)  : {stats['avg_speed']:.3f}")

        topdown_path = os.path.join(args.out, f"{player_id}_trajectory_topdown.png")
        threed_path = os.path.join(args.out, f"{player_id}_trajectory_3d.png")

        plot_topdown(group, topdown_path, f"移動軌跡（上から見た図）- {player_id}")
        plot_3d(group, threed_path, f"移動軌跡（3D）- {player_id}")

        print(f"  → 上から見た軌跡を保存: {topdown_path}")
        print(f"  → 3D軌跡を保存        : {threed_path}")


if __name__ == "__main__":
    main()