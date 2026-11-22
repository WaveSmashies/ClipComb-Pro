# SPDX-License-Identifier: GPL-3.0-or-later
"""Use the host theme for all archive tools; no second theme engine."""
from review_theme import (ACCENT, GREEN, MUTED, PANEL, VIDEO, BORDER, ACCENT_DARK,
                         confirm_action, dark_title, dialog, present, pick_path,
                         reveal_paths, show_error)
def install_theme(root,palette=None):
    from review_theme import install_theme as install_host,DEFAULT_PALETTE
    owner=root._root()
    colors=dict(palette or getattr(owner,'review_palette',DEFAULT_PALETTE))
    # ttk styles are shared by the interpreter. Keep their image ownership on
    # the main Tk root so closing Archive Tools cannot release theme images.
    install_host(owner,colors)
    root.review_palette=colors;root.configure(bg=colors['background'])
    dark_title(root)
