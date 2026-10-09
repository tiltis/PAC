"""SO-101 기구학 검증. 정기구학은 독립 구현(ikpy)과 비교하고, 역기구학은 왕복 오차를 본다."""
import numpy as np
import pytest

import kinematics as K

robot = K.SO101()


def test_fk_matches_ikpy():
    ikpy_chain = pytest.importorskip("ikpy.chain")
    chain = ikpy_chain.Chain.from_urdf_file(str(K.URDF), base_elements=["base_link"],
                                            last_link_vector=None, active_links_mask=None)
    names = [l.name for l in chain.links]
    rng = np.random.default_rng(0)
    for _ in range(20):
        q = rng.uniform(robot.lower, robot.upper)
        full = np.zeros(len(chain.links))
        for jn, v in zip(K.ARM_JOINTS, q):
            full[names.index(jn)] = v
        T_ikpy = chain.forward_kinematics(full)
        assert np.allclose(robot.fk(q)[:3, 3], T_ikpy[:3, 3], atol=1e-4), (q, robot.fk(q)[:3, 3], T_ikpy[:3, 3])


def test_topdown_ik_roundtrip():
    rng = np.random.default_rng(1)
    ok, tried = 0, 0
    for _ in range(30):
        # 수직 하강이 가능한 범위(실측 지도: 높이 -2~6cm, 거리 12~28cm) 안에서만 시험
        r, az, z, yaw = rng.uniform(0.14, 0.24), rng.uniform(-1.0, 1.0), rng.uniform(0.0, 0.05), rng.uniform(-np.pi, np.pi)
        pos = np.array([r * np.cos(az), r * np.sin(az), z])
        q = robot.ik(pos, yaw=yaw)
        tried += 1
        if q is None:
            continue
        ok += 1
        pe, ae = robot.error(q, pos, np.array([0, 0, -1.0]), np.array([np.cos(yaw), np.sin(yaw), 0]))
        assert pe < 1.0 and ae < 2.0
        assert np.all(q >= robot.lower - 1e-9) and np.all(q <= robot.upper + 1e-9)
    assert ok / tried > 0.9, f"위에서 집기 역기구학 성공률이 낮음: {ok}/{tried}"


def test_unreachable_returns_none():
    assert robot.ik([0.9, 0.0, 0.05]) is None


def test_gripper_angle_and_units():
    a = K.gripper_angle_for(78)  # 78 + 15mm 여유 → 93mm
    assert 0.91 < a < 1.03
    assert K.gripper_angle_for(200) is None
    q = np.array([0.1, -0.2, 0.3, -0.4, 0.5])
    assert np.allclose(K.from_lerobot(K.to_lerobot(q)), q)
    jm = {"elbow_flex": {"sign": -1, "offset_deg": 3.0}}
    assert np.allclose(K.from_lerobot(K.to_lerobot(q, jm), jm), q)


def test_topdown_too_high_is_rejected():
    # 수직 하강 자세로 닿지 않는 높이는 엉뚱한 해 대신 None
    assert robot.ik([0.2, 0.0, 0.14], yaw=0.0) is None
