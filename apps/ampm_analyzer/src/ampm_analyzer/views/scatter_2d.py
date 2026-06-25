"""
scatter_2d.py
"""

NAME = "2D Scatter"
DESCRIPTION = "Top-down 2D scatter plot with optional color mapping."

AXES = {
    "x": {"label": "X axis", "default": "Demand X"},
    "y": {"label": "Y axis", "default": "Demand Y"},
    "color": {"label": "Color", "default": None},
}

SETTINGS = {
    "SAMPLE_SIZE": {
        "type": "int",
        "default": 100_000,
        "min": 1000,
        "max": 1_000_000,
        "label": "Sample size",
    },
    "POINT_SIZE": {
        "type": "int",
        "default": 4,
        "min": 1,
        "max": 20,
        "label": "Point size",
    },
    "EQUAL_ASPECT": {
        "type": "bool",
        "default": True,
        "label": "Equal aspect ratio",
    },
}


def run(df, config, axes, settings):
    from ohpal.ampm.plotting import scatter2d
    from ohpal.ampm.sampling import prepare_for_plot

    sample_size = settings.get("SAMPLE_SIZE", 100_000)
    point_size = settings.get("POINT_SIZE", 4)
    equal_aspect = settings.get("EQUAL_ASPECT", True)

    print(f"Sampling {sample_size:,} points...")
    sample = prepare_for_plot(df, target_points=sample_size, method="random", seed=0)

    print("Rendering 2D scatter...")
    scatter2d(
        sample,
        x=axes["x"],
        y=axes["y"],
        color=axes.get("color"),
        size=point_size,
        equal_aspect=equal_aspect,
        colorscale="Turbo",
        title=f"2D Scatter — color: {axes.get('color', 'none')}",
        xaxis_title=axes["x"],
        yaxis_title=axes["y"],
        colorbar_title=axes.get("color", ""),
    ).show()

    print("Done.")
