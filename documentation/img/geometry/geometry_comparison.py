"""Draw two idealized reservoir geometries and their response to rising water."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Polygon

OUTPUT = Path(__file__).resolve().parent
BASE_FS = 22
INK = "#26323a"
EDGE = "#356f91"
HIGH = "#dbeaf3"
LOW = "#83b3ce"
SIDE = "#aacbdc"
FRONT = "#77a9c5"
FLOOR = "#77736e"


def style_matplotlib():
    """Set uniform typography for the explanatory diagram."""
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": BASE_FS,
        "axes.titlesize": BASE_FS,
        "axes.labelsize": BASE_FS,
        "xtick.labelsize": BASE_FS,
        "ytick.labelsize": BASE_FS,
        "legend.fontsize": BASE_FS,
        "figure.titlesize": BASE_FS,
        "text.color": INK,
        "axes.labelcolor": INK,
        "axes.unicode_minus": True,
        "savefig.facecolor": "white",
    })


def project(points):
    """Project longitudinal distance, transverse distance and elevation."""
    xyz = np.asarray(points, dtype=float)
    return np.column_stack((0.90 * xyz[:, 0] + 0.80 * xyz[:, 1],
                            0.30 * xyz[:, 0] - 0.45 * xyz[:, 1] + 1.20 * xyz[:, 2]))


def polygon(ax, points, color, width=2.2, dashed=False):
    """Draw a filled polygon with a consistent outline."""
    patch = Polygon(points, closed=True, facecolor=color, edgecolor=EDGE,
                    linewidth=width, linestyle=(0, (5, 3)) if dashed else "solid",
                    joinstyle="round")
    ax.add_patch(patch)


def water_shape(ax, kind):
    """Draw the water volume at depth 2h as an exact polyhedron."""
    if kind == "wedge":
        vertices = np.array([[0, -2, 0], [0, 2, 0], [0, -2, 2],
                             [0, 2, 2], [6, -2, 2], [6, 2, 2]])
        faces = [([0, 4, 2], HIGH), ([2, 4, 5, 3], HIGH),
                 ([0, 2, 3, 1], FRONT), ([1, 3, 5], SIDE)]
        bed = project([[0, 2, 0], [6, 2, 2]])
        endpoint = project([[3, 2, 1]])[0]
    else:
        vertices = np.array([[0, 0, 0], [0, -2, 2], [0, 2, 2], [6, 0, 2]])
        faces = [([0, 1, 3], HIGH), ([1, 3, 2], HIGH),
                 ([0, 1, 2], FRONT), ([0, 2, 3], SIDE)]
        bed = project([[0, 0, 0], [6, 0, 2]])
        endpoint = project([[3, 0, 1]])[0]
    for indices, color in faces:
        polygon(ax, project(vertices[indices]), color)
    ax.plot(bed[:, 0], bed[:, 1], color=FLOOR, linewidth=3)
    ax.annotate("Sloping bed", xy=endpoint, xytext=(6.7, -0.6), ha="center",
                arrowprops={"arrowstyle": "->", "color": INK, "lw": 1.5})
    ax.annotate("Dam face", xy=(0.2, 0.9), xytext=(-0.5, -1.45), ha="center",
                arrowprops={"arrowstyle": "->", "color": INK, "lw": 1.5})
    ax.set(xlim=(-2.1, 8.9), ylim=(-1.9, 5.35), aspect="equal")
    ax.axis("off")


def cross_section(ax, kind):
    """Show depth h and 2h in the cross-section immediately upstream of the dam."""
    if kind == "wedge":
        upper = [(-2, 0), (2, 0), (2, 2), (-2, 2)]
        lower = [(-2, 0), (2, 0), (2, 1), (-2, 1)]
        wall = [(-2, 2.4), (-2, 0), (2, 0), (2, 2.4)]
        low_width = 2
        statement = "Width stays constant"
    else:
        upper = [(0, 0), (2, 2), (-2, 2)]
        lower = [(0, 0), (1, 1), (-1, 1)]
        wall = [(-2.4, 2.4), (0, 0), (2.4, 2.4)]
        low_width = 1
        statement = "Width increases with depth"
    polygon(ax, upper, HIGH)
    polygon(ax, lower, LOW, dashed=True)
    wall = np.asarray(wall)
    ax.plot(wall[:, 0], wall[:, 1], color=FLOOR, linewidth=3)
    ax.plot([-2, 2], [2, 2], color=EDGE, linewidth=2.5)
    ax.plot([-low_width, low_width], [1, 1], color=EDGE,
            linewidth=2.5, linestyle=(0, (5, 3)))
    ax.text(-2.7, 2, "2h", va="center", ha="right")
    ax.text(-2.7, 1, "h", va="center", ha="right")
    ax.text(0, -0.65, statement, ha="center", va="center")
    ax.set(xlim=(-3.8, 3.8), ylim=(-0.95, 2.7), aspect="equal")
    ax.axis("off")


def plan_view(ax, kind):
    """Draw the nested water-surface footprints for depth h and 2h."""
    if kind == "wedge":
        upper = [(0, -2), (6, -2), (6, 2), (0, 2)]
        lower = [(0, -2), (3, -2), (3, 2), (0, 2)]
    else:
        upper = [(0, -2), (6, 0), (0, 2)]
        lower = [(0, -1), (3, 0), (0, 1)]
    polygon(ax, upper, HIGH)
    polygon(ax, lower, LOW, dashed=True)
    ax.plot([0, 0], [-2.25, 2.25], color=FLOOR, linewidth=5)
    ax.text(-0.4, 0, "Dam", rotation=90, ha="center", va="center")
    ax.annotate("Upstream", xy=(5.8, 2.65), xytext=(3.3, 2.65),
                ha="left", va="center",
                arrowprops={"arrowstyle": "->", "color": INK, "lw": 1.5})
    ax.text(1.2, 0, "h", ha="center", va="center")
    ax.text(4.5, 0, "2h", ha="center", va="center")
    ax.set(xlim=(-1, 6.8), ylim=(-2.45, 3.15), aspect="equal")
    ax.axis("off")


def main():
    """Render the two shapes with matching geometry and water levels."""
    style_matplotlib()
    width, height = 22, 19.5
    fig = plt.figure(figsize=(width, height))
    gap = 0.47
    margin = 0.55
    col_width = (width - 2 * margin - gap) / 2
    columns = [margin, margin + col_width + gap]
    rows = [(12.3, 5.8), (8.03, 3.8), (2.3, 5.26)]
    for col, kind in enumerate(("wedge", "valley")):
        center = (columns[col] + col_width/2)/width
        name = "Constant-width wedge" if col == 0 else "V-shaped valley"
        fig.text(center, 18.9/height, name, ha="center", va="center", weight="bold")
        for index, (bottom, row_height) in enumerate(rows):
            ax = fig.add_axes([columns[col]/width, bottom/height,
                               col_width/width, row_height/height])
            (water_shape, cross_section, plan_view)[index](ax, kind)
        if col == 0:
            result = "Depth h → 2h: area ×2, volume ×4\nA ∝ h,  V ∝ h²\nβ = 1,  b = 2"
        else:
            result = "Depth h → 2h: area ×4, volume ×8\nA ∝ h²,  V ∝ h³\nβ = 2,  b = 1.5"
        fig.text(center, 1.2/height, result, ha="center", va="center", linespacing=1.45)
    for y, label in ((18.3, "Water volume in 3D at depth 2h"),
                     (12.03, "Cross-section at the dam"),
                     (7.76, "Water surface seen from above")):
        fig.text(0.5, y/height, label, ha="center", va="center")
    fig.text(0.5, 0.18/height, "Same uniform bed slope in both examples. h is water depth at the dam.",
             ha="center", va="center")
    fig.savefig(OUTPUT/'geometry_comparison.png', dpi=300, bbox_inches="tight", pad_inches=0.16,
                metadata={"Software": "Matplotlib"})
    plt.close(fig)


if __name__ == "__main__":
    main()
