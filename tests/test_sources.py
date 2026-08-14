from datetime import datetime, timezone

from newsbot.sources import (
    _SoNewsParser,
    _SogouWeixinParser,
    _extract_toutiao_objects,
    _relative_chinese_time,
    _toutiao_direct_url,
    _toutiao_time,
    _sogou_time,
)


def test_extract_toutiao_objects() -> None:
    page = 'before(T.qf || T.flow).call(T,{ data: {"title":"棋牌新闻","publish_time":"1700000000"}});after'
    values = _extract_toutiao_objects(page)
    assert values == [{"title": "棋牌新闻", "publish_time": "1700000000"}]


def test_toutiao_direct_url_extracts_original_page() -> None:
    value = "https://article.zlink.toutiao.com/J4dQM?h5_url=https%3A%2F%2Fexample.com%2Fnews%3Fa%3D1"
    assert _toutiao_direct_url(value) == "https://example.com/news?a=1"


def test_toutiao_time_parses_epoch() -> None:
    assert _toutiao_time({"publish_time": "1700000000"}) == datetime.fromtimestamp(1700000000, tz=timezone.utc)


def test_parse_360_news_result() -> None:
    parser = _SoNewsParser()
    parser.feed(
        '<li class="res-list" data-url="https://example.com/news">'
        '<a title="闲徕互娱股权转让"><p class="summary">地方棋牌游戏运营主体变化</p>'
        '<cite class="sitename">行业媒体</cite><span class="time">2小时前</span></a></li>'
    )
    assert parser.items == [{
        "url": "https://example.com/news",
        "title": "闲徕互娱股权转让",
        "summary": "地方棋牌游戏运营主体变化",
        "source": "行业媒体",
        "time": "2小时前",
    }]


def test_parse_360_relative_time() -> None:
    now = datetime(2026, 8, 13, 8, tzinfo=timezone.utc)
    assert _relative_chinese_time("2小时前", now) == datetime(2026, 8, 13, 6, tzinfo=timezone.utc)


def test_parse_sogou_weixin_result() -> None:
    parser = _SogouWeixinParser()
    parser.feed(
        '<li id="sogou_vr_11002601_box_0"><div class="txt-box"><h3>'
        '<a href="/link?url=test"><em>棋牌</em>行业变化</a></h3>'
        '<p class="txt-info">地方麻将产品调整</p><div class="s-p">'
        '<span class="all-time-y2">主流媒体</span><span class="s2">'
        "<script>document.write(timeConvert('1700000000'))</script></span></div></div></li>"
    )
    assert parser.items == [{
        "url": "/link?url=test",
        "title": "棋牌行业变化",
        "summary": "地方麻将产品调整",
        "source": "主流媒体",
        "timestamp": "document.write(timeConvert('1700000000'))",
    }]
    assert _sogou_time(parser.items[0]["timestamp"]) == datetime.fromtimestamp(1700000000, tz=timezone.utc)
