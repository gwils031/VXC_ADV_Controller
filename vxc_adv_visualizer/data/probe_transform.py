"""Probe coordinate transformation for mounting pitch/roll/yaw misalignment.

Transforms 3D ADV velocity measurements from probe-head coordinate frame to
flume-aligned coordinate frame using a Tait-Bryan Euler angle rotation matrix.
"""

import math
import logging
from pathlib import Path
from typing import Sequence, Tuple, List, Optional
import numpy as np
import yaml

logger = logging.getLogger(__name__)


def build_rotation_matrix(roll_deg: float = 0.0, pitch_deg: float = 0.0, yaw_deg: float = 0.0) -> np.ndarray:
    """Build 3D rotation matrix mapping probe coordinates to flume coordinates.

    Convention:
        - Roll (phi): rotation about X axis (streamwise)
        - Pitch (theta): rotation about Y axis (transverse)
        - Yaw (psi): rotation about Z axis (vertical)
        R = R_z(psi) * R_y(theta) * R_x(phi)

    Args:
        roll_deg: Roll angle in degrees.
        pitch_deg: Pitch angle in degrees.
        yaw_deg: Yaw angle in degrees.

    Returns:
        3x3 orthogonal rotation matrix.
    """
    if roll_deg == 0.0 and pitch_deg == 0.0 and yaw_deg == 0.0:
        return np.eye(3, dtype=float)

    phi = math.radians(roll_deg)
    theta = math.radians(pitch_deg)
    psi = math.radians(yaw_deg)

    # Rotation about X (roll)
    Rx = np.array([
        [1.0, 0.0, 0.0],
        [0.0, math.cos(phi), -math.sin(phi)],
        [0.0, math.sin(phi), math.cos(phi)],
    ], dtype=float)

    # Rotation about Y (pitch)
    Ry = np.array([
        [math.cos(theta), 0.0, math.sin(theta)],
        [0.0, 1.0, 0.0],
        [-math.sin(theta), 0.0, math.cos(theta)],
    ], dtype=float)

    # Rotation about Z (yaw)
    Rz = np.array([
        [math.cos(psi), -math.sin(psi), 0.0],
        [math.sin(psi), math.cos(psi), 0.0],
        [0.0, 0.0, 1.0],
    ], dtype=float)

    # Total rotation matrix: R = Rz * Ry * Rx
    return Rz @ Ry @ Rx


def transform_velocity_vectors(
    u: Sequence[float],
    v: Sequence[float],
    w: Sequence[float],
    roll_deg: float = 0.0,
    pitch_deg: float = 0.0,
    yaw_deg: float = 0.0,
) -> Tuple[List[float], List[float], List[float]]:
    """Transform 3D velocity series from probe frame to flume frame.

    Args:
        u: Velocity along probe X axis (m/s).
        v: Velocity along probe Y axis (m/s).
        w: Velocity along probe Z axis (m/s).
        roll_deg: Probe mounting roll in degrees.
        pitch_deg: Probe mounting pitch in degrees.
        yaw_deg: Probe mounting yaw in degrees.

    Returns:
        Tuple of (u_flume, v_flume, w_flume) lists.
    """
    if u is None or v is None or w is None or len(u) == 0 or len(v) == 0 or len(w) == 0:
        return list(u) if u is not None else [], list(v) if v is not None else [], list(w) if w is not None else []

    # Fast path for zero rotation (identity)
    if roll_deg == 0.0 and pitch_deg == 0.0 and yaw_deg == 0.0:
        return list(u), list(v), list(w)

    n = min(len(u), len(v), len(w))
    probe_coords = np.column_stack([
        np.asarray(u[:n], dtype=float),
        np.asarray(v[:n], dtype=float),
        np.asarray(w[:n], dtype=float),
    ])

    R = build_rotation_matrix(roll_deg, pitch_deg, yaw_deg)
    # v_flume = (R @ v_probe^T)^T = v_probe @ R^T
    flume_coords = probe_coords @ R.T

    return flume_coords[:, 0].tolist(), flume_coords[:, 1].tolist(), flume_coords[:, 2].tolist()


def load_probe_orientation(config_path: Optional[Path] = None) -> Tuple[float, float, float]:
    """Load probe mounting orientation angles from experiment_config.yaml.

    Args:
        config_path: Optional path to experiment_config.yaml.

    Returns:
        Tuple of (roll_deg, pitch_deg, yaw_deg). Defaults to (0.0, 0.0, 0.0).
    """
    if config_path is None:
        config_path = Path(__file__).resolve().parents[1] / "config" / "experiment_config.yaml"
        if not config_path.exists():
            config_path = Path("config/experiment_config.yaml")

    if not config_path.exists():
        return 0.0, 0.0, 0.0

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        orient = cfg.get("probe_orientation", {})
        roll = float(orient.get("roll_deg", 0.0))
        pitch = float(orient.get("pitch_deg", 0.0))
        yaw = float(orient.get("yaw_deg", 0.0))
        return roll, pitch, yaw
    except Exception as e:
        logger.warning(f"Could not read probe_orientation from {config_path}: {e}")
        return 0.0, 0.0, 0.0
