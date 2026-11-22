# SPDX-License-Identifier: GPL-3.0-or-later
"""Source-relative, non-drop-frame timecode and readable source rates."""
import math
from fractions import Fraction

def frame_rate(value):
    try:
        fps=Fraction(str(value)).limit_denominator(1001000)
        if fps>0:return fps
    except (ValueError,ZeroDivisionError,TypeError):pass
    return Fraction(30)

def timecode(seconds,fps=30,frames=True):
    seconds=max(0,float(seconds))
    if frames:
        rate=frame_rate(fps);nominal=max(1,round(float(rate)))
        index=max(0,math.floor(seconds*float(rate)+.50000001))
        whole,sub=divmod(index,nominal)
        tail=f'{sub:0{max(2,len(str(nominal-1)))}d}'
    else:
        whole,sub=divmod(max(0,round(seconds*1000)),1000);tail=f'{sub:03d}'
    minutes,sec=divmod(whole,60);hours,minutes=divmod(minutes,60)
    return (f'{hours:02}:' if hours else '')+f'{minutes:02}:{sec:02}.{tail}'

def fps_text(value):
    fps=frame_rate(value)
    return str(fps.numerator) if fps.denominator==1 else f'{float(fps):.3f}'.rstrip('0').rstrip('.')
