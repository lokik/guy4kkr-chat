"""Transaction policy for SPR-KKR's separate single-site energy contour."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, MutableMapping

from ase2sprkkr import InputParameters

from ase2sprkkr_gui.gui.input_parameters.bindings import InputParameterPath, resolve_option


class SingleSiteContourPlugin:
    """Keep the optional second energy mesh outside inactive input files.

    The policy is deliberately independent of Qt and of the session class. It
    participates in a transaction by modifying only its candidate parameters
    and the supplied non-serialized editing state.
    """

    _MESH_PATHS: tuple[InputParameterPath, ...] = (
        ("ENERGY", "GRID"),
        ("ENERGY", "NE"),
    )
    _INDEX = 1

    def apply(
        self,
        before_parameters: InputParameters,
        candidate_parameters: InputParameters,
        dormant: MutableMapping[tuple[InputParameterPath, int], Any],
    ) -> None:
        before_active = before_parameters.uses_separate_single_site_contour()
        after_active = candidate_parameters.uses_separate_single_site_contour()
        if before_active == after_active:
            # An unrelated edit must not repair incomplete imported input.
            return

        for path in self._MESH_PATHS:
            option = resolve_option(candidate_parameters, path)
            values = list(option())
            key = (path, self._INDEX)
            if after_active and len(values) == 1:
                values.append(deepcopy(dormant.get(key, values[0])))
                option.set(values)
            elif not after_active and len(values) > 1:
                dormant[key] = deepcopy(values[self._INDEX])
                option.set(values[:1])
