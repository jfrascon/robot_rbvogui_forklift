import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
import pytest

EXPECTED_RESOURCES = (
    'LICENSE',
    'README.md',
    'config/default_bridge.yaml',
    'config/default_params.yaml',
    'config/default_simulation.yaml',
    'config/default_xacro_args.yaml',
    'launch/debug_model_forklift.launch.py',
    'rviz/sim_debug.rviz',
    'scripts/debug_model_forklift.sh',
    'urdf/model_forklift.xacro',
)

REMOVED_RESOURCES = ('launch/debug_model_base.launch.py', 'scripts/debug_model_base.sh')


@pytest.fixture(scope='module')
def package_share() -> Path:
    return Path(get_package_share_directory('robot_rbvogui_forklift'))


@pytest.mark.parametrize('relative_path', EXPECTED_RESOURCES)
def test_required_resource_is_installed(package_share: Path, relative_path: str) -> None:
    assert package_share.joinpath(relative_path).is_file()


@pytest.mark.parametrize('relative_path', REMOVED_RESOURCES)
def test_removed_resource_is_not_installed(package_share: Path, relative_path: str) -> None:
    assert not package_share.joinpath(relative_path).exists()


@pytest.mark.parametrize('relative_path', ['scripts/debug_model_forklift.sh'])
def test_installed_debug_script_is_executable(package_share: Path, relative_path: str) -> None:
    assert os.access(package_share / relative_path, os.X_OK)
