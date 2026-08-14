import os

from newsbot.config import load_env_file


def test_load_env_file_sets_missing_values(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DINGTALK_WEBHOOK", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nDINGTALK_WEBHOOK='https://oapi.dingtalk.com/robot/send?access_token=test'\n",
        encoding="utf-8",
    )
    assert load_env_file(env_file)
    assert os.environ["DINGTALK_WEBHOOK"].endswith("access_token=test")


def test_load_env_file_does_not_override_process_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DINGTALK_WEBHOOK", "from-process")
    env_file = tmp_path / ".env"
    env_file.write_text("DINGTALK_WEBHOOK=from-file\n", encoding="utf-8")
    load_env_file(env_file)
    assert os.environ["DINGTALK_WEBHOOK"] == "from-process"
