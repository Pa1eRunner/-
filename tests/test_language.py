from newsbot.language import detect_chinese_html


def test_allows_chinese_original_page() -> None:
    page = "<html lang='zh-CN'><body>" + "这是中国棋牌游戏行业的重要新闻内容。" * 8 + "</body></html>"
    assert detect_chinese_html(page).allowed


def test_blocks_japanese_original_even_with_kanji() -> None:
    page = "<html lang='ja'><body>全国高校麻雀選手権大会を開催します。参加者を募集しています。</body></html>"
    result = detect_chinese_html(page)
    assert not result.allowed
    assert "ja" in result.reason


def test_blocks_english_original_page() -> None:
    page = "<html lang='en'><body>The official tournament announcement is published here.</body></html>"
    assert not detect_chinese_html(page).allowed


def test_allows_traditional_chinese_page() -> None:
    page = "<html lang='zh-Hant'><body>" + "本賽事採用廣東麻將規則並公開完整計分方式。" * 8 + "</body></html>"
    assert detect_chinese_html(page).allowed
