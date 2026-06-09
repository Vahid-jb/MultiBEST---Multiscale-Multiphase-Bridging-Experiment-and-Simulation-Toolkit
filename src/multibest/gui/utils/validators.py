# SPDX-FileCopyrightText: 2026 bright-ideas-clan
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
multibest.gui.utils/validators.py
=============================

Centralised QValidator subclasses for every free-text QLineEdit used across
the MultiBEST sub-interface GUIs.

Adjusting patterns
------------------
All regular-expression strings live in the **PATTERNS** dict below.
Change a pattern there and every widget that uses the corresponding validator
class will pick it up automatically – you never need to touch the individual
GUI files.

Usage
-----
    from multibest.gui.utils.validators import apply_validator, FloatTripletValidator

    apply_validator(self.my_line_edit, FloatTripletValidator())

``apply_validator`` connects a ``textChanged`` slot that colours the widget
border green (Acceptable), default (Intermediate / empty) or red (Invalid).
"""

from __future__ import annotations

import periodictable
from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator, QValidator
from PySide6.QtWidgets import QLineEdit

# ---------------------------------------------------------------------------
# ── Easily-adjustable pattern registry ──────────────────────────────────────
# ---------------------------------------------------------------------------
# Each entry maps a logical name to the regex string used by the validator.
# Anchoring (^…$) is added automatically in the validator constructors.
#
# Notation used in comments:
#   FLOAT  = optional sign, integer part, optional decimal, optional exponent
#   INT    = optional sign, digits only
#   SEP    = ", " or ","  (the patterns allow optional whitespace around commas)
# ---------------------------------------------------------------------------

#: A single float in any notation (e.g. 1e37, -3.14, 0.05)
_FLOAT = r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
#: A non-negative decimal float (no sign)
_UFLOAT = r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
#: A plain integer (optional sign + digits)
_INT = r"[+-]?\d+"
#: Separator: comma with optional surrounding whitespace
_SEP = r"\s*,\s*"

_VALID_SYMBOLS = [el.symbol for el in periodictable.elements if el.symbol != "n"]

PATTERNS: dict[str, str] = {
    # -- element lists -------------------------------------------------------
    # Built dynamically from valid atomic symbols
    "element_list": rf"\s*(?:{'|'.join(_VALID_SYMBOLS)})(?:{_SEP}(?:{'|'.join(_VALID_SYMBOLS)}))*\s*",
    # -- numeric triplets ----------------------------------------------------
    # Three floats separated by commas, optional outer whitespace
    "float_triplet": rf"\s*{_FLOAT}{_SEP}{_FLOAT}{_SEP}{_FLOAT}\s*",
    # Three integers separated by commas, optional outer whitespace
    "int_triplet": rf"\s*{_INT}{_SEP}{_INT}{_SEP}{_INT}\s*",
    # -- numeric pairs -------------------------------------------------------
    # Two floats separated by a comma (e.g. "10, 90")
    "float_pair": rf"{_FLOAT}{_SEP}{_FLOAT}",
    # -- single values -------------------------------------------------------
    # Any single float, including scientific notation (e.g. "1e37")
    "scientific_float": _FLOAT,
    # -- structured key-value lists ------------------------------------------
    # Debye-Waller factors: "Elem=float" pairs, comma-separated
    # e.g. "Zn=0.5, Cu=0.6"
    "debye_waller": rf"[A-Za-z]+={_UFLOAT}(?:{_SEP}[A-Za-z]+={_UFLOAT})*",
    # -- structured space-separated lists ------------------------------------
    # Atom masses / IR charges: "Elem value" pairs, separated by semicolons
    # e.g. "C 12.011; H 1.008"
    "mass_charge_list": rf"[A-Za-z]+\s+{_FLOAT}(?:\s*;\s*[A-Za-z]+\s+{_FLOAT})*",
    # -- integer space list --------------------------------------------------
    # Space-separated positive integers (e.g. "1 2")
    "space_int_list": r"\d+(?:\s+\d+)*",
    # -- filename ------------------------------------------------------------
    # Any string that does not contain path separators
    "filename": r"[^/\\]+",
}


# ---------------------------------------------------------------------------
# Validator classes
# ---------------------------------------------------------------------------


def _make_validator(pattern_key: str) -> QRegularExpressionValidator:
    """Return a QRegularExpressionValidator anchored to the full string."""
    pattern = PATTERNS[pattern_key]
    return QRegularExpressionValidator(QRegularExpression(rf"^(?:{pattern})?$"))


class ElementListValidator(QRegularExpressionValidator):
    """
    Validates a comma-separated list of element symbols.

    Examples of *Acceptable* input:  ``Cu``  ``Cu, Zn``  ``Fe,Ni,Cr``
    """

    def __init__(self, parent=None):
        regex = QRegularExpression(rf"^(?:{PATTERNS['element_list']})?$")
        super().__init__(regex, parent)


class FloatTripletValidator(QRegularExpressionValidator):
    """
    Validates three comma-separated floating-point numbers.

    Examples: ``0.05, 0.05, 0.05``  ``-1, 0, 0``  ``39.84, 0, 0``
    """

    def __init__(self, parent=None):
        regex = QRegularExpression(rf"^(?:{PATTERNS['float_triplet']})?$")
        super().__init__(regex, parent)


class IntTripletValidator(QRegularExpressionValidator):
    """
    Validates three comma-separated integers.

    Examples: ``1, 0, 0``  ``0, 0, 1``  ``-1, 2, 0``
    """

    def __init__(self, parent=None):
        regex = QRegularExpression(rf"^(?:{PATTERNS['int_triplet']})?$")
        super().__init__(regex, parent)


class FloatPairValidator(QRegularExpressionValidator):
    """
    Validates two comma-separated floating-point numbers.

    Examples: ``10, 90``  ``0.5, 180.0``
    """

    def __init__(self, parent=None):
        regex = QRegularExpression(rf"^(?:{PATTERNS['float_pair']})?$")
        super().__init__(regex, parent)


class ScientificFloatValidator(QRegularExpressionValidator):
    """
    Validates a single float in any notation, including scientific.

    Examples: ``1e37``  ``-3.14``  ``0``  ``2.5E-3``
    """

    def __init__(self, parent=None):
        regex = QRegularExpression(rf"^(?:{PATTERNS['scientific_float']})?$")
        super().__init__(regex, parent)


class DebyeWallerValidator(QRegularExpressionValidator):
    """
    Validates Debye-Waller factor strings.

    Format: ``Elem=value`` pairs separated by commas.
    Examples: ``Zn=0.5``  ``Zn=0.5, Cu=0.6``
    """

    def __init__(self, parent=None):
        regex = QRegularExpression(rf"^(?:{PATTERNS['debye_waller']})?$")
        super().__init__(regex, parent)


class MassChargeListValidator(QRegularExpressionValidator):
    """
    Validates element mass / charge lists.

    Format: ``Elem value`` pairs separated by semicolons.
    Examples: ``C 12.011; H 1.008``  ``C 0.3; H -0.2``
    """

    def __init__(self, parent=None):
        regex = QRegularExpression(rf"^(?:{PATTERNS['mass_charge_list']})?$")
        super().__init__(regex, parent)


class SpaceIntListValidator(QRegularExpressionValidator):
    """
    Validates a space-separated list of non-negative integers.

    Examples: ``1 2``  ``0 3 7``
    """

    def __init__(self, parent=None):
        regex = QRegularExpression(rf"^(?:{PATTERNS['space_int_list']})?$")
        super().__init__(regex, parent)


class FilenameValidator(QRegularExpressionValidator):
    """
    Validates a plain filename (no path separators).

    Examples: ``basic_xrd_plot.png``  ``result.csv``
    """

    def __init__(self, parent=None):
        regex = QRegularExpression(rf"^(?:{PATTERNS['filename']})?$")
        super().__init__(regex, parent)


# ---------------------------------------------------------------------------
# Visual-feedback helper
# ---------------------------------------------------------------------------

# Stylesheet snippets applied according to validation state.
_STYLE_VALID = ""  # "QLineEdit { border: 1.5px solid #4caf50; }"   # green
_STYLE_DEFAULT = ""  # theme default
_STYLE_INVALID = "QLineEdit { border: 1.5px solid #f44336; }"  # red


def apply_validator(line_edit: QLineEdit, validator: QRegularExpressionValidator) -> None:
    """
    Attach *validator* to *line_edit* and wire up live visual feedback.

    Border colours:
    - **Green**   – the current text is fully *Acceptable*.
    - **Default** – the field is empty or in an *Intermediate* (partial) state.
    - **Red**     – the text is *Invalid*.

    Parameters
    ----------
    line_edit:
        The ``QLineEdit`` widget to validate.
    validator:
        Any ``QValidator`` instance (typically one of the classes above).
    """
    line_edit.setValidator(validator)

    def _update_style(text: str) -> None:
        state, _, _ = validator.validate(text, len(text))
        if text == "":
            line_edit.setStyleSheet(_STYLE_DEFAULT)
        elif state == QValidator.State.Acceptable:
            line_edit.setStyleSheet(_STYLE_VALID)
        elif state == QValidator.State.Invalid:
            line_edit.setStyleSheet(_STYLE_INVALID)
        else:  # Intermediate
            line_edit.setStyleSheet(_STYLE_DEFAULT)

    line_edit.textChanged.connect(_update_style)
    # Run once on the current text so existing default values get coloured.
    _update_style(line_edit.text())
