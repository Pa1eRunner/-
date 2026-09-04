import pytest

from newsbot.dingtalk import DingTalkClient


def test_rejects_non_dingtalk_webhook() -> None:
    with pytest.raises(ValueError):
        DingTalkClient("https://example.com/hook", "信源")


def test_rejects_message_without_security_keyword() -> None:
    client = DingTalkClient(
        "https://oapi.dingtalk.com/robot/send?access_token=test",
        "信源",
    )
    with pytest.raises(ValueError):
        client.send_markdown("行业快讯", "不包含安全词")

