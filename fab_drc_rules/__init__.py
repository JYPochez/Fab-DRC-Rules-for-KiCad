# SPDX-License-Identifier: GPL-3.0-or-later
"""Fab DRC Rules for KiCad: registers the toolbar button (see plugin.py)."""

from .plugin import FabDrcRulesPlugin

FabDrcRulesPlugin().register()
