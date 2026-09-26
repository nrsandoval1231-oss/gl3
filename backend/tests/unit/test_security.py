import time

from gridlens.security import token_for, valid_token


def test_session_token_is_signed_and_expiring():
    token = token_for(int(time.time()) + 60)
    assert valid_token(token)
    assert not valid_token(token + "x")
    assert not valid_token(token_for(int(time.time()) - 1))
