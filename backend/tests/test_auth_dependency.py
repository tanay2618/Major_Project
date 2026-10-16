import types
from datetime import timedelta

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import auth


class FakeDB:
    def __init__(self, user):
        self.user = user

    def get(self, model, pk):
        return self.user if self.user is not None and self.user.id == pk else None


def creds(token):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_valid_token_returns_user():
    user = types.SimpleNamespace(id=7, is_active=True)
    token = auth.create_access_token({"sub": "7", "role": "applicant"})
    assert auth.get_current_user(creds(token), FakeDB(user)) is user


@pytest.mark.parametrize("bad", ["garbage", "a.b.c", ""])
def test_bad_token_rejected(bad):
    with pytest.raises(HTTPException) as e:
        auth.get_current_user(creds(bad), FakeDB(None))
    assert e.value.status_code == 401


def test_missing_credentials_rejected():
    with pytest.raises(HTTPException) as e:
        auth.get_current_user(None, FakeDB(None))
    assert e.value.status_code == 401


def test_expired_token_rejected():
    user = types.SimpleNamespace(id=7, is_active=True)
    token = auth.create_access_token({"sub": "7"}, expires_delta=timedelta(seconds=-5))
    with pytest.raises(HTTPException):
        auth.get_current_user(creds(token), FakeDB(user))


def test_inactive_or_missing_user_rejected():
    token = auth.create_access_token({"sub": "7"})
    with pytest.raises(HTTPException):
        auth.get_current_user(creds(token), FakeDB(types.SimpleNamespace(id=7, is_active=False)))
    with pytest.raises(HTTPException):
        auth.get_current_user(creds(token), FakeDB(None))
