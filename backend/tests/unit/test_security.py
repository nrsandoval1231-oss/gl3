import time

from gridlens.security import token_for, valid_token


def test_session_token_is_signed_and_expiring():
    token = token_for(int(time.time()) + 60)
    assert valid_token(token)
    assert not valid_token(token + "x")
    assert not valid_token(token_for(int(time.time()) - 1))


def test_session_token_rejects_oversized_expiry_before_integer_conversion():
    assert not valid_token("9" * 4500 + "." + "0" * 64)


def test_session_token_rejects_non_ascii_expiry_digits():
    assert not valid_token("².0000000000000000000000000000000000000000000000000000000000000000")


def test_session_token_rejects_non_hex_signature():
    assert not valid_token("9999999999." + "é" * 64)
