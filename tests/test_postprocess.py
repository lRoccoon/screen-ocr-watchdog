from app.ocr.postprocess import _is_noise, aggregate_cards


def _block(text: str, y_top: int, y_bot: int):
    bbox = [[0, y_top], [100, y_top], [100, y_bot], [0, y_bot]]
    return (bbox, text, 0.99)


def test_noise_detection():
    assert _is_noise("14:30")
    assert _is_noise("14:30:00")
    assert _is_noise("2025-05-16")
    assert _is_noise("...")
    assert _is_noise("   ")
    assert _is_noise("")
    assert not _is_noise("你好")
    assert not _is_noise("hello world")


def test_aggregate_groups_by_gap():
    blocks = [
        _block("用户A", 10, 25),
        _block("早上好", 26, 41),
        _block("用户B", 80, 95),
        _block("回复 用户A 我也是", 96, 111),
    ]
    cards = aggregate_cards(blocks, card_gap=20)
    assert len(cards) == 2
    assert cards[0].text == "用户A\n早上好"
    assert cards[1].text == "用户B\n回复 用户A 我也是"


def test_aggregate_filters_noise():
    blocks = [
        _block("14:30", 10, 25),
        _block("正文一", 26, 41),
        _block(":::", 60, 75),
        _block("正文二", 80, 95),
    ]
    cards = aggregate_cards(blocks, card_gap=12)
    joined = " ".join(c.text for c in cards)
    assert "14:30" not in joined
    assert ":::" not in joined
    assert "正文一" in joined
    assert "正文二" in joined


def test_aggregate_empty_input():
    assert aggregate_cards([]) == []


def test_aggregate_unsorted_input_is_sorted():
    blocks = [
        _block("第三", 80, 95),
        _block("第一", 10, 25),
        _block("第二", 26, 41),
    ]
    cards = aggregate_cards(blocks, card_gap=50)
    # gap 足够大覆盖 41→80 间距，三块合一卡，按 y 排序
    assert len(cards) == 1
    assert cards[0].text == "第一\n第二\n第三"
