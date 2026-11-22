# SPDX-License-Identifier: GPL-3.0-or-later
"""Readable scan labels shared by the review and archive workspaces."""
import re


def display(message,mode='Full speed'):
    match=re.search(r'(Indexed|Compared) (\d+)/(\d+)(?: · (.*))?',message)
    if match:
        label=f'{match[1]} {match[2]}/{match[3]}'
        if match[4]:label=match[4]+' · '+label
        fraction=int(match[2])/max(1,int(match[3]))
        return label+' · '+mode,(70*fraction if match[1]=='Indexed' else 70+29*fraction)
    return message+' · '+mode,None
