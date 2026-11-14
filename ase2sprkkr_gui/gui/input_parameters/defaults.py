"""Presentation metadata derived from actual option defaults, never GUI presets."""
import numpy as np


def default_text(value):
    """Format a backend default for a placeholder without parsing or storing it."""
    if value is None:
        return 'Not set'
    if isinstance(value, np.ndarray):
        value = value.tolist()
    text = format(value, '.10g') if isinstance(value, float) else str(value)
    return f'Default: {text}'
