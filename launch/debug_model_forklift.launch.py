"""
Launch the RB-VOGUI forklift model in a package-local Gazebo debug world.

The launch renders Xacro once, starts Gazebo, waits for entity creation to become available, and
spawns the resulting URDF file. It then starts RSP, the bridge, kinematics, fork control, and RViz
only after Gazebo reports that the model was created.

Use this launch file to inspect URDF/Xacro changes and Gazebo plugins without starting the complete
simulation stack.
"""

from datetime import datetime
import os
from tempfile import mkstemp

from launch import LaunchContext
from launch import LaunchDescription
from launch import LaunchDescriptionEntity
from launch.actions import DeclareLaunchArgument
from launch.actions import EmitEvent
from launch.actions import ExecuteProcess
from launch.actions import IncludeLaunchDescription
from launch.actions import LogInfo
from launch.actions import OpaqueFunction
from launch.actions import RegisterEventHandler
from launch.actions import SetLaunchConfiguration
from launch.conditions import IfCondition
from launch.conditions import UnlessCondition
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.events.process import ProcessExited
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.logging import get_logger
from launch.substitutions import LaunchConfiguration
from launch.substitutions import PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackagePrefix
from launch_ros.substitutions import FindPackageShare
import ros2_launch_helpers as rlh


def generate_launch_description() -> LaunchDescription:
    """Launch the RB-VOGUI forklift model in a Gazebo world for debugging and inspection."""
    actions: list[LaunchDescriptionEntity] = [
        SetLaunchConfiguration('namespace', '/sim_debug'),
        SetLaunchConfiguration('use_sim_time', 'True'),
        SetLaunchConfiguration('world_name', 'debug_world'),
        DeclareLaunchArgument(
            'robot_name', default_value='rbv0', description='Unique robot name.'
        ),
        DeclareLaunchArgument(
            'robot_params_file',
            default_value=PathJoinSubstitution(
                [FindPackageShare('robot_rbvogui_forklift'), 'config', 'default_params.yaml']
            ),
            description='Complete robot parameter YAML file.',
        ),
        DeclareLaunchArgument(
            'robot_params_file_allow_substs',
            default_value='True',
            choices=['True', 'true', 'False', 'false'],
            description='Allow ROS launch substitutions in robot_params_file.',
        ),
        DeclareLaunchArgument(
            'robot_xacro_args_file',
            default_value=PathJoinSubstitution(
                [FindPackageShare('robot_rbvogui_forklift'), 'config', 'default_xacro_args.yaml']
            ),
            description='YAML file with model-description xacro arguments.',
        ),
        DeclareLaunchArgument(
            'robot_sim_file',
            default_value=PathJoinSubstitution(
                [FindPackageShare('robot_rbvogui_forklift'), 'config', 'default_simulation.yaml']
            ),
            description='Simulation YAML used while generating the robot description.',
        ),
        DeclareLaunchArgument(
            'robot_bridge_config_file',
            default_value=PathJoinSubstitution(
                [FindPackageShare('robot_rbvogui_forklift'), 'config', 'default_bridge.yaml']
            ),
            description='ROS-Gazebo bridge configuration for this model.',
        ),
        DeclareLaunchArgument(
            'robot_rsp_node_args',
            default_value='{"output":"both","ros_arguments":["--log-level","info"]}',
            description=rlh.LAUNCH_ACTION_ARGUMENTS_DESC,
        ),
        DeclareLaunchArgument(
            'robot_bridge_node_args',
            default_value='{"output":"both","ros_arguments":["--log-level","info"]}',
            description=rlh.LAUNCH_ACTION_ARGUMENTS_DESC,
        ),
        DeclareLaunchArgument(
            'robot_kinematics_node_args',
            default_value='{"output":"both","ros_arguments":["--log-level","info"]}',
            description=rlh.LAUNCH_ACTION_ARGUMENTS_DESC,
        ),
        DeclareLaunchArgument(
            'robot_fork_controller_node_args',
            default_value='{"output":"both","ros_arguments":["--log-level","info"]}',
            description=rlh.LAUNCH_ACTION_ARGUMENTS_DESC,
        ),
        DeclareLaunchArgument(
            'robot_fork_serial_node_args',
            default_value='{"output":"both","ros_arguments":["--log-level","info"]}',
            description=rlh.LAUNCH_ACTION_ARGUMENTS_DESC,
        ),
        DeclareLaunchArgument(
            'rviz_enabled',
            default_value='True',
            choices=['True', 'true', 'False', 'false'],
            description='Launch RViz with the RB-VOGUI debug configuration.',
        ),
        DeclareLaunchArgument(
            'gzgui_enabled',
            default_value='True',
            choices=['True', 'true', 'False', 'false'],
            description='Launch the Gazebo graphical client.',
        ),
        rlh.RequireFile(path=LaunchConfiguration('robot_params_file')),
        rlh.RequireFile(path=LaunchConfiguration('robot_sim_file')),
        rlh.RequireFile(path=LaunchConfiguration('robot_bridge_config_file')),
        rlh.SetRobotNamespace(
            namespace=LaunchConfiguration('namespace'),
            robot_name=LaunchConfiguration('robot_name'),
            output_context_key='robot_namespace',
        ),
        rlh.SetRobotPrefix(
            robot_name=LaunchConfiguration('robot_name'), output_context_key='robot_prefix'
        ),
        # Keep the original path when substitutions are disabled.
        SetLaunchConfiguration(
            'resolved_robot_params_file', LaunchConfiguration('robot_params_file')
        ),
        # When enabled, render once and replace the shared path before any child launch starts.
        rlh.RenderParamsFile(
            params_file=LaunchConfiguration('robot_params_file'),
            output_context_key='resolved_robot_params_file',
            condition=IfCondition(LaunchConfiguration('robot_params_file_allow_substs')),
        ),
        OpaqueFunction(function=_set_robot_urdf_file),
        _include_render_robot_urdf(),
        _include_spawn_world(),
    ]

    # Wait for the Gazebo create service before launching the remaining actions.
    wait_for_create_service = ExecuteProcess(
        cmd=[
            PathJoinSubstitution(
                [
                    FindPackagePrefix('ros_gz_tools'),
                    'lib',
                    'ros_gz_tools',
                    'wait_for_gz_service.py',
                ]
            ),
            ['/world/', LaunchConfiguration('world_name'), '/create'],
        ],
        output='screen',
    )

    actions.extend(
        [
            RegisterEventHandler(
                OnProcessExit(
                    target_action=wait_for_create_service,
                    # Spawn the model and launch the remaining actions.
                    on_exit=lambda event, context: _launch_actions_after_world_ready(
                        event, context
                    ),
                )
            ),
            wait_for_create_service,
        ]
    )

    return LaunchDescription(actions)


