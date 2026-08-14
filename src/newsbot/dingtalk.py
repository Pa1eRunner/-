from __future__ import annotations

import time

import requests


class DingTalkError(RuntimeError):
    pass


class DingTalkClient:
    def __init__(
        self,
        webhook: str,
        security_keyword: str,
        timeout_seconds: float = 15,
        minimum_send_interval_seconds: float = 1.2,
    ) -> None:
        if not webhook.startswith("https://oapi.dingtalk.com/robot/send?"):
            raise ValueError("DingTalk webhook must use the official HTTPS endpoint")
        self.webhook = webhook
        self.security_keyword = security_keyword
        self.timeout_seconds = timeout_seconds
        self.minimum_send_interval_seconds = minimum_send_interval_seconds
        self._last_sent_at = 0.0

    def send_markdown(self, title: str, markdown: str) -> None:
        if self.security_keyword not in title and self.security_keyword not in markdown:
            raise ValueError("Message does not contain the configured DingTalk security keyword")
        wait_seconds = self.minimum_send_interval_seconds - (time.monotonic() - self._last_sent_at)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        response = requests.post(
            self.webhook,
            json={"msgtype": "markdown", "markdown": {"title": title, "text": markdown}},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        result = response.json()
        if result.get("errcode") != 0:
            raise DingTalkError(f"DingTalk rejected message: {result.get('errmsg', 'unknown error')}")
        self._last_sent_at = time.monotonic()

