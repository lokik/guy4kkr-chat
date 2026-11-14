from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    from mendeleev import element as mendeleev_element
except Exception:
    mendeleev_element = None

# Full periodic table layout (Z, symbol, row, col) including f-block rows (8,9)
_TABLE: List[Tuple[int, str, int, int]] = [
    (1, "H", 0, 0), (2, "He", 0, 17),
    (3, "Li", 1, 0), (4, "Be", 1, 1), (5, "B", 1, 12), (6, "C", 1, 13), (7, "N", 1, 14), (8, "O", 1, 15), (9, "F", 1, 16), (10, "Ne", 1, 17),
    (11, "Na", 2, 0), (12, "Mg", 2, 1), (13, "Al", 2, 12), (14, "Si", 2, 13), (15, "P", 2, 14), (16, "S", 2, 15), (17, "Cl", 2, 16), (18, "Ar", 2, 17),
    (19, "K", 3, 0), (20, "Ca", 3, 1), (21, "Sc", 3, 2), (22, "Ti", 3, 3), (23, "V", 3, 4), (24, "Cr", 3, 5), (25, "Mn", 3, 6), (26, "Fe", 3, 7),
    (27, "Co", 3, 8), (28, "Ni", 3, 9), (29, "Cu", 3, 10), (30, "Zn", 3, 11), (31, "Ga", 3, 12), (32, "Ge", 3, 13), (33, "As", 3, 14), (34, "Se", 3, 15),
    (35, "Br", 3, 16), (36, "Kr", 3, 17),
    (37, "Rb", 4, 0), (38, "Sr", 4, 1), (39, "Y", 4, 2), (40, "Zr", 4, 3), (41, "Nb", 4, 4), (42, "Mo", 4, 5), (43, "Tc", 4, 6), (44, "Ru", 4, 7),
    (45, "Rh", 4, 8), (46, "Pd", 4, 9), (47, "Ag", 4, 10), (48, "Cd", 4, 11), (49, "In", 4, 12), (50, "Sn", 4, 13), (51, "Sb", 4, 14), (52, "Te", 4, 15),
    (53, "I", 4, 16), (54, "Xe", 4, 17),
    (55, "Cs", 5, 0), (56, "Ba", 5, 1), (57, "La", 8, 2), (58, "Ce", 8, 3), (59, "Pr", 8, 4), (60, "Nd", 8, 5), (61, "Pm", 8, 6), (62, "Sm", 8, 7),
    (63, "Eu", 8, 8), (64, "Gd", 8, 9), (65, "Tb", 8, 10), (66, "Dy", 8, 11), (67, "Ho", 8, 12), (68, "Er", 8, 13), (69, "Tm", 8, 14), (70, "Yb", 8, 15),
    (71, "Lu", 8, 16),
    (72, "Hf", 5, 3), (73, "Ta", 5, 4), (74, "W", 5, 5), (75, "Re", 5, 6), (76, "Os", 5, 7), (77, "Ir", 5, 8), (78, "Pt", 5, 9), (79, "Au", 5, 10),
    (80, "Hg", 5, 11), (81, "Tl", 5, 12), (82, "Pb", 5, 13), (83, "Bi", 5, 14), (84, "Po", 5, 15), (85, "At", 5, 16), (86, "Rn", 5, 17),
    (87, "Fr", 6, 0), (88, "Ra", 6, 1), (89, "Ac", 9, 2), (90, "Th", 9, 3), (91, "Pa", 9, 4), (92, "U", 9, 5), (93, "Np", 9, 6), (94, "Pu", 9, 7),
    (95, "Am", 9, 8), (96, "Cm", 9, 9), (97, "Bk", 9, 10), (98, "Cf", 9, 11), (99, "Es", 9, 12), (100, "Fm", 9, 13), (101, "Md", 9, 14), (102, "No", 9, 15),
    (103, "Lr", 9, 16),
    (104, "Rf", 6, 3), (105, "Db", 6, 4), (106, "Sg", 6, 5), (107, "Bh", 6, 6), (108, "Hs", 6, 7), (109, "Mt", 6, 8), (110, "Ds", 6, 9), (111, "Rg", 6, 10),
    (112, "Cn", 6, 11), (113, "Nh", 6, 12), (114, "Fl", 6, 13), (115, "Mc", 6, 14), (116, "Lv", 6, 15), (117, "Ts", 6, 16), (118, "Og", 6, 17),
]

CATEGORY_COLORS: Dict[str, str] = {
    'alkali': '#FF6666', 'alkaline': '#FFDEAD', 'lanthanoid': '#FFB3FF', 'actinoid': '#FF99CC',
    'transition': '#FFD27F', 'post': '#C0C0C0', 'metalloid': '#C0E0C0', 'nonmetal': '#99FF99',
    'halogen': '#66FFCC', 'noble': '#66CCFF', 'unknown': '#FFFFFF'
}

