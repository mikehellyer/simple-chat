from simple_chat import app


def test_self_test_passes():
    assert app.self_test() == 0
