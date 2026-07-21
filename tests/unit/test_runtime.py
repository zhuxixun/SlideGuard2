import socket

from slideguard.app import _loopback_listener


def test_listener_uses_ipv4_loopback_and_random_port() -> None:
    listener = _loopback_listener()
    try:
        host, port = listener.getsockname()
        assert listener.family == socket.AF_INET
        assert host == "127.0.0.1"
        assert port > 0
    finally:
        listener.close()