def _categorize() -> Dict[int, str]:
    cats: Dict[int, str] = {}
    for z, sym, r, c in _TABLE:
        if z in (3, 11, 19, 37, 55, 87):
            cats[z] = 'alkali'
        elif z in (4, 12, 20, 38, 56, 88):
            cats[z] = 'alkaline'
        elif 57 <= z <= 71:
            cats[z] = 'lanthanoid'
        elif 89 <= z <= 103:
            cats[z] = 'actinoid'
        elif z in (2, 10, 18, 36, 54, 86, 118):
            cats[z] = 'noble'
        elif z in (1, 6, 7, 8, 15, 16, 34):
            cats[z] = 'nonmetal'
        elif z in (5, 14, 32, 33, 51, 52):
            cats[z] = 'metalloid'
        elif z in (9, 17, 35, 53, 85):
            cats[z] = 'halogen'
        elif (21 <= z <= 30) or (39 <= z <= 48) or (72 <= z <= 80) or (104 <= z <= 112):
            cats[z] = 'transition'
        elif z in (13, 31, 49, 50, 81, 82, 83, 113, 114, 115, 116):
            cats[z] = 'post'
        else:
            cats[z] = 'unknown'
    return cats

_CATEGORY_BY_Z = _categorize()

def _load_element_info(atomic_number: int) -> Optional[Dict[str, object]]:
    """Load slow optional element metadata outside the GUI thread."""
    if mendeleev_element is None:
        return None
    try:
        el = mendeleev_element(atomic_number)
    except Exception:  # optional third-party data source boundary
        return None

    conf = _get_attr_value(
        el, 'electronic_configuration', 'econf', 'ec', 'electron_configuration'
    )
    counts = {'s': 0, 'p': 0, 'd': 0, 'f': 0}
    for token in _tokens_from_econf(conf):
        match = re.match(r"^(\d+)([spdf])(\d+)$", str(token).strip())
        if match:
            counts[match.group(2)] += int(match.group(3))
    return {
        'name': _get_attr_value(el, 'name'),
        'symbol': _get_attr_value(el, 'symbol'),
        'atomic_weight': _get_attr_value(el, 'atomic_weight', 'atomic_mass'),
        'valence': _get_attr_value(el, 'nvalence', 'valence'),
        'en': _get_attr_value(el, 'en_pauling', 'electronegativity'),
        'ea': _get_attr_value(el, 'electron_affinity'),
        'ox': _get_attr_value(el, 'oxistates', 'oxidation_states'),
        'econf': conf,
        'spdf': counts,
    }


class _ElementInfoTaskSignals(QObject):
    loaded = pyqtSignal(int, object)


class _ElementInfoTask(QRunnable):
    def __init__(self, atomic_number: int):
        super().__init__()
        self.atomic_number = atomic_number
        self.signals = _ElementInfoTaskSignals()

    def run(self) -> None:
        self.signals.loaded.emit(
            self.atomic_number, _load_element_info(self.atomic_number)
        )


class _ElementInfoLoader(QObject):
    """Cache element metadata and publish completed background loads."""

    loaded = pyqtSignal(int, object)

    def __init__(self):
        super().__init__()
        self._cache: Dict[int, Dict[str, object]] = {}
        self._pending: set[int] = set()
        self._pool = QThreadPool(self)
        # mendeleev access used to be serialized by one worker; keep that property.
        self._pool.setMaxThreadCount(1)

    def cached(self, atomic_number: int) -> Optional[Dict[str, object]]:
        return self._cache.get(atomic_number)

    def request(self, atomic_number: int) -> None:
        if (
            mendeleev_element is None
            or atomic_number in self._cache
            or atomic_number in self._pending
        ):
            return
        self._pending.add(atomic_number)
        task = _ElementInfoTask(atomic_number)
        task.signals.loaded.connect(self._finished)
        self._pool.start(task)

    def _finished(self, atomic_number: int, data: object) -> None:
        self._pending.discard(atomic_number)
        if isinstance(data, dict):
            self._cache[atomic_number] = data
        self.loaded.emit(atomic_number, data)


_ELEMENT_INFO_LOADER: Optional[_ElementInfoLoader] = None

def _element_info_loader() -> _ElementInfoLoader:
    global _ELEMENT_INFO_LOADER
    if _ELEMENT_INFO_LOADER is None:
        _ELEMENT_INFO_LOADER = _ElementInfoLoader()
    return _ELEMENT_INFO_LOADER

def _get_attr_value(obj, *names):
    for name in names:
        if not hasattr(obj, name):
            continue
        value = getattr(obj, name)
        if callable(value):
            try:
                value = value()
            except Exception:
                continue
        if value is not None:
            return value
    return None

def _tokens_from_econf(config_str):
    if not isinstance(config_str, str) or not config_str.strip():
        return []
    tokens: List[str] = []
    m = re.search(r"\[(\w+)\]", config_str)
    rest = config_str
    if m:
        core_sym = m.group(1)
        # minimal expansion (He..Rn) not strictly needed for counts; skip for speed
        rest = re.sub(r"\[\w+\]", "", rest)
    tokens.extend(rest.split())
    return tokens

