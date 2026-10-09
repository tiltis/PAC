"""Reject boolean/float association attempts even when Python equality matches."""
import pytest
from test_sensor_association import client_with_handler


@pytest.mark.parametrize("attempt,value", [(0, False), (1, True), (0, 0.0), (1, 1.0)])
def test_nested_attempt_requires_integer(attempt, value):
    client = client_with_handler(
        lambda result: result["sensor_data"]["association"].update(attempt=value))
    try:
        assert client.inspect("t", "S01", "A", attempt)["status"] == "error"
    finally:
        client.close()
