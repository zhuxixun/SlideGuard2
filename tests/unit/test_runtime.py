import socket

from slideguard.app import _loopback_listener, _server_config


def test_listener_uses_ipv4_loopback_and_random_port() -> None:
    listener = _loopback_listener()
    try:
        host, port = listener.getsockname()
        assert listener.family == socket.AF_INET
        assert host == "127.0.0.1"
        assert port > 0
    finally:
        listener.close()


def test_windowed_server_disables_uvicorn_default_logging() -> None:
    config = _server_config(object(), 12345)

    assert config.log_config is None
    assert config.access_log is False