def _launch_actions_after_world_ready(
    event: ProcessExited, ctx: LaunchContext
) -> list[LaunchDescriptionEntity]:
    """Create the model only after the Gazebo world advertises its create service."""
    if event.returncode != 0:
        reason = f'Gazebo world readiness check failed with return code {event.returncode}.'
        get_logger('robot_rbvogui_forklift').error(reason)
        return [EmitEvent(event=Shutdown(reason=reason))]

    robot_name = LaunchConfiguration('robot_name').perform(ctx)

    spawn_model_action = Node(
        package='ros_gz_sim',
        executable='create',
        parameters=[
            {
                'world': LaunchConfiguration('world_name'),
                'file': LaunchConfiguration('robot_urdf_file'),
                'string': '',
                'topic': '',
                'name': robot_name,
                'allow_renaming': False,
                'x': 0.0,
                'y': 0.0,
                'z': 0.0,
                'R': 0.0,
                'P': 0.0,
                'Y': 0.0,
            }
        ],
        ros_arguments=['--log-level', 'info'],
        output='screen',
    )

    return [
        RegisterEventHandler(
            OnProcessExit(
                target_action=spawn_model_action,
                on_exit=lambda event, context: _launch_actions_after_model_ready(event, context),
            )
        ),
        LogInfo(
            msg=[
                "Spawning model '",
                robot_name,
                "' into world '",
                LaunchConfiguration('world_name'),
                "'",
            ]
        ),
        spawn_model_action,
    ]


