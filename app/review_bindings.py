# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared shortcut validation, contextual dispatch and implicit Delete binding."""
from review_core import DEFAULT_KEYS,DEFAULT_SECONDARY_KEYS

SECTIONS=('shortcuts','shortcuts_secondary')
TRIM_ACTIONS=frozenset(('trim_file','create_trim'))


def sorting_guide(bindings,project=None):
    from review_folders import names
    folders=names(project)
    return ' | '.join(f'{" / ".join(keys_for(bindings,role.lower())) or "Unbound"} - {"Mark clip " if role=="Used" else "Mark "}{folders[role]}'
                     for role in ('Used','Unused','Deleted','Kept'))


def delete_fallback(bindings):
    return not any(key=='Delete' for section in SECTIONS for key in bindings[section].values())


def keys_for(bindings,action):
    keys=list(dict.fromkeys(bindings[section].get(action,'') for section in SECTIONS if bindings[section].get(action,'')))
    if action=='remove_range' and delete_fallback(bindings):keys.append('Delete')
    return keys


def secondary_text(bindings,action):
    value=bindings['shortcuts_secondary'].get(action,'')
    if action=='remove_range' and delete_fallback(bindings):return ' / '.join(filter(None,(value,'Delete')))
    return value


def action_for(bindings,key,mode='review'):
    if not key:return None
    actions=list(dict.fromkeys(action for section in SECTIONS for action,binding in bindings[section].items() if binding==key))
    if len(actions)>1 and set(actions)<=TRIM_ACTIONS:
        return 'create_trim' if mode=='trim' else 'trim_file'
    if actions:return actions[0]
    return 'remove_range' if key=='Delete' and delete_fallback(bindings) else None


def validate(bindings,labels):
    seen={}
    for section in SECTIONS:
        for action,key in bindings[section].items():
            if not key:continue
            previous=seen.setdefault(key,action)
            if previous!=action and not {previous,action}<=TRIM_ACTIONS:
                raise ValueError(f'{key} is already assigned to {labels[previous]}. Choose a different shortcut or clear one slot.')


def default_help(action):
    bindings=dict(shortcuts=DEFAULT_KEYS,shortcuts_secondary=DEFAULT_SECONDARY_KEYS)
    return f'Default: Primary {DEFAULT_KEYS[action] or "blank"}; Secondary {secondary_text(bindings,action) or "blank"}.'