def _compress_to_noble_shorthand(config_str):
    if not isinstance(config_str, str) or not config_str.strip():
        return config_str
    if re.search(r"\[\w+\]", config_str):
        return re.sub(r"\s+", " ", config_str).strip()
    # Not recomputing full core compression for brevity
    return config_str


def _format_element_info(
    atomic_number: int, symbol: str, data: Optional[Dict[str, object]] = None
) -> str:
    """Format both cached and freshly loaded element information."""
    lines = [f"Symbol: {symbol}", f"Z: {atomic_number}"]
    if not data:
        return "\n".join(lines)

    name = data.get('name')
    if name:
        lines.insert(0, f"Name: {name} ({data.get('symbol') or symbol})")
    fields = (
        ('atomic_weight', 'Atomic weight'),
        ('valence', 'Valence'),
        ('en', 'EN (Pauling)'),
        ('ea', 'Electron affinity'),
        ('ox', 'Ox states'),
    )
    for key, label in fields:
        value = data.get(key)
        if value:
            lines.append(f"{label}: {value}")
    if data.get('econf'):
        lines.append(f"Config: {_compress_to_noble_shorthand(data['econf'])}")

    spdf = data.get('spdf')
    if isinstance(spdf, dict):
        parts = []
        for orb in ('s', 'p', 'd', 'f'):
            value = spdf.get(orb)
            if isinstance(value, int) and value > 0:
                parts.append(f"{orb}:{value}")
        if parts:
            lines.append("Orbitals " + ", ".join(parts))
    return "\n".join(lines)


class ElementSelectorDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Select Element")
        self.selected_symbol: Optional[str] = None
        self._hovered_element: Optional[Tuple[int, str]] = None
        self._info_loader = _element_info_loader()
        self._info_loader.loaded.connect(self._element_info_loaded)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        layout.addLayout(top)
        grid = QGridLayout()
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(2)
        # Add an empty row gap between main block (0..6) and f-block (8,9)
        grid.setRowMinimumHeight(7, 14)
        top.addLayout(grid)

        font = QFont()
        font.setPointSize(11)
        font.setBold(True)

        size = 36
        for z, sym, r, c in _TABLE:
            cat = _CATEGORY_BY_Z.get(z, 'unknown')
            color = CATEGORY_COLORS.get(cat, '#FFFFFF')
            btn = QPushButton(sym)
            btn.setFont(font)
            btn.setFixedSize(size, size)
            btn.setStyleSheet(
                "QPushButton { background-color: %s; color: #000000; border: 1px solid #666; padding:0px; }"
                "QPushButton:hover { background-color: %s; color: #000000; border: 2px solid #222; }" % (color, color)
            )
            btn.clicked.connect(lambda _=False, s=sym: self._choose(s))
            btn.enterEvent = self._make_enter_handler(z, sym)  # type: ignore
            btn.leaveEvent = self._make_leave_handler(z)  # type: ignore
            grid.addWidget(btn, r, c)

        # Info / status panel on the right
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        info_title = QLabel("Element info")
        info_title.setFont(QFont("", 10, QFont.Weight.Bold))
        right_layout.addWidget(info_title)
        self.info_label = QLabel("Hover element for info")
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        right_layout.addWidget(self.info_label)
        right_layout.addStretch(1)
        right_widget.setMinimumWidth(260)
        top.addWidget(right_widget)

        # Action row
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)
        layout.addLayout(actions)

    def _choose(self, symbol: str) -> None:
        self.selected_symbol = symbol
        self.accept()

    def _make_enter_handler(self, z: int, sym: str):
        def handler(_event):
            self._hovered_element = (z, sym)
            data = self._info_loader.cached(z)
            text = _format_element_info(z, sym, data)
            if data is None and mendeleev_element is not None:
                text += "\nLoading..."
                self._info_loader.request(z)
            self.info_label.setText(text)
        return handler

    def _make_leave_handler(self, z: int):
        def handler(_event):
            if self._hovered_element and self._hovered_element[0] == z:
                self._hovered_element = None
                self.info_label.setText("Hover element for info")
        return handler

    def _element_info_loaded(self, z: int, data: object) -> None:
        if not self._hovered_element or self._hovered_element[0] != z:
            return
        _, symbol = self._hovered_element
        info = data if isinstance(data, dict) else None
        self.info_label.setText(_format_element_info(z, symbol, info))

    def result_symbol(self) -> Optional[str]:
        return self.selected_symbol


def select_element(parent: Optional[QWidget] = None) -> Optional[str]:
    dlg = ElementSelectorDialog(parent)
    result = dlg.exec()
    if result == QDialog.DialogCode.Accepted:
        return dlg.result_symbol()
    return None