def _set_robot_urdf_file(ctx: LaunchContext) -> list[LaunchDescriptionEntity]:
    """Create a unique persistent URDF path for this robot namespace."""
    robot_namespace = LaunchConfiguration('robot_namespace').perform(ctx)
    flattened_namespace = rlh.flatten_namespace(robot_namespace, '_')
    if not flattened_namespace:
        raise ValueError('robot_namespace must not flatten to an empty URDF filename prefix.')

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    file_descriptor, output_path = mkstemp(
        prefix=f'{flattened_namespace}_{timestamp}_', suffix='.urdf', dir='/tmp'
    )
    os.close(file_descriptor)
    ctx.launch_configurations['robot_urdf_file'] = output_path
    return [LogInfo(msg=f'Robot URDF output: {output_path}')]


def _include_render_robot_urdf() -> IncludeLaunchDescription:
    """Render the forklift Xacro to the shared URDF file before starting child processes."""
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [FindPackageShare('robot_rbvogui_common'), 'launch', 'render_robot_urdf.launch.py']
            )
        ),
        launch_arguments={
            'namespace': LaunchConfiguration('namespace'),
            'robot_name': LaunchConfiguration('robot_name'),
            'robot_xacro_file': PathJoinSubstitution(
                [FindPackageShare('robot_rbvogui_forklift'), 'urdf', 'model_forklift.xacro']
            ),
            'robot_xacro_args_file': LaunchConfiguration('robot_xacro_args_file'),
            'robot_sim_file': LaunchConfiguration('robot_sim_file'),
            'robot_urdf_file': LaunchConfiguration('robot_urdf_file'),
        }.items(),
    )


def _include_spawn_world() -> IncludeLaunchDescription:
    """Start the shared Gazebo world used to inspect the forklift model."""
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [FindPackageShare('ros_gz_tools'), 'launch', 'spawn_world.launch.py']
            )
        ),
        launch_arguments={
            'gzserver_use_composition': 'False',
            'gzserver_create_own_container': 'False',
            'gzserver_container_name': '',
            'gzserver_initial_sim_time': '0.0',
            'gzserver_verbosity_level': '4',
            'gzgui_enabled': LaunchConfiguration('gzgui_enabled'),
            'gzgui_config_file': '',
            'world_sdf_file': PathJoinSubstitution(
                [FindPackageShare('robot_rbvogui_common'), 'worlds', 'debug_world.sdf']
            ),
            'world_sdf_string': '',
            'world_bridge_config_file': PathJoinSubstitution(
                [FindPackageShare('robot_rbvogui_common'), 'worlds', 'debug_world_bridge.yaml']
            ),
            'world_bridge_name': 'world_bridge',
            'world_bridge_subscription_heartbeat': '1000',
            'world_bridge_expand_gz_topic_names': 'True',
            'world_bridge_override_timestamps_with_wall_time': 'False',
            'world_bridge_override_frame_id': '',
            'world_bridge_use_respawn': 'False',
            'world_bridge_log_level': 'info',
        }.items(),
    )


def _include_robot_state_publisher() -> IncludeLaunchDescription:
    """Start robot_state_publisher from the URDF rendered by the parent launch."""
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [
                    FindPackageShare('robot_rbvogui_common'),
                    'launch',
                    'robot_state_publisher.launch.py',
                ]
            )
        ),
        launch_arguments={
            'namespace': LaunchConfiguration('namespace'),
            'robot_name': LaunchConfiguration('robot_name'),
            'robot_urdf_file': LaunchConfiguration('robot_urdf_file'),
            'robot_rsp_params_file': LaunchConfiguration('resolved_robot_params_file'),
            'robot_rsp_params_file_allow_substs': 'False',
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'node_args': LaunchConfiguration('robot_rsp_node_args'),
        }.items(),
    )


