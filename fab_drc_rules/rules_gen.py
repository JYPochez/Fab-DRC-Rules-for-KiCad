# SPDX-License-Identifier: GPL-3.0-or-later
"""Turns one fab profile (fabs/<id>.json) into KiCad custom design rules.

No pcbnew import here, so the generator can be tested with any Python 3.9+.

Why clearance and track width are not custom rules
--------------------------------------------------
KiCad resolves a custom rule as "winner takes all": the last matching rule
for a constraint type wins, and custom rules come after the net-class rules.
An unconditioned ``clearance`` rule would therefore *replace* every net-class
clearance with the fab's minimum (a 0.5 mm high-voltage class would silently
drop to 0.1 mm). The copper-to-copper clearance goes into Board Setup >
Constraints instead, which KiCad always enforces as a floor under the
net-class values. Track width has the same floor there, and per-layer
minimums (outer/inner) are rules because net classes only give an opt value.
"""

import json
import re
from pathlib import Path

BEGIN_MARK = "# >>> fab_drc_rules: begin"
END_MARK = "# <<< fab_drc_rules: end"
VERSION_LINE = "(version 1)"

# Values the Board Setup > Constraints page receives (see board_minimums).
VALUE_KEYS = (
    "track_width", "clearance", "inner_track_width", "inner_clearance",
    "via_drill", "via_diameter", "via_annular_ring",
    "pth_drill", "pth_annular_ring", "npth_drill", "max_drill",
    "hole_to_hole", "hole_to_copper", "pth_hole_to_copper", "edge_clearance",
    "silk_line_width", "silk_text_height", "silk_to_pad",
    "mask_bridge", "mask_expansion",
    "plated_slot_width", "npth_slot_width", "castellated_hole",
    "smd_pad_to_pad",
)

COND_VIA = "A.Type == 'Via' && !A.isMicroVia()"
COND_PTH = "A.Type == 'Pad' && A.isPlated()"
COND_PTH_EITHER = "(A.Type == 'Pad' && A.isPlated()) || (B.Type == 'Pad' && B.isPlated())"
COND_NPTH = "A.Type == 'Pad' && !A.isPlated()"
COND_SLOT = "A.Hole_Size_X != A.Hole_Size_Y"
COND_CASTELLATED = "A.Type == 'Pad' && A.Fabrication_Property == 'Castellated pad'"
COND_SILK_TEXT = "A.Type == 'Text' || A.Type == 'Text Box'"
LAYER_SILK = "?.Silkscreen"
# Silkscreen against pads is tested on the mask layer (the pad openings).
LAYER_MASK = "?.Mask"
LAYER_KEYWORDS = ("outer", "inner")


# ---------------------------------------------------------------------------
# Fab data

