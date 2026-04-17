#!/usr/bin/env python3
"""
figure_generator.py
====================
Generates publication-ready scientific figures for the medical-paper-pipeline skill.

Supports: patient flow chart, Kaplan-Meier, forest plot, ROC curve,
calibration plot, heatmap, box plot, stacked bar chart.

Outputs:
  - Color version (submission): TIFF @ 300dpi + SVG
  - Grayscale version (print review): TIFF @ 300dpi + SVG

Usage (import as module):
    from figure_generator import FigureGenerator, FigureType
    fg = FigureGenerator(output_dir="figures")
    fg.generate(
        figure_type=FigureType.KAPLAN_MEIER,
        data={...},
        config={...},
        style_config={...}
    )

CLI usage:
    python figure_generator.py --type km --input data.json --output-dir figures
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

# Use non-interactive backend for server/CLI environments
matplotlib.use("Agg")

import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
from matplotlib.ticker import MaxNLocator

try:
    import lifelines
    from lifelines import KaplanMeierFitter
    from lifelines.statistics import logrank_test

    LIFELINES_AVAILABLE = True
except ImportError:
    LIFELINES_AVAILABLE = False

try:
    from sklearn.metrics import auc, roc_curve, roc_auc_score
    from sklearn.utils import resample

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    import plotly.express as px
    import plotly.graph_objects as go

    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False


# ─── Constants ────────────────────────────────────────────────────────────────

# Okabe-Ito colorblind-friendly palette
OKABE_COLORS = {
    "blue": "#0072B2",
    "orange": "#E69F00",
    "teal": "#009E73",
    "rose": "#CC79A7",
    "sky": "#56B4E9",
    "coral": "#D55E00",
    "yellow": "#F0E442",
    "gray": "#999999",
    "black": "#000000",
}

OKABE_HEX_LIST = [
    OKABE_COLORS["blue"],
    OKABE_COLORS["orange"],
    OKABE_COLORS["teal"],
    OKABE_COLORS["rose"],
    OKABE_COLORS["sky"],
    OKABE_COLORS["coral"],
    OKABE_COLORS["yellow"],
    OKABE_COLORS["gray"],
]

# Grayscale equivalents for print
OKABE_GRAYSCALE = {
    "blue": "#4D4D4D",
    "orange": "#808080",
    "teal": "#666666",
    "rose": "#999999",
    "sky": "#B3B3B3",
    "coral": "#333333",
    "yellow": "#CCCCCC",
    "gray": "#AAAAAA",
    "black": "#000000",
}

# Export dimensions (cm → inches)
CM_TO_INCH = 1 / 2.54
HALF_WIDTH_CM = 8.5
FULL_WIDTH_CM = 17.0
HALF_WIDTH_INCH = HALF_WIDTH_CM * CM_TO_INCH
FULL_WIDTH_INCH = FULL_WIDTH_CM * CM_TO_INCH

# Default height ratio
HEIGHT_INCH = 6.0


# ─── Enums & Dataclasses ────────────────────────────────────────────────────


class FigureType(Enum):
    FLOW_CHART = "flow_chart"
    KAPLAN_MEIER = "kaplan_meier"
    FOREST_PLOT = "forest_plot"
    ROC_CURVE = "roc_curve"
    CALIBRATION_PLOT = "calibration_plot"
    HEATMAP = "heatmap"
    BOX_PLOT = "box_plot"
    STACKED_BAR = "stacked_bar"
    SANKEY = "sankey"


class ExportFormat(Enum):
    TIFF = "tiff"
    SVG = "svg"
    PNG = "png"


@dataclass
class StyleConfig:
    """Base style configuration for all figures."""

    palette: list[str] = field(default_factory=lambda: OKABE_HEX_LIST)
    grayscale: bool = False
    width: float = HALF_WIDTH_INCH
    height: float = HEIGHT_INCH
    font_family: str = "Arial"
    title_size: int = 12
    label_size: int = 10
    legend_size: int = 9
    panel_label_size: int = 12
    grid_color: str = "#CCCCCC"
    grid_linewidth: float = 0.5
    tick_direction: str = "out"  # matplotlib 'in'|'out'|'inout'

    def resolve_color(self, name: str) -> str:
        if self.grayscale:
            return OKABE_GRAYSCALE.get(name, OKABE_COLORS.get(name, "#000000"))
        return OKABE_COLORS.get(name, "#000000")

    def resolve_palette(self) -> list[str]:
        if self.grayscale:
            return [OKABE_GRAYSCALE["blue"], OKABE_GRAYSCALE["orange"],
        return self.palette


@dataclass
class FigureConfig:
    """Configuration specific to a figure type."""

    title: str = ""
    xlabel: str = ""
    ylabel: str = ""
    group_names: list[str] = field(default_factory=list)
    panel_label: str = ""  # e.g. "A", "B", "C"
    ci_level: float = 0.95  # confidence interval level
    bootstrap_iterations: int = 1000
    show_p_value: bool = True
    risk_table: bool = True
    time_unit: str = "months"


@dataclass
class ExportConfig:
    output_dir: Path = field(default_factory=lambda: Path("figures"))
    dpi: int = 300
    formats: list[ExportFormat] = field(
        default_factory=lambda: [ExportFormat.TIFF, ExportFormat.SVG]
    )
    journal_width: Literal["half", "full"] = "half"

    def resolve_dimensions(self) -> tuple[float, float]:
        w = FULL_WIDTH_INCH if self.journal_width == "full" else HALF_WIDTH_INCH
        return w, HEIGHT_INCH


# ─── Figure Generator ────────────────────────────────────────────────────────


class FigureGenerator:
    """
    Generates publication-ready scientific figures.

    All figures are rendered with Okabe-Ito colorblind-friendly palette,
    exported in both color (submission) and grayscale (print) versions.

    Usage:
        fg = FigureGenerator(output_dir="figures")
        fg.generate(FigureType.ROC_CURVE, data={...}, config={...})
    """

    def __init__(self, output_dir: str | Path = "figures"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._setup_matplotlib()

    def _setup_matplotlib(self) -> None:
        plt.rcParams.update({
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
            "font.size": 10,
            "axes.labelsize": 10,
            "axes.titlesize": 12,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
            "figure.dpi": 300,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "axes.axisbelow": True,
            "axes.grid": True,
            "grid.linewidth": 0.5,
            "grid.color": "#CCCCCC",
            "xtick.direction": "out",
            "ytick.direction": "out",
        })

    def generate(
        self,
        figure_type: FigureType,
        data: dict[str, Any],
        config: FigureConfig | None = None,
        style: StyleConfig | None = None,
        export: ExportConfig | None = None,
        filename: str | None = None,
    ) -> dict[str, Path]:
        """
        Generate a figure and save it.

        Args:
            figure_type: Which figure to generate.
            data: Figure-specific data (structure depends on figure_type).
            config: Figure-specific configuration.
            style: Visual style (colors, dimensions, fonts).
            export: Export settings (output dir, formats, DPI).
            filename: Output filename stem (auto-generated if None).

        Returns:
            Dict mapping format → Path of saved files.
        """
        config = config or FigureConfig()
        style = style or StyleConfig()
        export = export or ExportConfig()

        # Set dimensions from export config
        w, h = export.resolve_dimensions()
        style.width = w
        style.height = h

        # Create figure
        fig, axes = self._create_figure(figure_type)
        self._render(figure_type, fig, axes, data, config, style)

        # Save in requested formats
        stem = filename or self._default_filename(figure_type)
        return self._save(fig, stem, export, style.grayscale)

    def _create_figure(
        self, figure_type: FigureType
    ) -> tuple[plt.Figure, plt.Axes | np.ndarray]:
        if figure_type == FigureType.SANKEY:
            if not PLOTLY_AVAILABLE:
                raise ImportError("plotly is required for Sankey diagrams: pip install plotly")
            fig, ax = plt.subplots()
            return fig, ax
        fig, ax = plt.subplots(figsize=(StyleConfig().width, StyleConfig().height))
        return fig, ax

    def _render(
        self,
        figure_type: FigureType,
        fig: plt.Figure,
        axes: plt.Axes | np.ndarray,
        data: dict,
        config: FigureConfig,
        style: StyleConfig,
    ) -> None:
        ax = axes if not isinstance(axes, np.ndarray) else axes.flat[0]

        if figure_type == FigureType.FLOW_CHART:
            self._render_flow_chart(ax, data, config, style)
        elif figure_type == FigureType.KAPLAN_MEIER:
            self._render_kaplan_meier(ax, data, config, style)
        elif figure_type == FigureType.FOREST_PLOT:
            self._render_forest_plot(ax, data, config, style)
        elif figure_type == FigureType.ROC_CURVE:
            self._render_roc_curve(ax, data, config, style)
        elif figure_type == FigureType.CALIBRATION_PLOT:
            self._render_calibration_plot(ax, data, config, style)
        elif figure_type == FigureType.HEATMAP:
            self._render_heatmap(ax, data, config, style)
        elif figure_type == FigureType.BOX_PLOT:
            self._render_box_plot(ax, data, config, style)
        elif figure_type == FigureType.STACKED_BAR:
            self._render_stacked_bar(ax, data, config, style)
        elif figure_type == FigureType.SANKEY:
            self._render_sankey(fig, ax, data, config, style)

        self._apply_base_style(fig, ax, config, style)

    def _render_flow_chart(
        self, ax: plt.Axes, data: dict, config: FigureConfig, style: StyleConfig
    ) -> None:
        """Render a STROBE-compliant patient flow chart."""
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.axis("off")

        boxes = data.get("boxes", [])
        arrows = data.get("arrows", [])

        # Box style
        box_style = dict(
            boxstyle="round,pad=0.3",
            facecolor=style.resolve_color("sky") if not style.grayscale else "#E8E8E8",
            edgecolor=style.resolve_color("black"),
            linewidth=1.0,
        )
        arrow_style = dict(
            arrowstyle="->", color=style.resolve_color("black"), lw=1.0
        )

        for i, box in enumerate(boxes):
            x = box.get("x", 5.0)
            y = box.get("y", 9.0 - i * 2)
            text = box.get("text", "")
            ax.annotate(
                text,
                xy=(x, y),
                xytext=(x, y),
                fontsize=style.legend_size,
                ha="center",
                va="center",
                bbox=box_style,
                annotation_clip=False,
            )

        for arrow in arrows:
            x0, y0 = arrow.get("from", [0, 0])
            x1, y1 = arrow.get("to", [0, 0])
            label = arrow.get("label", "")
            ax.annotate(
                "",
                xy=(x1, y1),
                xytext=(x0, y0),
                arrowprops=dict(arrowstyle="->", color=style.resolve_color("black"), lw=1.0),
            )
            if label:
                mx, my = (x0 + x1) / 2, (y0 + y1) / 2
                ax.text(mx, my, label, fontsize=style.legend_size - 1, ha="center", va="center")

    def _render_kaplan_meier(
        self, ax: plt.Axes, data: dict, config: FigureConfig, style: StyleConfig
    ) -> None:
        if not LIFELINES_AVAILABLE:
            raise ImportError("lifelines is required for Kaplan-Meier plots: pip install lifelines")

        timelines = data.get("timelines", np.linspace(0, data.get("max_time", 60), 100))
        group_names = config.group_names or ["Group 0", "Group 1"]

        kmf_list = []
        colors = style.resolve_palette()

        for idx, group_data in enumerate(data.get("groups", [])):
            durations = group_data["durations"]
            events = group_data.get("events", np.ones(len(durations), dtype=bool))
            kmf = KaplanMeierFitter()
            kmf.fit(durations, event_observed=events, timeline=timelines)
            kmf_list.append(kmf)

            color = colors[idx % len(colors)]
            label = group_names[idx] if idx < len(group_names) else f"Group {idx}"
            ax.plot(
                kmf.survival_function_.index,
                kmf.survival_function_.iloc[:, 0],
                color=color,
                linewidth=1.5,
                label=label,
            )
            # Confidence interval band
            ci_lower = kmf.confidence_interval_[kmf.confidence_interval_.columns[0]]
            ci_upper = kmf.confidence_interval_[kmf.confidence_interval_.columns[1]]
            ax.fill_between(
                kmf.survival_function_.index,
                ci_lower,
                ci_upper,
                color=color,
                alpha=0.2,
            )

        # Log-rank test
        if config.show_p_value and len(kmf_list) == 2:
            results = logrank_test(
                data["groups"][0]["durations"],
                data["groups"][1]["durations"],
                data["groups"][0].get("events", np.ones(len(data["groups"][0]["durations"])),
                data["groups"][1].get("events", np.ones(len(data["groups"][1]["durations"])),
            )
            p_text = f"Log-rank p = {results.p_value:.4f}" if results.p_value >= 0.0001 else "Log-rank p < 0.0001"
            ax.text(
                0.98, 0.02, p_text,
                transform=ax.transAxes,
                fontsize=style.legend_size,
                ha="right", va="bottom",
            )

        # Risk table
        if config.risk_table:
            self._add_risk_table(ax, kmf_list, timelines, group_names, style)

        ax.set_xlabel(config.xlabel or f"Time ({config.time_unit})", fontsize=style.label_size)
        ax.set_ylabel(config.ylabel or "Survival probability", fontsize=style.label_size)
        ax.set_ylim(0, 1.05)
        ax.legend(loc="best", fontsize=style.legend_size, framealpha=0.9)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    def _add_risk_table(
        self,
        ax: plt.Axes,
        kmf_list: list,
        timelines: np.ndarray,
        group_names: list[str],
        style: StyleConfig,
    ) -> None:
        """Add a risk table below the Kaplan-Meier plot."""
        tick_positions = np.linspace(0, len(timelines) - 1, 6).astype(int)
        tick_times = timelines[tick_positions]

        table_data = []
        for kmf in kmf_list:
            n_at_risk = [
                np.sum(kmf.durations > t) for t in tick_times
            ]
            table_data.append(n_at_risk)

        # Convert axes to make room for table
        pos = ax.get_position()
        fig = ax.figure
        table_height = 0.12
        ax.set_position([
            pos.x0, pos.y0,
            pos.width, pos.height - table_height
        ])

        # Create risk table axes
        table_ax = fig.add_axes([pos.x0, pos.y0, pos.width, table_height])
        table_ax.axis("off")
        table_ax.set_xlim(0, 1)
        table_ax.set_ylim(0, 1)

        n_cols = len(tick_times)
        col_width = 1.0 / (n_cols + 1)
        for col_idx, t in enumerate(tick_times):
            x = col_width * (col_idx + 1)
            table_ax.text(x, 0.85, f"Time {int(t)}", ha="center", va="top", fontsize=style.legend_size - 1)
            for grp_idx, n in enumerate(table_data):
                y = 0.65 - grp_idx * 0.3
                table_ax.text(x, y, str(n[col_idx]), ha="center", va="top", fontsize=style.legend_size - 1)
                # Group label
                table_ax.text(
                    col_width * 0.5, y,
                    group_names[grp_idx] if grp_idx < len(group_names) else f"Group {grp_idx}",
                    ha="center", va="top", fontsize=style.legend_size - 1, fontweight="bold",
                )

    def _render_forest_plot(
        self, ax: plt.Axes, data: dict, config: FigureConfig, style: StyleConfig
    ) -> None:
        """Render a forest plot (OR/HR with 95% CI)."""
        estimates = data.get("estimates", [])
        labels = data.get("labels", [f"Item {i}" for i in range(len(estimates))]

        if not estimates:
            ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center")
            return

        y_positions = np.arange(len(estimates))
        colors = style.resolve_palette()

        # Reference line at 1.0
        ax.axvline(x=1.0, color=style.resolve_color("black"), linewidth=1.0, linestyle="-")

        for i, (est, y_pos) in enumerate(zip(estimates, y_positions)):
            point = est["point"]
            lower = est["lower"]
            upper = est["upper"]
            color = colors[i % len(colors)]
            label_text = labels[i] if i < len(labels) else ""

            ax.plot([lower, upper], [y_pos, y_pos], color=color, linewidth=1.5)
            ax.plot(point, y_pos, "o", color=color, markersize=5)

            # HR/OR value text
            x_max = ax.get_xlim()[1]
            ax.text(
                x_max * 0.98, y_pos,
                f"{point:.2f} ({lower:.2f}–{upper:.2f})",
                fontsize=style.legend_size - 1,
                va="center", ha="right",
            )

            ax.text(0.02, y_pos, label_text, transform=ax.get_yaxis_transform(), fontsize=style.legend_size - 1, va="center", ha="left")

        ax.set_yticks(y_positions)
        ax.set_yticklabels([])
        ax.set_xlabel(config.xlabel or "Odds Ratio / Hazard Ratio", fontsize=style.label_size)
        ax.set_xscale("log")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    def _render_roc_curve(
        self, ax: plt.Axes, data: dict, config: FigureConfig, style: StyleConfig
    ) -> None:
        if not SKLEARN_AVAILABLE:
            raise ImportError("sklearn is required for ROC curves: pip install scikit-learn")

        models = data.get("models", [{"y_true": [], "y_score": []}])
        model_names = config.group_names or [f"Model {i+1}" for i in range(len(models))]
        colors = style.resolve_palette()

        for idx, model_data in enumerate(models):
            y_true = np.array(model_data["y_true"])
            y_score = np.array(model_data["y_score"])

            fpr, tpr, _ = roc_curve(y_true, y_score)
            roc_auc = roc_auc_score(y_true, y_score)
            color = colors[idx % len(colors)]

            ax.plot(
                fpr, tpr, color=color, linewidth=1.5,
                label=f"{model_names[idx]} AUC = {roc_auc:.3f}",
            )

        # Diagonal reference line
        ax.plot([0, 1], [0, 1], color=style.resolve_color("gray"), linewidth=1.0, linestyle="--")

        ax.set_xlabel(config.xlabel or "1 - Specificity (False Positive Rate)", fontsize=style.label_size)
        ax.set_ylabel(config.ylabel or "Sensitivity (True Positive Rate)", fontsize=style.label_size)
        ax.legend(loc="lower right", fontsize=style.legend_size)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1.02)
        ax.set_aspect("equal")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    def _render_calibration_plot(
        self, ax: plt.Axes, data: dict, config: FigureConfig, style: StyleConfig
    ) -> None:
        """Render a calibration plot (observed vs predicted probabilities)."""
        predicted = np.array(data.get("predicted", []))
        observed = np.array(data.get("observed", []))

        if len(predicted) == 0 or len(observed) == 0:
            ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center")
            return

        # Sort by predicted probability
        sort_idx = np.argsort(predicted)
        pred_sorted = predicted[sort_idx]
        obs_sorted = observed[sort_idx]

        # Bin into deciles
        n_bins = 10
        bin_size = len(pred_sorted) // n_bins
        bin_centers = []
        bin_observed = []
        bin_predicted = []

        for b in range(n_bins):
            start = b * bin_size
            end = start + bin_size if b < n_bins - 1 else len(pred_sorted)
            bin_centers.append(np.mean(pred_sorted[start:end]))
            bin_observed.append(np.mean(obs_sorted[start:end]))
            bin_predicted.append(np.mean(pred_sorted[start:end]))

        color = style.resolve_color("blue")
        ax.plot([0, 1], [0, 1], color=style.resolve_color("gray"), linewidth=1.0, linestyle="--", label="Perfect calibration")
        ax.plot(bin_centers, bin_observed, "o-", color=color, linewidth=1.5, markersize=5, label="Model")

        ax.set_xlabel(config.xlabel or "Predicted probability", fontsize=style.label_size)
        ax.set_ylabel(config.ylabel or "Observed proportion", fontsize=style.label_size)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.legend(loc="upper left", fontsize=style.legend_size)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    def _render_heatmap(
        self, ax: plt.Axes, data: dict, config: FigureConfig, style: StyleConfig
    ) -> None:
        matrix = np.array(data.get("matrix", [[]])
        row_labels = data.get("row_labels", [f"R{i}" for i in range(matrix.shape[0])])
        col_labels = data.get("col_labels", [f"C{i}" for i in range(matrix.shape[1])])

        sns.heatmap(
            matrix,
            annot=True,
            fmt=".2f" if matrix.dtype != int else "d",
            cmap="RdBu_r" if not style.grayscale else "gray",
            xticklabels=col_labels,
            yticklabels=row_labels,
            ax=ax,
            cbar_kws={"label": config.ylabel or ""},
            linewidths=0.5,
            linecolor=style.grid_color,
        )
        ax.set_title(config.title, fontsize=style.title_size, pad=10)

    def _render_box_plot(
        self, ax: plt.Axes, data: dict, config: FigureConfig, style: StyleConfig
    ) -> None:
        groups = data.get("groups", [])
        group_labels = data.get("group_labels", [f"Group {i+1}" for i in range(len(groups))])
        colors = style.resolve_palette()

        positions = np.arange(len(groups))
        bp_data = []

        for i, grp in enumerate(groups):
            color = colors[i % len(colors)]
            bp = ax.boxplot(
                grp,
                positions=[i],
                widths=0.5,
                patch_artist=True,
                boxprops=dict(facecolor=color if not style.grayscale else OKABE_GRAYSCALE["gray"], alpha=0.7),
                medianprops=dict(color=style.resolve_color("black"), linewidth=1.5),
                whiskerprops=dict(color=style.resolve_color("black")),
                capprops=dict(color=style.resolve_color("black")),
                flierprops=dict(marker="o", markerfacecolor=color if not style.grayscale else "#666666", markersize=3),
            )
            bp_data.append(bp)

        ax.set_xticks(positions)
        ax.set_xticklabels(group_labels, fontsize=style.legend_size)
        ax.set_ylabel(config.ylabel or "", fontsize=style.label_size)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    def _render_stacked_bar(
        self, ax: plt.Axes, data: dict, config: FigureConfig, style: StyleConfig
    ) -> None:
        categories = data.get("categories", [])
        stacks = data.get("stacks", {})
        stack_labels = list(stacks.keys())
        n_stacks = len(stack_labels)
        colors = [style.resolve_palette()[i % len(style.resolve_palette())] for i in range(n_stacks)]

        bottom = np.zeros(len(categories))
        for i, (label, values) in enumerate(stacks.items()):
            color = colors[i] if not style.grayscale else OKABE_GRAYSCALE["gray"]
            ax.bar(categories, values, bottom=bottom, label=label, color=color, width=0.6)
            bottom += values

        ax.set_xlabel(config.xlabel or "", fontsize=style.label_size)
        ax.set_ylabel(config.ylabel or "Count", fontsize=style.label_size)
        ax.legend(fontsize=style.legend_size, loc="best")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    def _render_sankey(
        self, fig: plt.Figure, ax: plt.Axes, data: dict, config: FigureConfig, style: StyleConfig
    ) -> None:
        if not PLOTLY_AVAILABLE:
            raise ImportError("plotly is required for Sankey diagrams: pip install plotly")

        # Build Plotly Sankey diagram and embed as figure image
        nodes = data.get("nodes", [])
        links_src = data.get("links_source", [])
        links_tgt = data.get("links_target", [])
        links_val = data.get("links_value", [])

        node_color = [style.resolve_palette()[i % len(style.resolve_palette())] for i in range(len(nodes))]
        link_color = [style.resolve_palette()[src % len(style.resolve_palette())] + "80" for src in links_src]

        fig_sankey = go.Figure(data=[go.Sankey(
            node=dict(label=nodes, color=node_color),
            link=dict(source=links_src, target=links_tgt, value=links_val, color=link_color),
        )])
        fig_sankey.update_layout(font_size=style.legend_size)
        # Convert to matplotlib figure via static image
        fig_sankey.write_image(
            str(self.output_dir / "_temp_sankey.png"),
            width=int(style.width * 300),
            height=int(style.height * 300),
            scale=1,
        )
        img = plt.imread(str(self.output_dir / "_temp_sankey.png"))
        ax.imshow(img, aspect="auto")
        ax.axis("off")
        Path("_temp_sankey.png").unlink(missing_ok=True)

    def _apply_base_style(
        self, fig: plt.Figure, ax: plt.Axes, config: FigureConfig, style: StyleConfig
    ) -> None:
        """Apply common style elements after rendering."""
        if config.panel_label:
            ax.text(
                -0.02, 1.02, config.panel_label,
                transform=ax.transAxes,
                fontsize=style.panel_label_size,
                fontweight="bold",
                va="bottom",
            )
        if config.title:
            ax.set_title(config.title, fontsize=style.title_size, pad=10)
        ax.grid(True, color=style.grid_color, linewidth=style.grid_linewidth, axis="both")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    def _save(
        self,
        fig: plt.Figure,
        stem: str,
        export: ExportConfig,
        grayscale: bool,
    ) -> dict[str, Path]:
        """Save figure in all requested formats."""
        results = {}
        for fmt in export.formats:
            path = self.output_dir / f"{stem}_{'gs' if grayscale else 'color'}.{fmt.value}"
            if fmt == ExportFormat.TIFF:
                fig.savefig(path, format="tiff", dpi=export.dpi, bbox_inches="tight")
            elif fmt == ExportFormat.SVG:
                fig.savefig(path, format="svg", bbox_inches="tight")
            elif fmt == ExportFormat.PNG:
                fig.savefig(path, format="png", dpi=export.dpi, bbox_inches="tight")
            results[fmt.value] = path
        plt.close(fig)
        return results

    def _default_filename(self, figure_type: FigureType) -> str:
        return f"fig_{figure_type.value}"

    # ─── High-level convenience methods ─────────────────────────────────────────

    def generate_flow_chart(
        self,
        boxes: list[dict],
        arrows: list[dict],
        config: FigureConfig | None = None,
        style: StyleConfig | None = None,
        export: ExportConfig | None = None,
        grayscale: bool = False,
    ) -> dict[str, Path]:
        """
        Convenience: generate patient flow chart.
        boxes: [{'x': float, 'y': float, 'text': str}, ...]
        arrows: [{'from': [x,y], 'to': [x,y], 'label': str}, ...]
        """
        if style is not None:
            style.grayscale = grayscale
        elif style is None and grayscale:
            style = StyleConfig(grayscale=True)
        return self.generate(
            FigureType.FLOW_CHART,
            data={"boxes": boxes, "arrows": arrows},
            config=config or FigureConfig(),
            style=style,
            export=export or ExportConfig(),
            filename="flow_chart",
        )

    def generate_km(
        self,
        groups: list[dict],  # [{durations: [...], events: [...]}, ...]
        group_names: list[str] | None = None,
        config: FigureConfig | None = None,
        style: StyleConfig | None = None,
        export: ExportConfig | None = None,
        grayscale: bool = False,
    ) -> dict[str, Path]:
        """Convenience: generate Kaplan-Meier plot."""
        if style is not None:
            style.grayscale = grayscale
        elif style is None and grayscale:
            style = StyleConfig(grayscale=True)
        cfg = config or FigureConfig()
        if group_names:
            cfg.group_names = group_names
        return self.generate(
            FigureType.KAPLAN_MEIER,
            data={"groups": groups},
            config=cfg,
            style=style,
            export=export or ExportConfig(),
            filename="fig_km",
        )

    def generate_roc(
        self,
        models: list[dict],  # [{y_true: [...], y_score: [...]}, ...]
        model_names: list[str] | None = None,
        config: FigureConfig | None = None,
        style: StyleConfig | None = None,
        export: ExportConfig | None = None,
        grayscale: bool = False,
    ) -> dict[str, Path]:
        """Convenience: generate ROC curve."""
        if style is not None:
            style.grayscale = grayscale
        elif style is None and grayscale:
            style = StyleConfig(grayscale=True)
        cfg = config or FigureConfig()
        if model_names:
            cfg.group_names = model_names
        return self.generate(
            FigureType.ROC_CURVE,
            data={"models": models},
            config=cfg,
            style=style,
            export=export or ExportConfig(),
            filename="fig_roc",
        )

    def generate_calibration(
        self,
        predicted: list,
        observed: list,
        config: FigureConfig | None = None,
        style: StyleConfig | None = None,
        export: ExportConfig | None = None,
        grayscale: bool = False,
    ) -> dict[str, Path]:
        """Convenience: generate calibration plot."""
        if style is not None:
            style.grayscale = grayscale
        elif style is None and grayscale:
            style = StyleConfig(grayscale=True)
        return self.generate(
            FigureType.CALIBRATION_PLOT,
            data={"predicted": predicted, "observed": observed},
            config=config or FigureConfig(),
            style=style,
            export=export or ExportConfig(),
            filename="fig_calibration",
        )


# ─── CLI entry point ─────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate publication-ready scientific figures.")
    parser.add_argument("--type", "-t", required=True, choices=[ft.value for ft in FigureType])
    parser.add_argument("--input", "-i", help="JSON file with figure data")
    parser.add_argument("--output-dir", "-o", default="figures")
    parser.add_argument("--width", choices=["half", "full"], default="half")
    parser.add_argument("--grayscale", "-g", action="store_true")
    parser.add_argument("--formats", "-f", default="tiff,svg", help="Comma-separated formats")
    parser.add_argument("--filename", help="Output filename stem")

    args = parser.parse_args()

    # Load data
    if args.input:
        with open(args.input) as f:
            data = json.load(f)
    else:
        data = {}

    # Resolve formats
    fmt_map = {"tiff": ExportFormat.TIFF, "svg": ExportFormat.SVG, "png": ExportFormat.PNG}
    formats = [fmt_map[f.strip()] for f in args.formats.split(",")]

    export = ExportConfig(
        output_dir=Path(args.output_dir),
        formats=formats,
        journal_width=args.width,
    )

    style = StyleConfig(grayscale=args.grayscale)

    fg = FigureGenerator(output_dir=args.output_dir)

    try:
        ft = FigureType(args.type)
    except ValueError:
        sys.stderr.write(f"Unknown figure type: {args.type}\n")
        sys.exit(1)

    result = fg.generate(
        figure_type=ft,
        data=data,
        config=FigureConfig(),
        style=style,
        export=export,
        filename=args.filename,
    )

    print("Generated files:")
    for fmt, path in result.items():
        print(f"  {fmt}: {path}")


if __name__ == "__main__":
    _cli()