def _launch_actions_after_model_ready(
    event: ProcessExited, _ctx: LaunchContext
) -> list[LaunchDescriptionEntity]:
    """Start model-dependent processes only after Gazebo finishes spawning the robot."""
    if event.returncode != 0:
        reason = f'Gazebo model spawn failed with return code {event.returncode}.'
        get_logger('robot_rbvogui_forklift').error(reason)
        return [EmitEvent(event=Shutdown(reason=reason))]

    return [
        _include_robot_state_publisher(),
        _include_bridge(),
        _include_kinematics(),
        *_include_fork_control(),
        _launch_rviz(),
    ]


def _include_bridge() -> IncludeLaunchDescription:
    """Start the model bridge after starting the Gazebo spawn process."""
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [FindPackageShare('robot_rbvogui_common'), 'launch', 'bridge.launch.py']
            )
        ),
        launch_arguments={
            'namespace': LaunchConfiguration('namespace'),
            'robot_name': LaunchConfiguration('robot_name'),
            'robot_bridge_params_file': LaunchConfiguration('resolved_robot_params_file'),
            'robot_bridge_params_file_allow_substs': 'False',
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'robot_bridge_config_file': LaunchConfiguration('robot_bridge_config_file'),
            'node_args': LaunchConfiguration('robot_bridge_node_args'),
        }.items(),
    )


def _include_kinematics() -> IncludeLaunchDescription:
    """Start the kinematics node after starting the model bridge."""
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [
                    FindPackageShare('robot_rbvogui_common'),
                    'launch',
                    'ground_vehicle_kinematics.launch.py',
                ]
            )
        ),
        launch_arguments={
            'namespace': LaunchConfiguration('namespace'),
            'robot_name': LaunchConfiguration('robot_name'),
            'robot_params_file': LaunchConfiguration('resolved_robot_params_file'),
            'robot_params_file_allow_substs': 'False',
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'node_args': LaunchConfiguration('robot_kinematics_node_args'),
        }.items(),
    )


def _include_fork_control() -> list[IncludeLaunchDescription]:
    """Start fork control processes after starting the bridge and kinematics node."""
    return [_include_fork_controller_server(), _include_fork_serial_driver()]


def _include_fork_controller_server() -> IncludeLaunchDescription:
    """Start the fork action server with every child launch key set explicitly."""
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [
                    FindPackageShare('joint_position_controller_server'),
                    'launch',
                    'joint_position_controller_server.launch.py',
                ]
            )
        ),
        launch_arguments={
            'namespace': LaunchConfiguration('robot_namespace'),
            'params_file': LaunchConfiguration('resolved_robot_params_file'),
            'params_file_allow_substs': 'False',
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'node_args': LaunchConfiguration('robot_fork_controller_node_args'),
        }.items(),
    )


def _include_fork_serial_driver() -> IncludeLaunchDescription:
    """Start the physical fork driver only when the launch uses real time."""
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [
                    FindPackageShare('joint_position_controller_server'),
                    'launch',
                    'prismatic_joint_position_serial_driver.launch.py',
                ]
            )
        ),
        condition=UnlessCondition(LaunchConfiguration('use_sim_time')),
        launch_arguments={
            'namespace': LaunchConfiguration('robot_namespace'),
            'params_file': LaunchConfiguration('resolved_robot_params_file'),
            'params_file_allow_substs': 'False',
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'node_args': LaunchConfiguration('robot_fork_serial_node_args'),
        }.items(),
    )


def _launch_rviz() -> Node:
    """Launch RViz with the package-local RB-VOGUI debug configuration."""
    return Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        namespace=LaunchConfiguration('namespace'),
        arguments=[
            '-d',
            PathJoinSubstitution(
                [FindPackageShare('robot_rbvogui_forklift'), 'rviz', 'sim_debug.rviz']
            ),
        ],
        output='both',
        condition=IfCondition(LaunchConfiguration('rviz_enabled')),
    )
