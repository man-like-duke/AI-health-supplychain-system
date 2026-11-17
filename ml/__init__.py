"""Lightweight supervised stockout prediction for the decision-support app.

The package is deliberately separate from :mod:`src`. The deterministic
analysis in ``src`` remains authoritative; this package only produces
predictive evidence for human review.
"""

from ml.schema import TARGET_COLUMN

__all__ = ["TARGET_COLUMN"]
