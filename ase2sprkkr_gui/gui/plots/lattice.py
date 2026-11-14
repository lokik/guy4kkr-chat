from __future__ import annotations

from itertools import product
from typing import Any, Callable, Dict, Optional, Sequence

import numpy as np
from matplotlib import colormaps
from matplotlib.colors import to_hex

_SITE_ROLE_STYLES = {
    'inactive': {
        'color': '#7cc6ff',
        'edgecolor': '#1c4b73',
        'linewidths': 0.6,
        's': 42,
    },
    'focused': {
        'color': '#8a8a8a',
        'edgecolor': 'none',
        'linewidths': 0.0,
        's': 56,
    },
    'active': {
        'color': '#ff3232',
        'edgecolor': 'black',
        'linewidths': 1.0,
        's': 68,
    },
}

PREVIEW_SITE_STYLE = {
    'edgecolor': 'black',
    'linewidths': 0.9,
    's': 40,
}


def _spacegroup_kinds_from_atoms(atoms: Any, count: int) -> list[Any]:
    arrays = getattr(atoms, 'arrays', {})
    kinds = arrays.get('spacegroup_kinds')
    if kinds is None:
        symbols = list(atoms.get_chemical_symbols())
        if len(symbols) == count:
            return symbols
        return ['atom'] * count
    return list(kinds)


def _kind_key(kind: Any) -> Any:
    """Return a stable, hashable key for a site kind."""
    try:
        hash(kind)
    except Exception:
        return ('repr', repr(kind))
    return kind


def compute_site_colors(atoms: Any) -> Dict[Any, str]:
    scaled = np.asarray(atoms.get_scaled_positions(), dtype=float)
    kinds = _spacegroup_kinds_from_atoms(atoms, len(scaled))

    ordered_kinds: list[Any] = []
    seen_keys: set[Any] = set()
    for kind in kinds:
        key = _kind_key(kind)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        ordered_kinds.append(kind)

    cmap = colormaps.get_cmap('tab20').resampled(
        max(len(ordered_kinds), 1)
    )
    base_colors = list(getattr(cmap, 'colors', []))
    if not base_colors:
        steps = max(len(ordered_kinds), 1)
        base_colors = [cmap(i / max(steps - 1, 1)) for i in range(steps)]

    colors: Dict[Any, str] = {}
    n = len(base_colors)
    for idx, kind in enumerate(ordered_kinds):
        rgba = base_colors[idx % n]
        colors[_kind_key(kind)] = to_hex(rgba)
    return colors


def plot_atoms_preview(
    ax,
    atoms: Optional[Any],
    *,
    canvas=None,
    clear_axes: bool = True,
    axis_on: bool = True,
    fallback_lattice=None,
    hovered_atom_indices: Optional[Sequence[int] | int] = None,
    site_colors: Optional[Dict[Any, str]] = None,
    base_style: Optional[Dict[str, Any]] = None,
    hovered_style: Optional[Dict[str, Any]] = None,
    default_color: str = '#1f77b4',
    extra_draw: Optional[Callable[[Any, Optional[Any], Optional[np.ndarray]], None]] = None,
) -> Dict[Any, str]:
    if clear_axes:
        ax.clear()
    if axis_on:
        ax.set_axis_on()

    lattice = None
    if atoms is not None:
        lattice = np.asarray(atoms.get_cell(), dtype=float)
    elif fallback_lattice is not None:
        lattice = np.asarray(fallback_lattice, dtype=float)

    if lattice is not None:
        plot_lattice(ax, lattice)

    if atoms is None:
        if extra_draw is not None:
            extra_draw(ax, None, lattice)
        if canvas is not None:
            canvas.draw_idle()
        return site_colors or {}

    scaled = np.asarray(atoms.get_scaled_positions(), dtype=float)
    if scaled.size == 0:
        if extra_draw is not None:
            extra_draw(ax, atoms, lattice)
        if canvas is not None:
            canvas.draw_idle()
        return site_colors or {}

    kinds = _spacegroup_kinds_from_atoms(atoms, len(scaled))
    color_map = site_colors if site_colors is not None else compute_site_colors(atoms)

    if hovered_atom_indices is None:
        hovered_set: set[int] = set()
    elif isinstance(hovered_atom_indices, int):
        hovered_set = {hovered_atom_indices}
    else:
        hovered_set = {int(idx) for idx in hovered_atom_indices}
    hovered_set = {idx for idx in hovered_set if 0 <= idx < len(scaled)}

    style = dict(PREVIEW_SITE_STYLE)
    if base_style:
        style.update(base_style)

    grouped_indices: Dict[str, list[int]] = {}
    for idx, kind in enumerate(kinds):
        if idx in hovered_set:
            continue
        key = _kind_key(kind)
        color = color_map.get(key, default_color)
        grouped_indices.setdefault(color, []).append(idx)

    for color, selected_indices in grouped_indices.items():
        if not selected_indices:
            continue
        kind_style = dict(style)
        kind_style['color'] = color
        plot_sites_in_lattice(ax, lattice, scaled[selected_indices], **kind_style)

    focus_style = dict(style)
    focus_style.setdefault('color', 'black')
    focus_style['color'] = 'black'
    focus_style['s'] = int(float(focus_style.get('s', 40)) * 1.5)
    if hovered_style:
        focus_style.update(hovered_style)

    for idx in sorted(hovered_set):
        plot_sites_in_lattice(ax, lattice, scaled[idx], **focus_style)

    if extra_draw is not None:
        extra_draw(ax, atoms, lattice)

    if canvas is not None:
        canvas.draw_idle()

    return color_map


