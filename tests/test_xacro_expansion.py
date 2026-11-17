from math import pi
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
import yaml

from conftest import PACKAGE_DIR
from conftest import run_bash


def test_forklift_xacro_expands_to_valid_urdf(tmp_path: Path) -> None:
    urdf_path = tmp_path / 'forklift.urdf'
    xacro_path = PACKAGE_DIR / 'urdf' / 'robot_rbvogui_forklift.xacro'

    result = run_bash(f'xacro "{xacro_path}" > "{urdf_path}" && check_urdf "{urdf_path}"')
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    expanded = urdf_path.read_text(encoding='utf-8')
    assert 'rbvogui_fork_root_link' in expanded
    assert 'rbvogui_basket_root_link' in expanded
    assert 'rbvogui_front_top_lidar_root_link' in expanded
    assert 'rbvogui_back_top_lidar_root_link' in expanded

    model = ET.fromstring(expanded)
    lidar = model.find("link[@name='rbvogui_front_bottom_lidar_root_link']")
    assert lidar is not None
    mesh_dir = (
        'package://robotics_description/meshes/sensors/lidars/'
        'sick_microscan3_mics3_cbaz40pz1/'
    )
    mesh_name = 'sick_microscan3_mics3_cbaz40pz1'
    visual = lidar.find('visual/geometry/mesh')
    collision = lidar.find('collision/geometry/mesh')
    assert visual is not None
    assert collision is not None
    assert visual.attrib['filename'] == f'{mesh_dir}{mesh_name}.obj'
    assert collision.attrib['filename'] == f'{mesh_dir}{mesh_name}.stl'
    assert lidar.find('visual/material') is None

    mount = model.find("joint[@name='rbvogui_front_bottom_lidar_root_joint']")
    assert mount is not None
    parent = mount.find('parent')
    origin = mount.find('origin')
    base_origin = model.find("joint/child[@link='rbvogui_base_link']/../origin")
    assert parent is not None
    assert origin is not None
    assert base_origin is not None
    assert parent.attrib['link'] == 'rbvogui_base_link'
    xyz = [float(value) for value in origin.attrib['xyz'].split()]
    rpy = [float(value) for value in origin.attrib['rpy'].split()]
    base_height = float(base_origin.attrib['xyz'].split()[2])
    assert rpy == pytest.approx([pi, 0.0, 0.0])
    assert xyz[1] == pytest.approx(0.0)
    # The inverted microScan3 stays flush with the front edge and 0.1 m above ground.
    assert xyz[0] + 0.1111 / 2.0 == pytest.approx(1.044 / 2.0)
    assert base_height + xyz[2] - 0.1507 == pytest.approx(0.1)

    camera = model.find("link[@name='rbvogui_fork_camera_link']")
    assert camera is not None
    camera_mesh_dir = 'package://robotics_description/meshes/sensors/cameras/realsense_d435/'
    assert camera.find('visual/geometry/mesh').get('filename') == (
        f'{camera_mesh_dir}realsense_d435.obj'
    )
    assert camera.find('collision/geometry/mesh').get('filename') == (
        f'{camera_mesh_dir}realsense_d435.stl'
    )
    assert camera.find('visual/material') is None
    assert float(camera.find('inertial/mass').get('value')) == pytest.approx(0.072)

    camera_mount = model.find("joint[@name='rbvogui_fork_camera_joint']")
    assert camera_mount.find('parent').get('link') == 'rbvogui_fork_root_link'
    assert tuple(map(float, camera_mount.find('origin').get('xyz').split())) == pytest.approx(
        (0.015372, 0.0, 0.045)
    )


