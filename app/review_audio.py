# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio layout choices shared by the reviewer and interchange preparation."""
from pathlib import Path
from review_core import profile_for_name

DATE_PROFILES=('Auto by date','Modern OBS','Legacy OBS')
def profile_choices(date_enabled):
    return (['Auto by date'] if date_enabled else [])+['Configured tracks','File track names']+(['Modern OBS','Legacy OBS'] if date_enabled else [])

def selected_profile(value,cfg,date_enabled):
    return value if value in profile_choices(date_enabled) else (cfg['default_profile'] if cfg['default_profile'] in profile_choices(date_enabled) else 'Configured tracks')

def effective_profile(filename,value,cfg,date_enabled):
    value=selected_profile(value,cfg,date_enabled)
    return profile_for_name(Path(filename).name,cfg['layout_change']) if value=='Auto by date' else value

def layout_key(profile):
    return {'Legacy OBS':'legacy','Modern OBS':'modern','Configured tracks':'configured'}.get(profile)

def track_names(filename,value,cfg,date_enabled):
    key=layout_key(effective_profile(filename,value,cfg,date_enabled))
    return cfg[key+'_names'].split('|') if key else []
