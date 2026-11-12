"""Guy4ASE uses only stable ASE2SPRKKR runtime contracts."""


def test_file_versions_use_backend_execution_contract():
    from ase2sprkkr.execution import FileState, FileVersion, FileVersionCaptureError
    from guy4ase.gui.application import result_store, result_artifacts, potential_version

    assert result_store.FileState is FileState
    assert result_store.FileVersion is FileVersion
    assert result_artifacts.FileState is FileState
    assert potential_version.PotentialFileVersion is FileVersion
    assert issubclass(FileVersionCaptureError, OSError)


def test_result_loading_uses_public_potential_exception():
    from ase2sprkkr.potentials.potentials import PotentialFileChanged
    from guy4ase.gui.application import result_loading

    assert result_loading.PotentialFileChanged is PotentialFileChanged
