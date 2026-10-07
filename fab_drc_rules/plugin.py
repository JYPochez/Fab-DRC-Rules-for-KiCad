"""Fab DRC Rules for KiCad: a toolbar button in the PCB editor.

One click opens a dialog listing the PCB fabs whose published capabilities
ship with the plugin (fabs/*.json). Pick the fab and a profile (layer count,
copper weight, standard or extra-cost options) and the plugin:

* writes the fab's custom design rules into the project's .kicad_dru, inside
  a marked block, keeping any rule of the user's own after it;
* optionally sets Board Setup > Constraints minimums to the fab's values
  (copper clearance in particular, which must not be a custom rule - see
  rules_gen.py).

A classic pcbnew action plugin (``pcbnew.ActionPlugin``). KiCad's bundled
Python is 3.9, so the code stays 3.9-compatible.
"""

import json
import shutil
import time
import webbrowser
from pathlib import Path

import pcbnew
import wx

from . import rules_gen

PLUGIN_NAME = "Fab DRC Rules"
SETTINGS_FILE = "settings.json"
FABS_FOLDER = "fabs"
RULES_SUFFIX = ".kicad_dru"
BACKUP_SUFFIX = ".kicad_dru.bak-"
EXTRA_COST_TAG = "  (extra cost)"
INFO_WRAP_WIDTH = 720

# Board Setup > Constraints names, for the report.
BOARD_SETTING_LABELS = {
    "m_MinClearance": "Minimum clearance",
    "m_TrackMinWidth": "Minimum track width",
    "m_ViasMinSize": "Minimum via diameter",
    "m_ViasMinAnnularWidth": "Minimum annular width",
    "m_MinThroughDrill": "Minimum through hole",
    "m_HoleClearance": "Hole clearance",
    "m_HoleToHoleMin": "Hole to hole clearance",
    "m_CopperEdgeClearance": "Copper to edge clearance",
    "m_MinSilkTextHeight": "Minimum silk text height",
    "m_MinSilkTextThickness": "Minimum silk text thickness",
}


# ---------------------------------------------------------------------------
# Files

def plugin_dir():
    return Path(__file__).resolve().parent


