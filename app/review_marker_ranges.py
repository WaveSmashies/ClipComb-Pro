# SPDX-License-Identifier: GPL-3.0-or-later
"""Bookmark ranges use a source start time and optional duration in seconds."""
import math


def duration(marker):
    try:value=float(marker.get('duration',0))
    except (TypeError,ValueError):return 0.
    return value if math.isfinite(value) and value>0 else 0.


def end(marker):
    return marker['time']+duration(marker)


def boundaries(markers):
    return [value for marker in markers for value in ((marker['time'],end(marker)) if duration(marker) else (marker['time'],))]