def test_forklift_simulation_xacro_expands_to_valid_urdf(tmp_path: Path) -> None:
    urdf_path = tmp_path / 'forklift_simulation.urdf'
    xacro_path = PACKAGE_DIR / 'urdf' / 'robot_rbvogui_forklift.xacro'
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

    sensor = ET.fromstring(expanded).find(
        ".//sensor[@name='rbvogui_front_bottom_lidar_gz']"
    )
    assert sensor is not None
    assert sensor.attrib['type'] == 'gpu_lidar'
    assert sensor.findtext('topic') == 'rbvogui/front_bottom_lidar/scan'
    assert sensor.findtext('gz_frame_id') == 'rbvogui_front_bottom_lidar_link'
    assert float(sensor.findtext('lidar/range/max', 'nan')) == pytest.approx(40.0)
    horizontal = sensor.find('lidar/scan/horizontal')
    assert horizontal is not None
    assert float(horizontal.findtext('min_angle', 'nan')) == pytest.approx(-137.5 * pi / 180)
    assert float(horizontal.findtext('max_angle', 'nan')) == pytest.approx(137.5 * pi / 180)
    assert horizontal.findtext('samples') == '706'

    camera_sensor = ET.fromstring(expanded).find(
        ".//sensor[@name='rbvogui_fork_camera_rgbd_gz_sensor']"
    )
    assert camera_sensor is not None
    assert camera_sensor.get('type') == 'rgbd_camera'
    assert camera_sensor.findtext('topic') == 'rbvogui/fork_camera/rgbd'


def test_fork_camera_arguments_match_default_configuration() -> None:
    root = ET.parse(PACKAGE_DIR / 'urdf' / 'robot_rbvogui_forklift.xacro').getroot()
    namespace = {'xacro': 'http://www.ros.org/wiki/xacro'}
    defaults = yaml.safe_load(
        (PACKAGE_DIR / 'config' / 'default_xacro_args.yaml').read_text(encoding='utf-8')
    )
    expected = {
        'fork_rgbd_use_visual': True,
        'fork_rgbd_use_collision': True,
        'fork_rgbd_use_inertial': True,
        'fork_rgbd_use_v_mesh': True,
        'fork_rgbd_color': '',
        'fork_rgbd_use_c_mesh': True,
    }
    for name, value in expected.items():
        argument = root.find(f"xacro:arg[@name='{name}']", namespace)
        assert argument is not None
        assert argument.get('default') == str(value)
        assert defaults[name] == value


@pytest.mark.parametrize(
    ('argument', 'element', 'geometry'),
    [
        ('fork_rgbd_use_visual', 'visual', None),
        ('fork_rgbd_use_collision', 'collision', None),
        ('fork_rgbd_use_v_mesh', 'visual', 'box'),
        ('fork_rgbd_use_c_mesh', 'collision', 'box'),
    ],
)
def test_fork_camera_geometry_arguments_are_forwarded(
    tmp_path: Path, argument: str, element: str, geometry: str | None
) -> None:
    urdf_path = tmp_path / f'{argument}.urdf'
    xacro_path = PACKAGE_DIR / 'urdf' / 'robot_rbvogui_forklift.xacro'
    result = run_bash(f'xacro "{xacro_path}" {argument}:=False > "{urdf_path}"')
    assert result.returncode == 0, result.stdout + result.stderr
    camera = ET.parse(urdf_path).getroot().find("link[@name='rbvogui_fork_camera_link']")
    assert camera is not None
    if geometry is None:
        assert camera.find(element) is None
    else:
        shape = camera.find(f'{element}/geometry/{geometry}')
        assert shape is not None
        assert tuple(map(float, shape.get('size').split())) == pytest.approx(
            (0.02505, 0.09, 0.025)
        )


def test_fork_camera_inertial_argument_selects_null_inertia(tmp_path: Path) -> None:
    urdf_path = tmp_path / 'camera_null_inertia.urdf'
    xacro_path = PACKAGE_DIR / 'urdf' / 'robot_rbvogui_forklift.xacro'
    result = run_bash(f'xacro "{xacro_path}" fork_rgbd_use_inertial:=False > "{urdf_path}"')
    assert result.returncode == 0, result.stdout + result.stderr
    camera = ET.parse(urdf_path).getroot().find("link[@name='rbvogui_fork_camera_link']")
    assert camera is not None
    assert float(camera.find('inertial/mass').get('value')) == pytest.approx(0.01)
