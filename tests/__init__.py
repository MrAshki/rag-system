"""Test package safety: reject every non-loopback network connection."""
import ipaddress
import socket


_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_create_connection = socket.create_connection


def _is_local_address(address) -> bool:
    if isinstance(address, str):  # AF_UNIX / named local endpoint
        return True
    if not isinstance(address, tuple) or not address:
        return False
    host = str(address[0]).strip("[]").lower()
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _offline_connect(self, address):
    if not _is_local_address(address):
        raise AssertionError(f"non-local network connection blocked during tests: {address!r}")
    return _real_connect(self, address)


def _offline_connect_ex(self, address):
    if not _is_local_address(address):
        raise AssertionError(f"non-local network connection blocked during tests: {address!r}")
    return _real_connect_ex(self, address)


def _offline_create_connection(address, *args, **kwargs):
    if not _is_local_address(address):
        raise AssertionError(f"non-local network connection blocked during tests: {address!r}")
    return _real_create_connection(address, *args, **kwargs)


socket.socket.connect = _offline_connect
socket.socket.connect_ex = _offline_connect_ex
socket.create_connection = _offline_create_connection
