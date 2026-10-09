"""Reuse team LeRobot FK/IK and SO101 SDK; no hardware CLI before commissioning.

Requires Python 3.12+, the reviewed PAC source, matching URDF/calibration,
and a site-specific collision/path validator. Does not connect on import.
"""
import math
import threading

ARM_JOINTS = ['shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll']


class ActionMismatchError(ValueError):
    def __init__(self, action_sent):
        super().__init__('SDK returned an altered action; hold required')
        self.action_sent = action_sent


class So101Backend:
    is_mock = False

    def __init__(self, robot, kinematics, joint_limits_deg, velocity_limits_deg_s,
                 path_validator, position_tolerance_m=.002, orientation_tolerance_rad=.02):
        if not callable(path_validator):
            raise ValueError('Commissioned collision/path validator required')
        if kinematics.joint_names != ARM_JOINTS:
            raise ValueError('URDF joint order must match the five arm joints; exclude gripper')
        if not robot.config.use_degrees:
            raise ValueError('Arm degree units required')
        if getattr(robot.config, 'cameras', None):
            raise ValueError('Wrist backend requires a joint-only robot config without cameras')
        if getattr(robot.config, 'max_relative_target', None) is not None:
            raise ValueError('SDK clipping would alter the validated joint path; use bridge joint-step limits')
        for name in ARM_JOINTS:
            low, high = joint_limits_deg[name]
            speed = velocity_limits_deg_s[name]
            if not all(math.isfinite(x) for x in (low, high, speed)) or low >= high or speed <= 0:
                raise ValueError('Invalid commissioned joint limits')
        if not 0 < position_tolerance_m <= .005 or not 0 < orientation_tolerance_rad <= .1:
            raise ValueError('Invalid FK residual tolerances')
        self.robot, self.kinematics = robot, kinematics
        self.kinematics_lock = threading.RLock()
        self.limits, self.speeds = joint_limits_deg, velocity_limits_deg_s
        self.path_validator = path_validator
        self.position_tolerance = position_tolerance_m
        self.orientation_tolerance = orientation_tolerance_rad

    @staticmethod
    def valid_pose(pose):
        import numpy as np
        return (pose.shape == (4,4) and np.isfinite(pose).all() and
                np.allclose(pose[3], [0,0,0,1], atol=1e-6) and
                np.allclose(pose[:3,:3].T @ pose[:3,:3], np.eye(3), atol=1e-6) and
                abs(np.linalg.det(pose[:3,:3])-1.) < 1e-6)

    def observe(self):
        import numpy as np
        raw = self.robot.get_observation()
        joints = {name+'.pos': float(raw[name+'.pos']) for name in ARM_JOINTS+['gripper']}
        if not all(math.isfinite(x) for x in joints.values()) or not 0 <= joints['gripper.pos'] <= 100:
            raise ValueError('Invalid robot observation')
        with self.kinematics_lock:
            pose = np.array(self.kinematics.forward_kinematics(np.array([joints[n+'.pos'] for n in ARM_JOINTS])), copy=True)
        if not self.valid_pose(pose):
            raise ValueError('Invalid forward kinematics')
        return dict(joints=joints, ee_position_m=pose[:3,3].tolist(),
                    ee_rotation=pose[:3,:3].reshape(-1).tolist(), synthetic=False,
                    joint_units={'arm':'deg','gripper':'normalized_0_100'},
                    ee_state_source='joint_encoder_forward_kinematics')

    def solve(self, position, reference, observation):
        import numpy as np
        desired = np.eye(4)
        desired[:3,3] = position
        desired[:3,:3] = np.array(reference['ee_rotation']).reshape(3,3)
        if not self.valid_pose(desired):
            raise ValueError('Invalid reference pose')
        with self.kinematics_lock:
            q = np.asarray(self.kinematics.inverse_kinematics(
                np.array([observation['joints'][n+'.pos'] for n in ARM_JOINTS]), desired,
                orientation_weight=1.))
        if q.shape != (5,) or not np.isfinite(q).all():
            raise ValueError('IK must return five finite arm joint values in degrees')
        action = {n+'.pos': float(v) for n,v in zip(ARM_JOINTS,q)}
        action['gripper.pos'] = reference['joints']['gripper.pos']
        return action

    def validate(self, action, position, reference, observation, dt):
        import numpy as np
        if not math.isfinite(dt) or dt <= 0 or set(action) != {n+'.pos' for n in ARM_JOINTS+['gripper']} or not all(math.isfinite(v) for v in action.values()):
            return False
        for name in ARM_JOINTS:
            q = action[name+'.pos']
            low, high = self.limits[name]
            if not low <= q <= high or abs(q-observation['joints'][name+'.pos']) > self.speeds[name]*dt:
                return False
        if action['gripper.pos'] != reference['joints']['gripper.pos']:
            return False
        with self.kinematics_lock:
            pose = np.array(self.kinematics.forward_kinematics(np.array([action[n+'.pos'] for n in ARM_JOINTS])),copy=True)
        if not self.valid_pose(pose):
            return False
        if np.linalg.norm(pose[:3,3]-position) > self.position_tolerance:
            return False
        rotation_error = np.array(reference['ee_rotation']).reshape(3,3).T @ pose[:3,:3]
        angle = math.acos(float(np.clip((np.trace(rotation_error)-1)/2, -1, 1)))
        if angle > self.orientation_tolerance:
            return False
        # Check entire interpolated path, fixtures, and measured EE tracking/speed.
        return self.path_validator(observation, action, dt) is True

    def send(self, action):
        sent = self.robot.send_action(action)
        if set(sent) != set(action) or any(not math.isfinite(sent[k]) or abs(sent[k]-action[k]) > 1e-6 for k in action):
            raise ActionMismatchError(sent)
        return sent

    def hold(self):
        raw = self.robot.get_observation()
        action = {n+'.pos': float(raw[n+'.pos']) for n in ARM_JOINTS+['gripper']}
        if not all(math.isfinite(v) for v in action.values()) or not 0 <= action['gripper.pos'] <= 100:
            raise ValueError('Cannot hold invalid observation')
        return self.send(action)
