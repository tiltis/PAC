import unittest
from types import SimpleNamespace
import numpy as np
from so101_backend import ARM_JOINTS, So101Backend
from robot_bridge import Bridge
from workspace import Workspace


class FakeSDK:
    config = SimpleNamespace(use_degrees=True)
    def __init__(self):
        self.sent = []
    def get_observation(self):
        return {**{n+'.pos':0. for n in ARM_JOINTS},'gripper.pos':35.}
    def send_action(self, action):
        self.sent.append(dict(action))
        return dict(action)


class FakeKinematics:
    joint_names = ARM_JOINTS
    def forward_kinematics(self, q):
        pose = np.eye(4)
        pose[:3,3] = [.3+q[0]*.001,0,.2]
        return pose
    def inverse_kinematics(self, q, desired, **kwargs):
        self.last_q = q
        self.last_desired = desired
        return np.array([1.,0.,0.,0.,0.])


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.sdk = FakeSDK()
        self.ik = FakeKinematics()
        self.backend = So101Backend(self.sdk,self.ik,
            {n:(-90.,90.) for n in ARM_JOINTS},
            {n:60. for n in ARM_JOINTS}, lambda *args:True)
        self.obs = self.backend.observe()
        self.action = self.backend.solve([.301,0,.2],self.obs,self.obs)

    def test_gripper_excluded_from_ik_and_preserved(self):
        self.assertEqual(len(self.ik.last_q),5)
        self.assertEqual(self.action['gripper.pos'],35.)
        np.testing.assert_allclose(self.ik.last_desired[:3,:3],np.eye(3))

    def test_joint_velocity_limit(self):
        self.assertFalse(self.backend.validate(self.action,[.301,0,.2],self.obs,self.obs,.001))
        self.assertTrue(self.backend.validate(self.action,[.301,0,.2],self.obs,self.obs,.04))

    def test_fk_residual(self):
        self.assertFalse(self.backend.validate(self.action,[.35,0,.2],self.obs,self.obs,.04))

    def test_collision_gate(self):
        self.backend.path_validator = lambda *args:False
        self.assertFalse(self.backend.validate(self.action,[.301,0,.2],self.obs,self.obs,.04))
        self.assertEqual(self.sdk.sent,[])

    def test_joint_limit(self):
        self.backend.limits['shoulder_pan'] = (-.5,.5)
        self.assertFalse(self.backend.validate(self.action,[.301,0,.2],self.obs,self.obs,.04))

    def test_hold_uses_observation_and_sdk_return(self):
        self.assertEqual(self.backend.hold(),self.sdk.get_observation())
        self.assertEqual(len(self.sdk.sent),1)

    def test_wrong_ik_vector_rejected_before_send(self):
        self.ik.inverse_kinematics = lambda *args,**kwargs: np.array([1.,2.])
        with self.assertRaisesRegex(ValueError,'five'):
            self.backend.solve([.301,0,.2],self.obs,self.obs)
        self.assertEqual(self.sdk.sent,[])

    def test_invalid_reference_rotation_rejected(self):
        bad = dict(self.obs,ee_rotation=[0]*9)
        with self.assertRaisesRegex(ValueError,'reference'):
            self.backend.solve([.301,0,.2],bad,self.obs)

    def test_orientation_error_rejected(self):
        original = self.ik.forward_kinematics
        def rotated(q):
            pose = original(q)
            pose[:3,:3] = [[0,-1,0],[1,0,0],[0,0,1]]
            return pose
        self.ik.forward_kinematics = rotated
        self.assertFalse(self.backend.validate(self.action,[.301,0,.2],self.obs,self.obs,.04))

    def test_normalized_arm_units_rejected(self):
        self.sdk.config = SimpleNamespace(use_degrees=False)
        with self.assertRaisesRegex(ValueError,'degree'):
            So101Backend(self.sdk,self.ik,self.backend.limits,self.backend.speeds,lambda *args:True)

    def test_existing_sdk_adapter_through_bridge_and_watchdog(self):
        # This uses fake SDK and fake kinematics; it never opens hardware ports.
        w = Workspace(x=(.25,.35),y=(-.02,.02),z=.2,profile='commissioned')
        now = [10.]
        bridge = Bridge(self.backend,clock=lambda:now[0],workspace=w)
        state = dict(position_m=[.31,0.,.2],motion_enabled=True,frame_id=1,
                     frame_age_s=0.,coordinate_frame='robot_base',units='m',workspace=w.metadata())
        self.assertTrue(bridge.receive(state,now[0]))
        self.assertTrue(bridge.arm())
        now[0] += .04
        self.assertTrue(bridge.step())
        self.assertEqual(self.sdk.sent[-1]['shoulder_pan.pos'],1.)
        self.assertEqual(self.sdk.sent[-1]['gripper.pos'],35.)
        now[0] += .201
        bridge.watchdog()
        self.assertFalse(bridge.enabled)
        self.assertEqual(self.sdk.sent[-1],self.sdk.get_observation())

    def test_arm_and_step_same_tick_preserves_armed_sdk_bridge(self):
        w = Workspace(x=(.25,.35),y=(-.02,.02),z=.2,profile='commissioned')
        now = [10.]
        bridge = Bridge(self.backend,clock=lambda:now[0],workspace=w)
        state = dict(position_m=[.31,0.,.2],motion_enabled=True,frame_id=1,
                     frame_age_s=0.,coordinate_frame='robot_base',units='m',workspace=w.metadata())
        self.assertTrue(bridge.receive(state,now[0]))
        self.assertTrue(bridge.arm())
        self.assertTrue(bridge.step())
        self.assertTrue(bridge.enabled)
        self.assertEqual(self.sdk.sent, [])
        now[0] += .04
        self.assertTrue(bridge.step())
        self.assertEqual(len(self.sdk.sent), 1)

    def test_sdk_clipping_configuration_rejected(self):
        self.sdk.config = SimpleNamespace(use_degrees=True,max_relative_target=1.)
        with self.assertRaisesRegex(ValueError,'clipping'):
            So101Backend(self.sdk,self.ik,self.backend.limits,self.backend.speeds,lambda *args:True)

    def test_altered_sdk_return_raises_for_bridge_to_hold(self):
        self.sdk.send_action = lambda action: dict(action,**{'shoulder_pan.pos':.5})
        with self.assertRaisesRegex(ValueError,'altered'):
            self.backend.send(self.action)


if __name__ == '__main__':
    unittest.main()
