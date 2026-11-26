"""Synthetic 2-D festival venue: rectangular boundary with five activity zones.

The venue is an unobstructed rectangle. Buildings, obstacles and body
attenuation are *not* modelled. Coordinates are in metres with the origin at
the bottom-left corner.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

CIRCULATION = -1  # zone index used for open circulation space


@dataclass(frozen=True)
class Zone:
    name: str
    x0: float
    x1: float
    y0: float
    y1: float

    @property
    def area(self) -> float:
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    def contains(self, xy: np.ndarray) -> np.ndarray:
        x, y = xy[..., 0], xy[..., 1]
        return (x >= self.x0) & (x <= self.x1) & (y >= self.y0) & (y <= self.y1)

    def sample_point(self, rng: np.random.Generator, margin: float = 0.0) -> np.ndarray:
        """Uniform random point inside the zone, optionally away from its edges."""
        mx = min(margin, (self.x1 - self.x0) / 4)
        my = min(margin, (self.y1 - self.y0) / 4)
        return np.array([rng.uniform(self.x0 + mx, self.x1 - mx),
                         rng.uniform(self.y0 + my, self.y1 - my)])


class Venue:
    """Venue geometry plus zone lookup helpers."""

    def __init__(self, venue_cfg: dict):
        self.width = float(venue_cfg["width_m"])
        self.height = float(venue_cfg["height_m"])
        self.zones: list[Zone] = [
            Zone(name, float(z["x"][0]), float(z["x"][1]), float(z["y"][0]), float(z["y"][1]))
            for name, z in venue_cfg["zones"].items()
        ]
        self.zone_names = [z.name for z in self.zones]
        self.index = {z.name: i for i, z in enumerate(self.zones)}
        self._check_overlap()

    @property
    def area(self) -> float:
        return self.width * self.height

    def _check_overlap(self) -> None:
        for i, a in enumerate(self.zones):
            for b in self.zones[i + 1:]:
                if a.x0 < b.x1 and b.x0 < a.x1 and a.y0 < b.y1 and b.y0 < a.y1:
                    raise ValueError(f"Zones '{a.name}' and '{b.name}' overlap.")

    def zone_of(self, xy: np.ndarray) -> np.ndarray:
        """Zone index for each point (``CIRCULATION`` if in open space)."""
        out = np.full(xy.shape[:-1], CIRCULATION, dtype=np.int8)
        for i, zone in enumerate(self.zones):
            out[zone.contains(xy)] = i
        return out

    def clip(self, xy: np.ndarray) -> np.ndarray:
        """Clip points to the venue boundary."""
        out = np.array(xy, dtype=float, copy=True)
        out[..., 0] = np.clip(out[..., 0], 0.0, self.width)
        out[..., 1] = np.clip(out[..., 1], 0.0, self.height)
        return out

    def inside(self, xy: np.ndarray, tol: float = 1e-9) -> np.ndarray:
        return ((xy[..., 0] >= -tol) & (xy[..., 0] <= self.width + tol)
                & (xy[..., 1] >= -tol) & (xy[..., 1] <= self.height + tol))

    def density_per_1000m2(self, node_count: int) -> float:
        return node_count / self.area * 1000.0
