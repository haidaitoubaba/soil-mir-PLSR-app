from __future__ import annotations

import numpy as np
from scipy.special import inv_boxcox
from scipy.stats import boxcox, yeojohnson

VALID_TRANSFORMS = {"none", "sqrt", "log", "log10", "cbrt", "boxcox", "yeojohnson"}


def apply_transform(y: np.ndarray, method: str) -> tuple[np.ndarray, float | None]:
    y = np.asarray(y, dtype=float)
    method = method.lower().strip()
    if method in ("none", ""):
        return y, None
    if method == "sqrt":
        if np.any(y < 0):
            raise ValueError("sqrt transform requires all reference values >= 0")
        return np.sqrt(y), None
    if method == "log":
        if np.any(y < 0):
            raise ValueError("log transform requires all reference values >= 0")
        return np.log1p(y), None
    if method == "log10":
        if np.any(y < 0):
            raise ValueError("log10 transform requires all reference values >= 0")
        return np.log10(y + 1), None
    if method == "cbrt":
        return np.cbrt(y), None
    if method == "boxcox":
        if np.any(y <= 0):
            raise ValueError("boxcox requires all reference values > 0 (no zeros)")
        transformed, lam = boxcox(y)
        return transformed, float(lam)
    if method == "yeojohnson":
        transformed, lam = yeojohnson(y)
        return transformed, float(lam)
    raise ValueError(
        f"Unknown transform '{method}'. Valid options: none, sqrt, log, log10, cbrt, "
        "boxcox, yeojohnson"
    )


def back_transform(y_t: np.ndarray, method: str, lam: float | None = None) -> np.ndarray:
    y_t = np.asarray(y_t, dtype=float)
    method = method.lower().strip()
    if method in ("none", ""):
        return y_t
    if method == "sqrt":
        return np.clip(y_t, 0, None) ** 2
    if method == "log":
        return np.expm1(y_t)
    if method == "log10":
        return 10**y_t - 1
    if method == "cbrt":
        return y_t**3
    if method == "boxcox":
        return inv_boxcox(y_t, lam)
    if method == "yeojohnson":
        if lam is None:
            raise ValueError("Yeo-Johnson inverse requires lambda")
        result = np.empty_like(y_t)
        positive = y_t >= 0
        if lam == 0:
            result[positive] = np.expm1(y_t[positive])
        else:
            result[positive] = np.expm1(np.log1p(lam * y_t[positive]) / lam)
        if lam == 2:
            result[~positive] = -np.expm1(-y_t[~positive])
        else:
            power = 2 - lam
            result[~positive] = -np.expm1(np.log1p(-power * y_t[~positive]) / power)
        return result
    return y_t
