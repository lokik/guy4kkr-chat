"""A safe, inspectable result when a native calculation output cannot be parsed."""
from __future__ import annotations

from typing import Any

from ase2sprkkr import TaskResult


class OutputOnlyResult(TaskResult):
    """Expose the captured OUT file without claiming valid scientific results.

    The historical run record is retained so the normal OutputFileOption
    enforces its captured file version before offering file actions.
    """

    produces_potential = False

    def __init__(self, record: Any, parse_error: Exception) -> None:
        files = record.files
        if files is None or files.output_file is None:
            raise FileNotFoundError("The run has no recorded output file")
        metadata = record.metadata.get("ase2sprkkr", {})
        super().__init__(
            None,
            None,
            record.execution.directory.local,
            output_file=files.output_file,
            task_name=metadata.get("task") or "unknown",
        )
        self.run_record = record
        self.return_code = record.return_code
        self.parse_error = f"{type(parse_error).__name__}: {parse_error}"

    @property
    def input_parameters(self) -> None:
        # Do not guess an input file or interpret scientific data in fallback mode.
        return None

    @property
    def output_values(self) -> dict[str, Any]:
        return {"output": self.files["output"]}
