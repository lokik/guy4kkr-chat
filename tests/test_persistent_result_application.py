from __future__ import annotations
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from ase import Atoms
from ase2sprkkr import InputParameters
from kkrunner.projects import ProjectRunManager, ProjectRepository
from kkrunner.files import FileEntry, FileManifest
from kkrunner import RunState, RunStore
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QWidget
from ase2sprkkr_gui.gui.application.persistent_jobs import PersistentJobSource
from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog
from ase2sprkkr_gui.gui.dialogs.profiles import ProfileSelectionDialog
from ase2sprkkr_gui.gui.flows import calculation as calculation_flow
from ase2sprkkr_gui.main import GuiApplication

def _finished_dos_run(tmp_path):
    parameters = InputParameters.create('DOS')
    parameters.CONTROL.DATASET = 'persistent-application'
    input_path = tmp_path / 'persistent-application.inp'
    output_path = tmp_path / 'persistent-application.out'
    dos_path = tmp_path / 'persistent-application_DOS.dos'
    with input_path.open('w') as stream:
        parameters.save_to_file(stream, validate=False)
    dos_path.write_text('')
    output_path.write_text(f'          *       KKRSCF  VERSION  8.5.test      (C) 2026  *\n          programm execution  on    15/10/2026    at   18:59:12\n          FILES:\n\n          input: {input_path.name}\n          DOS: {dos_path.name}\n\n')
    projects = ProjectRepository(tmp_path / 'projects')
    project = projects.create('Test')
    manager = ProjectRunManager(store=RunStore(tmp_path / 'runs'), project_repository=projects, project=project)
    run = manager.new_record(directory=tmp_path, files=FileManifest(inputs=(FileEntry(local_path=str(input_path)),), stdout=FileEntry(local_path=str(output_path)), outputs=(FileEntry(local_path=str(dos_path)),)), metadata={'ase2sprkkr': {'task': str('DOS').upper(), 'input_definition': str('DOS').upper()}}, processing_required=True)
    manager.store.save(run)
    run = manager.complete(run, state=RunState.FINISHED, return_code=0, artifacts_available=True)
    return (PersistentJobSource(manager), run)

def test_persisted_result_enters_application_history_and_recompute(tmp_path):
    """Exercise the production persistence -> workspace -> recompute boundaries."""
    application = QApplication.instance() or QApplication([])
    source, run = _finished_dos_run(tmp_path)
    gui = GuiApplication(workspace=WorkspaceState(atoms=Atoms('Fe'), directory=str(tmp_path)), recent_files_path=tmp_path / 'recent.json', settings_path=tmp_path / 'settings.json', persistent_jobs=source)
    loaded = gui.persistent_jobs_controller.load_result(run.id)
    assert loaded.task_name.lower() == 'dos'
    assert loaded.input_parameters.task_name.lower() == 'dos'
    record = gui.controller.result_store.result_for_external_source(tmp_path / 'persistent-application.out', persistent_ref=run.id)
    assert record is not None
    assert record.persistent_ref == run.id
    assert record.task_name == 'dos'
    assert record.input_parameters.task_name.lower() == 'dos'
    parent = QWidget()
    seen_dialogs = []

    def answer_next_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        if dialog is None:
            QTimer.singleShot(0, answer_next_dialog)
            return
        seen_dialogs.append(type(dialog))
        if isinstance(dialog, GuidedInputParametersDialog):
            dialog.accept()
            QTimer.singleShot(0, answer_next_dialog)
            return
        if isinstance(dialog, ProfileSelectionDialog):
            dialog.reject()
            return
        if isinstance(dialog, QDialog):
            dialog.reject()
    QTimer.singleShot(0, answer_next_dialog)
    launched = calculation_flow.recompute_result(gui.controller, gui.recent_files, parent, record.id)
    assert launched is None
    assert GuidedInputParametersDialog in seen_dialogs
    assert ProfileSelectionDialog in seen_dialogs
    assert gui.controller.input_parameters.task_name.lower() == 'dos'
