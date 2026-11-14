"""Energy value, display units and (where applicable) reference to Fermi energy."""

from ase2sprkkr.common.grammar_types import Energy
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QSizePolicy

from ase2sprkkr_gui.gui.input_parameters.defaults import default_text
from ase2sprkkr_gui.gui.input_parameters.energy import convert_energy
from ase2sprkkr_gui.gui.widgets.input_parameters.value_editor import (
    ParameterValueEditorWidget,
)
from ase2sprkkr_gui.gui.widgets.nullable_spinbox import NullableDoubleSpinBox


class EnergyEditor(ParameterValueEditorWidget):
    """Independent widget: reads state and commits via caller-supplied callbacks.

    Unit selection is presentation only. A reference change reinterprets the
    displayed number, without assuming an unavailable Fermi energy.

    ``read_state()`` returns EnergyState. ``apply_value(value, unit, relative)``
    must apply the whole change or raise without modifying the caller's state.
    The widget does not own InputParameters, an undo stack, or task validation.
    """
    def __init__(self, read_state, apply_value, parent=None, *, with_reference=True,
                 reference_selectable=True, minimum=-1e9):
        super().__init__(parent)
        self._read_state = read_state
        self._apply_value = apply_value
        self._reference_selectable = reference_selectable
        self._refreshing = False
        self._initialised = False
        self._shown = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.number = NullableDoubleSpinBox(self)
        self.number.setDecimals(10)
        self.number.setRange(minimum - 1., 1e9)
        self.number.set_unset_value(self.number.minimum())
        self.number.setKeyboardTracking(False)
        self.number.setSingleStep(.01)
        self.number.setMinimumWidth(75)
        self.number.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.number.setToolTip('Clear to remove the explicit value. Task defaults may then apply.')
        self.units = QComboBox(self)
        for name in Energy.units:
            self.units.addItem(name, name)
        self.relative = QCheckBox('Relative to EF', self)
        self.relative.setVisible(with_reference)
        layout.addWidget(self.number, 1)
        layout.addWidget(self.units)
        layout.addWidget(self.relative)
        self.number.editingFinished.connect(self.commit)
        self.units.currentIndexChanged.connect(self._unit_changed)
        self.relative.toggled.connect(self.commit)
        self.setFocusProxy(self.number)
        self.refresh()

    def refresh(self):
        """Read the model in the selected display unit, without writing rounded values."""
        self._refreshing = True
        try:
            state = self._read_state()
            selectable = self._reference_selectable
            selectable = selectable() if callable(selectable) else selectable
            self.relative.setEnabled(selectable)
            self.relative.setToolTip(
                'Checked: relative to Fermi energy. Unchecked: absolute energy. '
                'Changing this reinterprets both range bounds; it does not subtract or add a stored Fermi energy.'
                if selectable else 'This task supports absolute energy only; SPRKKR requires both bounds for a relative range.')
            if not self._initialised:
                self.units.setCurrentIndex(self.units.findData(state.unit))
                self._initialised = True
            self.relative.setChecked(state.relative)
            number = self.number.minimum() if state.value is None else convert_energy(
                state.value, state.unit, self.units.currentData())
            self.number.setValue(number)
            if state.value is not None and not state.explicit:
                self.number.show_default(number, default_text(number))
            self._shown = (self.number.value(), state.relative)
        finally:
            self._refreshing = False

    def _unit_changed(self):
        if not self._refreshing:
            # Convert from the full-precision model, not rounded screen text.
            self.refresh()

    def commit(self, *_args):
        """Apply an edited number/reference; preserve full precision if unchanged.

        Empty input becomes None. Callback errors are signalled and leave the
        draft visible; return False on failure and True on success or no change.
        """
        if self._refreshing or not self.isEnabled():
            return True
        value = self.number.value()
        relative = self.relative.isChecked()
        if (value, relative) == self._shown:
            return True
        if value == self.number.minimum() or (not self.number.cleanText().strip() and not self.number.is_default_display()):
            value = None
        try:
            self._apply_value(value, self.units.currentData(), relative)
            self.refresh()
        except Exception as error:
            self.validationChanged.emit(str(error))
            return False
        self.validationChanged.emit('')
        return True
