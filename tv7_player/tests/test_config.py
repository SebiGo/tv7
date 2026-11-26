"""config.log_once: an error of a step that runs again and again is logged once, and again when it changes."""

from tv7 import config


def test_log_once(capsys):
    where = "test step"
    config.log_ok(where)
    for _ in range(3):
        config.log_once(where, ValueError("broken"))
    assert capsys.readouterr().out.count("test step: ValueError: broken") == 1, "the same error only once"
    config.log_once(where, ValueError("other"))
    assert "ValueError: other" in capsys.readouterr().out, "a new error is logged"
    config.log_ok(where)
    config.log_once(where, ValueError("other"))
    assert "ValueError: other" in capsys.readouterr().out, "after it worked, the error is logged again"
