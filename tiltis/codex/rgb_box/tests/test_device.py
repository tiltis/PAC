from types import SimpleNamespace

import pytest

from device import select_device, synchronize


def test_cuda_requested_without_gpu_is_an_error_not_cpu_fallback():
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    with pytest.raises(RuntimeError, match="GPU unavailable"):
        select_device("cuda", torch)


def test_available_gpu_is_selected():
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True))
    assert select_device("cuda", torch) == "cuda"


def test_cpu_timing_does_not_call_cuda():
    synchronize(SimpleNamespace(), "cpu")


def test_cuda_timing_waits_for_gpu_execution():
    calls = []
    synchronize(SimpleNamespace(cuda=SimpleNamespace(synchronize=lambda: calls.append(True))), "cuda")
    assert calls == [True]
