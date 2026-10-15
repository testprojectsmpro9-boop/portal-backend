from app.utils.security import hash_password, verify_password


def test_hash_password_not_plaintext():
    hashed = hash_password("mysecretpassword")
    assert hashed != "mysecretpassword"
    assert len(hashed) > 20


def test_verify_password_correct():
    hashed = hash_password("mysecretpassword")
    assert verify_password("mysecretpassword", hashed) is True


def test_verify_password_wrong():
    hashed = hash_password("mysecretpassword")
    assert verify_password("wrongpassword", hashed) is False