def load_fabs(folder):
    """Every fabs/*.json, sorted by display name. Broken files are skipped and
    reported in the second list, so one bad file never hides the others."""
    fabs, errors = [], []
    for path in sorted(Path(folder).glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                fab = json.load(handle)
            if not fab.get("profiles"):
                raise ValueError("no profiles")
            fabs.append(fab)
        except (OSError, ValueError) as exc:
            errors.append("{}: {}".format(path.name, exc))
    fabs.sort(key=lambda fab: fab.get("name", fab.get("id", "")).lower())
    return fabs, errors


def best_profile(fab, layer_count):
    """The standard-price profile whose layer range holds the board's layer
    count, else the first standard-price profile, else the first one."""
    profiles = fab["profiles"]
    for want_standard in (True, False):
        for profile in profiles:
            if want_standard and profile.get("extra_cost"):
                continue
            low = profile.get("min_layers", 1)
            high = profile.get("max_layers", 64)
            if low <= layer_count <= high:
                return profile
    standard = [p for p in profiles if not p.get("extra_cost")]
    return (standard or profiles)[0]


def _val(profile, key):
    value = profile.get("values", {}).get(key)
    return value if isinstance(value, (int, float)) and value > 0 else None


def _mm(value):
    text = "{:.4f}".format(value).rstrip("0").rstrip(".")
    return text + "mm"


def _min_of(*values):
    present = [v for v in values if v is not None]
    return min(present) if present else None


# ---------------------------------------------------------------------------
# Rule text

def _rule(name, constraints, condition=None, layer=None):
    lines = ['(rule "{}"'.format(name)]
    if layer in LAYER_KEYWORDS:
        # A quoted "outer" is read as a layer name, and KiCad then silently
        # drops the whole rule file.
        lines.append("\t(layer {})".format(layer))
    elif layer:
        lines.append('\t(layer "{}")'.format(layer))
    if condition:
        lines.append('\t(condition "{}")'.format(condition))
    for constraint in constraints:
        lines.append("\t" + constraint)
    lines.append(")")
    return "\n".join(lines)


def _hole_size(minimum, maximum):
    parts = []
    if minimum is not None:
        parts.append("(min {})".format(_mm(minimum)))
    if maximum is not None:
        parts.append("(max {})".format(_mm(maximum)))
    return "(constraint hole_size {})".format(" ".join(parts)) if parts else None


def _constraint(kind, minimum):
    if minimum is None:
        return None
    return "(constraint {} (min {}))".format(kind, _mm(minimum))


def _rules_for(profile, tag):
    """(rule text) list, generic rules first: in KiCad the later rule wins."""
    v = lambda key: _val(profile, key)  # noqa: E731
    max_drill = v("max_drill")
    rules = []

    def add(name, constraints, condition=None, layer=None):
        constraints = [c for c in constraints if c]
        if constraints:
            rules.append(_rule("{}: {}".format(tag, name), constraints, condition, layer))

    # Copper geometry
    add("track width, outer layers", [_constraint("track_width", v("track_width"))],
        layer="outer")
    add("track width, inner layers", [_constraint("track_width", v("inner_track_width"))],
        layer="inner")

    # Holes, generic to specific
    add("hole to hole", [_constraint("hole_to_hole", v("hole_to_hole"))])
    add("hole to copper", [_constraint("hole_clearance", v("hole_to_copper"))])
    add("plated pad hole to copper", [_constraint("hole_clearance", v("pth_hole_to_copper"))],
        condition=COND_PTH_EITHER)
    add("copper to board edge", [_constraint("edge_clearance", v("edge_clearance"))])
    add("plated hole (PTH pad)",
        [_hole_size(v("pth_drill"), max_drill),
         _constraint("annular_width", v("pth_annular_ring"))],
        condition=COND_PTH)
    add("non-plated hole (NPTH)", [_hole_size(v("npth_drill"), max_drill)],
        condition=COND_NPTH)
    add("via", [_hole_size(v("via_drill"), max_drill),
                _constraint("via_diameter", v("via_diameter")),
                _constraint("annular_width", v("via_annular_ring"))],
        condition=COND_VIA)
    add("plated slot width", [_hole_size(v("plated_slot_width"), None)],
        condition="{} && {}".format(COND_PTH, COND_SLOT))
    add("non-plated slot width", [_hole_size(v("npth_slot_width"), None)],
        condition="{} && {}".format(COND_NPTH, COND_SLOT))
    add("castellated hole", [_hole_size(v("castellated_hole"), max_drill)],
        condition=COND_CASTELLATED)

    # Silkscreen
    add("silkscreen text",
        [_constraint("text_thickness", v("silk_line_width")),
         _constraint("text_height", v("silk_text_height"))],
        condition=COND_SILK_TEXT, layer=LAYER_SILK)
    add("silkscreen to pad", [_constraint("silk_clearance", v("silk_to_pad"))],
        layer=LAYER_MASK)
    return rules


def _header(fab, profile):
    v = lambda key: _val(profile, key)  # noqa: E731
    lines = [
        "{} fab=\"{}\" profile=\"{}\"".format(BEGIN_MARK, fab["id"], profile["id"]),
        "# Managed by the Fab DRC Rules plugin: everything up to the end mark is",
        "# replaced when a fab is installed again. Put your own rules after it.",
        "#",
        "# Fab:      {}".format(fab.get("name", fab["id"])),
        "# Profile:  {}".format(profile.get("label", profile["id"])),
        "# Data:     retrieved {} from {}".format(fab.get("retrieved", "?"), fab.get("url", "?")),
    ]
    if profile.get("extra_cost"):
        lines.append("# NOTE:     this profile uses options the fab charges extra for.")
    clearance = v("clearance")
    inner = v("inner_clearance")
    lines += [
        "#",
        "# Copper clearance is NOT a rule here (a custom clearance rule would",
        "# override every net class). It belongs in Board Setup > Constraints:",
        "#   minimum clearance  {}{}".format(
            _mm(clearance) if clearance else "(not published)",
            "  (inner layers: {})".format(_mm(inner)) if inner else ""),
    ]
    pad_gap = v("smd_pad_to_pad")
    if pad_gap:
        lines.append("#   SMD pad to pad     {}".format(_mm(pad_gap)))
    bridge = v("mask_bridge")
    if bridge:
        lines.append("#   mask min web width {}".format(_mm(bridge)))
    lines.append("#")
    return lines


def generate_block(fab, profile):
    """The managed block: begin mark, header comments, rules, end mark."""
    tag = fab.get("name", fab["id"])
    parts = ["\n".join(_header(fab, profile))]
    parts += _rules_for(profile, tag)
    parts.append(END_MARK)
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# The .kicad_dru file

_BLOCK_RE = re.compile(
    re.escape(BEGIN_MARK) + r".*?" + re.escape(END_MARK) + r"[^\n]*\n?", re.S)
_VERSION_RE = re.compile(r"^\s*\(version\s+\d+\)\s*\n?", re.M)


def installed_profile(text):
    """(fab id, profile id) of the managed block in a .kicad_dru text, or None."""
    match = re.search(re.escape(BEGIN_MARK) + r' fab="([^"]*)" profile="([^"]*)"', text or "")
    return (match.group(1), match.group(2)) if match else None


def strip_block(text):
    """The text without the managed block (user rules kept as they are)."""
    return _BLOCK_RE.sub("", text or "")


def merge(existing, block):
    """New file text: version line, managed block, then the user's own rules
    (after the block, so they take precedence over the fab's)."""
    user = strip_block(existing)
    user = _VERSION_RE.sub("", user, count=1).strip("\n")
    out = VERSION_LINE + "\n\n" + block
    if user.strip():
        out += "\n" + user + "\n"
    return out


def remove(existing):
    """File text without the managed block; None when nothing is left but the
    version line (the caller then deletes the file)."""
    user = _VERSION_RE.sub("", strip_block(existing), count=1).strip()
    return VERSION_LINE + "\n\n" + user + "\n" if user else None


# ---------------------------------------------------------------------------
# Board Setup > Constraints

def board_minimums(profile):
    """{BOARD_DESIGN_SETTINGS attribute: value in mm} for the profile. Each is
    the loosest value any layer allows: the per-layer limits are custom rules,
    and a floor stricter than one of them would contradict it."""
    v = lambda key: _val(profile, key)  # noqa: E731
    wanted = {
        "m_MinClearance": v("clearance"),
        "m_TrackMinWidth": _min_of(v("track_width"), v("inner_track_width")),
        "m_ViasMinSize": v("via_diameter"),
        "m_ViasMinAnnularWidth": _min_of(v("via_annular_ring"), v("pth_annular_ring")),
        "m_MinThroughDrill": _min_of(v("via_drill"), v("pth_drill")),
        "m_HoleClearance": v("hole_to_copper"),
        "m_HoleToHoleMin": v("hole_to_hole"),
        "m_CopperEdgeClearance": v("edge_clearance"),
        "m_MinSilkTextHeight": v("silk_text_height"),
        "m_MinSilkTextThickness": v("silk_line_width"),
    }
    return {key: value for key, value in wanted.items() if value is not None}


def describe_values(profile):
    """Readable 'key: value' lines for the dialog."""
    lines = []
    for key in VALUE_KEYS:
        value = _val(profile, key)
        if value is not None:
            lines.append("{:<20} {}".format(key.replace("_", " "), _mm(value)))
    return lines