def load_settings():
    try:
        with open(plugin_dir() / SETTINGS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    try:
        with open(plugin_dir() / SETTINGS_FILE, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=2)
    except OSError:
        pass


def rules_path(board):
    """<project>.kicad_dru beside the board; None for an unsaved board."""
    name = board.GetFileName()
    return Path(name).with_suffix(RULES_SUFFIX) if name else None


def read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def backup(path):
    """Copy of the rules file beside it, stamped; returns the copy's path."""
    target = path.with_name(path.stem + BACKUP_SUFFIX + time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(str(path), str(target))
    return target


# ---------------------------------------------------------------------------
# Board Setup > Constraints

def apply_board_minimums(board, profile, keep_stricter):
    """Sets the design-settings floors; returns report lines 'name: a -> b'."""
    settings = board.GetDesignSettings()
    lines = []
    for attr, value_mm in rules_gen.board_minimums(profile).items():
        if not hasattr(settings, attr):
            continue
        before = getattr(settings, attr)
        after = pcbnew.FromMM(value_mm)
        if keep_stricter and before > after:
            continue
        if before != after:
            setattr(settings, attr, after)
            lines.append("{}: {:g} -> {:g} mm".format(
                BOARD_SETTING_LABELS.get(attr, attr), pcbnew.ToMM(before), value_mm))
    if lines:
        board.SetModified()
    return lines


# ---------------------------------------------------------------------------
# Dialog

class FabDialog(wx.Dialog):
    """Fab and profile choice, a preview, Install / Remove."""

    def __init__(self, parent, board, fabs, settings):
        super().__init__(parent, title=PLUGIN_NAME,
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.board = board
        self.fabs = fabs
        self.settings = settings
        self.layer_count = board.GetCopperLayerCount()
        self.path = rules_path(board)
        self.installed = rules_gen.installed_profile(read_text(self.path)) if self.path else None
        self.profiles = []
        self._build()
        self._select_initial()
        self.SetSize(self.FromDIP(wx.Size(760, 640)))
        self.CentreOnParent()

    # -- layout

    def _build(self):
        pad = self.FromDIP(8)
        root = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(cols=2, vgap=pad, hgap=pad)
        grid.AddGrowableCol(1)
        self.fab_choice = wx.Choice(self, choices=[f.get("name", f["id"]) for f in self.fabs])
        self.profile_choice = wx.Choice(self)
        grid.Add(wx.StaticText(self, label="Fab:"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.fab_choice, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="Profile:"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.profile_choice, 1, wx.EXPAND)
        root.Add(grid, 0, wx.EXPAND | wx.ALL, pad)

        self.status = wx.StaticText(self, label=self._status_text())
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT, pad)

        self.info = wx.StaticText(self, label="")
        root.Add(self.info, 0, wx.EXPAND | wx.ALL, pad)

        self.link = wx.Button(self, label="Open the fab's capabilities page")
        root.Add(self.link, 0, wx.LEFT | wx.RIGHT, pad)

        self.notebook = wx.Notebook(self)
        mono = wx.Font(wx.FontInfo(11).Family(wx.FONTFAMILY_TELETYPE))
        self.values_text = self._preview_page("Values")
        self.rules_text = self._preview_page("Rules written to " + RULES_SUFFIX)
        for ctrl in (self.values_text, self.rules_text):
            ctrl.SetFont(mono)
        root.Add(self.notebook, 1, wx.EXPAND | wx.ALL, pad)

        self.set_board = wx.CheckBox(
            self, label="Also set Board Setup > Constraints minimums (clearance, track, via, holes, edge, silk)")
        self.set_board.SetValue(self.settings.get("set_board_minimums", True))
        self.keep_stricter = wx.CheckBox(self, label="Keep stricter values already set on the board")
        self.keep_stricter.SetValue(self.settings.get("keep_stricter", False))
        root.Add(self.set_board, 0, wx.LEFT | wx.RIGHT, pad)
        root.Add(self.keep_stricter, 0, wx.LEFT | wx.RIGHT | wx.TOP, pad)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.remove_button = wx.Button(self, label="Remove fab rules")
        self.remove_button.Enable(self.installed is not None)
        close_button = wx.Button(self, wx.ID_CANCEL, "Close")
        self.install_button = wx.Button(self, wx.ID_OK, "Install")
        self.install_button.SetDefault()
        buttons.Add(self.remove_button)
        buttons.AddStretchSpacer()
        buttons.Add(close_button, 0, wx.RIGHT, pad)
        buttons.Add(self.install_button)
        root.Add(buttons, 0, wx.EXPAND | wx.ALL, pad)
        self.SetSizer(root)

        self.fab_choice.Bind(wx.EVT_CHOICE, self.on_fab)
        self.profile_choice.Bind(wx.EVT_CHOICE, self.on_profile)
        self.set_board.Bind(wx.EVT_CHECKBOX, self.on_set_board)
        self.link.Bind(wx.EVT_BUTTON, self.on_link)
        self.install_button.Bind(wx.EVT_BUTTON, self.on_install)
        self.remove_button.Bind(wx.EVT_BUTTON, self.on_remove)

    def _preview_page(self, title):
        ctrl = wx.TextCtrl(self.notebook, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        self.notebook.AddPage(ctrl, title)
        return ctrl

    def _status_text(self):
        where = self.path.name if self.path else "(board not saved yet)"
        current = "none"
        if self.installed:
            current = "{} / {}".format(*self.installed)
        return "Board: {} copper layers - rules file: {} - installed: {}".format(
            self.layer_count, where, current)

    # -- selection

    def _select_initial(self):
        wanted = self.installed[0] if self.installed else self.settings.get("last_fab")
        index = next((i for i, f in enumerate(self.fabs) if f["id"] == wanted), 0)
        self.fab_choice.SetSelection(index)
        self._fill_profiles(self.installed[1] if self.installed else None)

    def _fill_profiles(self, wanted_id=None):
        fab = self.fab()
        self.profiles = fab["profiles"]
        labels = [p.get("label", p["id"]) + (EXTRA_COST_TAG if p.get("extra_cost") else "")
                  for p in self.profiles]
        self.profile_choice.Set(labels)
        chosen = next((p for p in self.profiles if p["id"] == wanted_id), None)
        if chosen is None or (self.installed and self.installed[0] != fab["id"]):
            chosen = rules_gen.best_profile(fab, self.layer_count)
        self.profile_choice.SetSelection(self.profiles.index(chosen))
        self._refresh()

    def fab(self):
        return self.fabs[max(self.fab_choice.GetSelection(), 0)]

    def profile(self):
        return self.profiles[max(self.profile_choice.GetSelection(), 0)]

    def _refresh(self):
        fab, profile = self.fab(), self.profile()
        low, high = profile.get("min_layers", 1), profile.get("max_layers", 64)
        lines = ["Data retrieved {}.  {}".format(fab.get("retrieved", "?"), fab.get("notes", ""))]
        if not low <= self.layer_count <= high:
            lines.append("Warning: this profile is for {}-{} layers; the board has {}.".format(
                low, high, self.layer_count))
        self.info.SetLabel("\n".join(lines))
        self.info.Wrap(self.FromDIP(INFO_WRAP_WIDTH))

        values = rules_gen.describe_values(profile)
        notes = profile.get("value_notes") or {}
        if notes:
            values += ["", "Notes:"] + ["  {}: {}".format(k, n) for k, n in notes.items()]
        sources = fab.get("sources") or []
        if sources:
            values += ["", "Sources:"] + ["  " + s for s in sources]
        self.values_text.SetValue("\n".join(values))
        self.rules_text.SetValue(rules_gen.generate_block(fab, profile))
        self.link.Enable(bool(fab.get("url")))
        self.keep_stricter.Enable(self.set_board.GetValue())
        self.Layout()

    # -- events

    def on_fab(self, _event):
        self._fill_profiles()

    def on_profile(self, _event):
        self._refresh()

    def on_set_board(self, _event):
        self.keep_stricter.Enable(self.set_board.GetValue())

    def on_link(self, _event):
        url = self.fab().get("url")
        if url:
            webbrowser.open(url)

    def on_install(self, _event):
        if not self.path:
            wx.MessageBox("Save the board first: the rules file goes beside it.",
                          PLUGIN_NAME, wx.OK | wx.ICON_WARNING, self)
            return
        fab, profile = self.fab(), self.profile()
        existing = read_text(self.path)
        report = []
        try:
            if existing.strip() and rules_gen.installed_profile(existing) is None:
                report.append("Your previous rules file was saved as " + backup(self.path).name
                              + " and its rules kept after the fab's.")
            self.path.write_text(rules_gen.merge(existing, rules_gen.generate_block(fab, profile)),
                                 encoding="utf-8")
        except OSError as exc:
            wx.MessageBox("Could not write {}:\n{}".format(self.path, exc),
                          PLUGIN_NAME, wx.OK | wx.ICON_ERROR, self)
            return
        report.insert(0, "Installed {} - {} in {}.".format(
            fab.get("name", fab["id"]), profile.get("label", profile["id"]), self.path.name))

        if self.set_board.GetValue():
            changes = apply_board_minimums(self.board, profile, self.keep_stricter.GetValue())
            if changes:
                report += ["", "Board Setup > Constraints changed (save the board to keep them):"]
                report += ["  " + line for line in changes]
            else:
                report += ["", "Board Setup > Constraints already matched."]
        report += ["", "Run Inspect > Design Rules Checker to check the board."]

        self.settings.update(last_fab=fab["id"], set_board_minimums=self.set_board.GetValue(),
                             keep_stricter=self.keep_stricter.GetValue())
        save_settings(self.settings)
        pcbnew.Refresh()
        wx.MessageBox("\n".join(report), PLUGIN_NAME, wx.OK | wx.ICON_INFORMATION, self)
        self.EndModal(wx.ID_OK)

    def on_remove(self, _event):
        if not self.path or not self.path.exists():
            return
        if wx.MessageBox("Remove the fab rules from {}?\nYour own rules stay. Board Setup values "
                         "are not changed.".format(self.path.name), PLUGIN_NAME,
                         wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        remaining = rules_gen.remove(read_text(self.path))
        try:
            if remaining is None:
                self.path.unlink()
            else:
                self.path.write_text(remaining, encoding="utf-8")
        except OSError as exc:
            wx.MessageBox("Could not update {}:\n{}".format(self.path, exc),
                          PLUGIN_NAME, wx.OK | wx.ICON_ERROR, self)
            return
        self.EndModal(wx.ID_OK)


# ---------------------------------------------------------------------------
# Action plugin

def pcb_frame():
    """The PCB editor window, as the dialogs' parent."""
    for window in wx.GetTopLevelWindows():
        if window.GetName() == "PcbFrame" or "PCB Editor" in window.GetTitle():
            return window
    return None


class FabDrcRulesPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = PLUGIN_NAME
        self.category = "Design rules"
        self.description = "Install a PCB fab's design rules (DRC) in the current board"
        self.show_toolbar_button = True
        self.icon_file_name = str(plugin_dir() / "icon_24x24.png")
        self.dark_icon_file_name = str(plugin_dir() / "icon_24x24_dark.png")

    def Run(self):
        parent = pcb_frame()
        board = pcbnew.GetBoard()
        fabs, errors = rules_gen.load_fabs(plugin_dir() / FABS_FOLDER)
        if errors:
            wx.MessageBox("Some fab files could not be read:\n" + "\n".join(errors),
                          PLUGIN_NAME, wx.OK | wx.ICON_WARNING, parent)
        if not fabs:
            wx.MessageBox("No fab data found in " + str(plugin_dir() / FABS_FOLDER),
                          PLUGIN_NAME, wx.OK | wx.ICON_ERROR, parent)
            return
        dialog = FabDialog(parent, board, fabs, load_settings())
        try:
            dialog.ShowModal()
        finally:
            dialog.Destroy()
