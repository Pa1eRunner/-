from newsbot.webtext import decoded_response_text


class FakeResponse:
    encoding = "ISO-8859-1"
    apparent_encoding = "utf-8"

    @property
    def text(self) -> str:
        return "中文正文" if self.encoding == "utf-8" else "ä¸­æ–‡æ­£æ–‡"


def test_uses_apparent_encoding_when_http_default_is_latin1() -> None:
    response = FakeResponse()
    assert decoded_response_text(response) == "中文正文"
