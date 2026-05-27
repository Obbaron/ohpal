"""
cov_summary.py

Loads build data, computes Coefficient of Variation in all three modes
(overall, per_layer_mean, across_layers), then produces a Plotly figure
with three panels:

(a) Grouped bar chart of laser output power CoV per part
(b) Grouped bar chart of melt pool CoV per part
(c) Scatter of melt pool vs laser power overall CoV per part

Each bar panel shows the three CoV modes side by side for each part,
making it easy to see where instability comes from (within-layer noise
vs layer-to-layer drift).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from PyQt6.QtWidgets import QApplication, QFileDialog

from ampm import DataStore
from ampm.config import create_or_load_config
from ampm.mask_cache import mask_or_load
from ampm.masking import apply_mask, build_mask
from ampm.parts import QuantAMParts, assign_nearest_part
from ampm.stats import compute_cov

SIGNALS = [
    "Laser output power (mean)",
    "MeltVIEW melt pool (mean)",
]

MODE_COLORS = {
    "overall": "#2E6BB0",
    "per_layer_mean": "#2CA25F",
    "across_layers": "#D85A30",
}

MODE_LABELS = {
    "overall": "Overall",
    "per_layer_mean": "Per-layer mean",
    "across_layers": "Across layers",
}


def main() -> None:
    if len(sys.argv) >= 2:
        build_dir = sys.argv[1]
    else:
        _app = QApplication(sys.argv)
        build_dir = QFileDialog.getExistingDirectory(None, "Select Build Directory")
        if not build_dir:
            sys.exit("No directory selected.")
    config = create_or_load_config(build_dir)

    SOURCE = config["SOURCE"]
    STL = config["STL"]
    PARTS_CSV = config["PARTS_CSV"]
    LAYER_THICKNESS = config["LAYER_THICKNESS"]
    MASK_CACHE = config["MASK_CACHE"]
    MASK_KEEP_CACHE = config["MASK_KEEP_CACHE"]
    MAX_DISTANCE_MM = config["MAX_DISTANCE_MM"]

    store = DataStore(SOURCE, layer_thickness=LAYER_THICKNESS)
    df = store.query()
    print(f"Loaded {df.height:,} rows across {len(store.layers)} layers.")

    mask_params = {
        "layers": (min(store.layers), max(store.layers)),
        "stl": str(STL),
        "buffer_mm": 0.0,
        "layer_thickness": LAYER_THICKNESS,
    }

    def masking_wrapper(d):
        mask = build_mask(
            STL,
            layers=store.layers,
            layer_thickness=LAYER_THICKNESS,
            buffer_mm=0.0,
            cache_path=MASK_CACHE,
        )
        return apply_mask(d, mask)

    df_masked = mask_or_load(
        df,
        cache_path=MASK_KEEP_CACHE,
        mask_fn=masking_wrapper,
        params=mask_params,
        strict=True,
    )
    print(f"After mask: {df_masked.height:,} rows.")

    del df

    quantam = QuantAMParts.from_path(PARTS_CSV)
    parts_table = quantam.parent_parts()
    print(f"Loaded {parts_table.height} parts from {Path(PARTS_CSV).name}.")

    print("Assigning parts (direct)...")
    assigned = assign_nearest_part(
        df_masked,
        parts_table,
        max_distance_mm=MAX_DISTANCE_MM,
        noise_label="noise",
    )
    del df_masked

    cov_data = {}
    for mode in ("overall", "per_layer_mean", "across_layers"):
        print(f"Computing CoV ({mode})...")
        cov_data[mode] = compute_cov(
            assigned,
            SIGNALS,
            group_by="part_id",
            mode=mode,
            noise_label="noise",
        )

    part_ids = cov_data["overall"].sort("part_id")["part_id"].to_list()
    short_labels = [pid.replace("Part(", "P").replace(")", "") for pid in part_ids]

    fig = make_subplots(
        rows=1,
        cols=3,
        subplot_titles=[
            "(a)  Laser output power CoV",
            "(b)  Melt pool CoV",
            "(c)  Melt pool vs laser power",
        ],
        column_widths=[0.35, 0.35, 0.30],
        horizontal_spacing=0.08,
    )

    for col_idx, signal in enumerate(SIGNALS, start=1):
        cov_col = f"cov_{signal}"

        for mode in ("overall", "per_layer_mean", "across_layers"):
            values = (
                cov_data[mode].sort("part_id").select(cov_col).to_series().to_list()
            )

            fig.add_trace(
                go.Bar(
                    x=short_labels,
                    y=values,
                    name=MODE_LABELS[mode],
                    marker_color=MODE_COLORS[mode],
                    legendgroup=mode,
                    showlegend=(col_idx == 1),
                ),
                row=1,
                col=col_idx,
            )

        fig.update_yaxes(title_text="CoV", row=1, col=col_idx)
        fig.update_xaxes(title_text="Part", row=1, col=col_idx)

    laser_col = f"cov_{SIGNALS[0]}"
    melt_col = f"cov_{SIGNALS[1]}"

    laser_values = (
        cov_data["overall"].sort("part_id").select(laser_col).to_series().to_list()
    )
    melt_values = (
        cov_data["overall"].sort("part_id").select(melt_col).to_series().to_list()
    )

    fig.add_trace(
        go.Scatter(
            x=laser_values,
            y=melt_values,
            mode="markers+text",
            text=short_labels,
            textposition="top right",
            textfont=dict(size=10),
            marker=dict(
                size=10,
                color=list(range(len(short_labels))),
                colorscale="Turbo",
                showscale=False,
            ),
            showlegend=False,
        ),
        row=1,
        col=3,
    )

    laser_mean = np.mean(laser_values)
    melt_mean = np.mean(melt_values)

    fig.add_hline(
        y=melt_mean,
        line_dash="dash",
        line_color="#888888",
        line_width=1,
        row=1,
        col=3,
    )
    fig.add_vline(
        x=laser_mean,
        line_dash="dash",
        line_color="#888888",
        line_width=1,
        row=1,
        col=3,
    )

    fig.update_xaxes(title_text="Laser output power CoV (overall)", row=1, col=3)
    fig.update_yaxes(title_text="Melt pool CoV (overall)", row=1, col=3)

    fig.update_layout(
        title_text="Coefficient of Variation - process stability by part",
        title_font_size=16,
        barmode="group",
        height=500,
        width=1400,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.05,
            xanchor="center",
            x=0.35,
        ),
    )

    print("\nOpening figure...")
    fig.show()

    print("Done.")


if __name__ == "__main__":
    main()
