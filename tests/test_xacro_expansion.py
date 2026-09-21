from pathlib import Path

from conftest import PACKAGE_DIR
from conftest import run_bash


def test_forklift_xacro_expands_to_valid_urdf(tmp_path: Path) -> None:
    urdf_path = tmp_path / 'forklift.urdf'
    xacro_path = PACKAGE_DIR / 'urdf' / 'model_forklift.xacro'

    result = run_bash(f'xacro "{xacro_path}" > "{urdf_path}" && check_urdf "{urdf_path}"')
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    expanded = urdf_path.read_text(encoding='utf-8')
    assert 'rbvogui_fork_root_link' in expanded
    assert 'rbvogui_basket_root_link' in expanded
    assert 'rbvogui_front_top_lidar_root_link' in expanded
    assert 'rbvogui_back_top_lidar_root_link' in expanded


def test_forklift_simulation_xacro_expands_to_valid_urdf(tmp_path: Path) -> None:
    urdf_path = tmp_path / 'forklift_simulation.urdf'
    xacro_path = PACKAGE_DIR / 'urdf' / 'model_forklift.xacro'
    sim_path = PACKAGE_DIR / 'config' / 'default_simulation.yaml'

    result = run_bash(
        f'xacro "{xacro_path}" sim_file:="{sim_path}" > "{urdf_path}" && check_urdf "{urdf_path}"'
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    expanded = urdf_path.read_text(encoding='utf-8')
    assert 'front_top_lidar/scan' in expanded
    assert 'back_top_lidar/scan' in expanded
    assert 'front_bottom_lidar/scan' in expanded