def plot_structure_axis_projection(ax, atoms: Any, axis: int, *, canvas=None) -> None:
    """Plot a structure projected along one selected lattice-vector axis."""
    ax.clear()

    lattice = np.asarray(atoms.get_cell(), dtype=float)
    horizontal = lattice[axis].copy()
    horizontal_norm = float(np.linalg.norm(horizontal))
    if horizontal_norm <= 1e-12:
        raise ValueError("Selected build axis has zero length.")
    horizontal /= horizontal_norm

    transverse = []
    for index in range(3):
        if index == axis:
            continue
        candidate = lattice[index].copy()
        candidate -= np.dot(candidate, horizontal) * horizontal
        norm = float(np.linalg.norm(candidate))
        if norm > 1e-12:
            transverse.append((norm, candidate / norm))
    if not transverse:
        raise ValueError("Cannot find a direction perpendicular to the build axis.")
    vertical = max(transverse, key=lambda item: item[0])[1]

    corners = np.asarray([
        i * lattice[0] + j * lattice[1] + k * lattice[2]
        for i in (0, 1)
        for j in (0, 1)
        for k in (0, 1)
    ])
    projected_corners = np.column_stack(
        (corners @ horizontal, corners @ vertical)
    )
    for start, end in edge_indices:
        edge = projected_corners[[start, end]]
        ax.plot(
            edge[:, 0], edge[:, 1], color="black", linewidth=0.8, zorder=1
        )

    positions = np.asarray(atoms.get_positions(), dtype=float)
    projected = np.column_stack(
        (positions @ horizontal, positions @ vertical)
    )
    symbols = np.asarray(atoms.get_chemical_symbols())
    for symbol in dict.fromkeys(symbols.tolist()):
        selected = symbols == symbol
        ax.scatter(
            projected[selected, 0],
            projected[selected, 1],
            s=40,
            edgecolors="black",
            linewidths=0.9,
            label=symbol,
            zorder=2,
        )

    all_points = np.vstack((projected_corners, projected))
    mins = all_points.min(axis=0)
    maxs = all_points.max(axis=0)
    spans = maxs - mins
    padding = np.maximum(spans * 0.03, 0.05)
    ax.set_xlim(mins[0] - padding[0], maxs[0] + padding[0])
    ax.set_ylim(mins[1] - padding[1], maxs[1] + padding[1])
    ax.set_aspect("auto")
    ax.set_axis_off()
    ax.set_in_layout(False)
    ax.set_position([0.01, 0.03, 0.98, 0.94])
    if canvas is not None:
        canvas.draw_idle()


def _cubic_plot_bounds(corners, padding=0.05):
    """Return equally sized axis limits around eight 3D cell corners."""
    corners = np.asarray(corners)
    if corners.shape != (8, 3):
        raise ValueError("corners must have shape (8, 3)")
    if padding < 0:
        raise ValueError("padding must be non-negative")

    min_corner = corners.min(axis=0)
    max_corner = corners.max(axis=0)
    max_side = (max_corner - min_corner).max()
    center = (max_corner + min_corner) / 2
    half_side = (0.5 + padding) * max_side
    return center - half_side, center + half_side


corner_indices = np.array(list(product((0,1), repeat=3))).T
edge_indices =np.array([(0,1),(0,2),(0,4),(7,6),(7,5),(7,3),(1,3),(1,5),(2,3),(2,6),(4,5),(4,6)])


def plot_lattice(ax, lattice):
    """
    Plot a lattice defined by its vectors on a given 3D axis.

    Parameters:
        ax: matplotlib 3D axis
        lattice: np.array of shape [3,3] - lattice vectors as rows
    """

    ax.figure.suptitle("")

    # draw cell
    corners = corner_indices.T @ lattice

    edges = corners[edge_indices]
    for edge in edges:
            ax.plot(edge[:, 0], edge[:, 1], edge[:, 2], color='black', linewidth=0.8)

    ax.set_xticks([]); ax.set_yticks([]); ax.set_zticks([])
    mn,mx = _cubic_plot_bounds(corners)
    ax.set_xlim(mn[0], mx[0])
    ax.set_ylim(mn[1], mx[1])
    ax.set_zlim(mn[2], mx[2])

def plot_sites_in_lattice(ax, lattice, points, *, role: str | None = None, **kwargs):
    """Plot atomic sites inside a lattice using role-based styling.

    Parameters
    ----------
    ax
        Matplotlib 3D axis to draw on.
    lattice
        ``(3, 3)`` array (rows are lattice vectors) or ``False``/``None`` to skip conversion.
    points
        Fractional coordinates ``(N, 3)`` or an iterable of such arrays.
    role
        Optional semantic role: ``'inactive'``, ``'focused'``, or ``'active'`` to apply
        consistent coloring with the Qt space-group selector.
    kwargs
        Forwarded to ``ax.scatter`` and override role defaults when provided.
    """
    if isinstance(points, (list, tuple)):
        if not points:
            return
        points = np.vstack(points)

    points = np.asarray(points, dtype=float)
    if points.size == 0:
        return
    if points.ndim == 1:
        if points.shape[0] != 3:
            return
        points = points.reshape(1, 3)

    config = {
        's': 25,
        'depthshade': False,
    }

    if role:
        style = _SITE_ROLE_STYLES.get(role)
        if style:
            for key, value in style.items():
                config.setdefault(key, value)

    config.update(kwargs)

    if 'color' not in config:
        config['color'] = 'red'

    if lattice is not False and lattice is not None:
        points = np.dot(points, lattice)

    ax.scatter(*points.T, **config)
