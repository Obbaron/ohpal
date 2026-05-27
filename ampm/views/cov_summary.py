"""
cov_summary.py

(a) Grouped bar chart of signal 1 CoV per part
(b) Grouped bar chart of signal 2 CoV per part
(c) Scatter of signal 2 vs signal 1 overall CoV per part
"""

NAME = "CoV Summary"
DESCRIPTION = (
    "Three-panel figure: grouped CoV bars for two signals plus a scatter comparison."
)

AXES = {
    "signal_1": {"label": "Signal 1", "default": "Laser output power (mean)"},
    "signal_2": {"label": "Signal 2", "default": "MeltVIEW melt pool (mean)"},
}

SETTINGS = {}

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


def run(df, config, axes, settings):
    import numpy as np
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    from ampm.stats import compute_cov

    signal_1 = axes["signal_1"]
    signal_2 = axes["signal_2"]
    signals = [signal_1, signal_2]

    cov_data = {}
    for mode in ("overall", "per_layer_mean", "across_layers"):
        print(f"Computing CoV ({mode})...")
        cov_data[mode] = compute_cov(
            df,
            signals,
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
            f"(a)  {signal_1} CoV",
            f"(b)  {signal_2} CoV",
            f"(c)  {signal_2} vs {signal_1}",
        ],
        column_widths=[0.35, 0.35, 0.30],
        horizontal_spacing=0.08,
    )

    for col_idx, signal in enumerate(signals, start=1):
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

    laser_col = f"cov_{signal_1}"
    melt_col = f"cov_{signal_2}"

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

    fig.update_xaxes(title_text=f"{signal_1} CoV (overall)", row=1, col=3)
    fig.update_yaxes(title_text=f"{signal_2} CoV (overall)", row=1, col=3)

    fig.update_layout(
        title_text="Coefficient of Variation — process stability by part",
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

    fig.show()
    print("Done.")
