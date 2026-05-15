from app.diff.detector import DiffDetector, Message


def msg(text: str, y: int = 0) -> Message:
    return Message(text=text, y_top=y, y_bottom=y + 10)


def test_first_frame_all_new():
    det = DiffDetector(lru_frames=20)
    new = det.detect([msg("A"), msg("B", 20)])
    assert [m.text for m in new] == ["A", "B"]


def test_identical_second_frame_no_new():
    det = DiffDetector(lru_frames=20)
    det.detect([msg("A"), msg("B", 20)])
    new = det.detect([msg("A"), msg("B", 20)])
    assert new == []


def test_one_new_message_detected():
    det = DiffDetector(lru_frames=20)
    det.detect([msg("A")])
    new = det.detect([msg("A"), msg("B", 20)])
    assert [m.text for m in new] == ["B"]


def test_fuzzy_match_treats_ocr_noise_as_same():
    det = DiffDetector(lru_frames=20, fuzzy_threshold=2)
    det.detect([msg("这是一条测试消息")])
    # OCR 抖动：少识别一个字
    new = det.detect([msg("这是一条试消息")])
    assert new == []


def test_fuzzy_threshold_zero_disables_fuzzy():
    det = DiffDetector(lru_frames=20, fuzzy_threshold=0)
    det.detect([msg("这是一条测试消息")])
    new = det.detect([msg("这是一条试消息")])
    assert [m.text for m in new] == ["这是一条试消息"]


def test_lru_eviction_makes_old_messages_new_again():
    det = DiffDetector(lru_frames=2, fuzzy_threshold=0)
    det.detect([msg("A")])  # frame 0
    det.detect([msg("B")])  # frame 1
    det.detect([msg("C")])  # frame 2 -> frame 0 evicted
    new = det.detect([msg("A")])  # A 不在窗口 → 新
    assert [m.text for m in new] == ["A"]


def test_sorted_by_y_top():
    det = DiffDetector(lru_frames=20)
    new = det.detect([msg("C", 30), msg("A", 0), msg("B", 15)])
    assert [m.text for m in new] == ["A", "B", "C"]


def test_empty_text_ignored():
    det = DiffDetector(lru_frames=20)
    new = det.detect([msg(""), msg("real", 20)])
    assert [m.text for m in new] == ["real"]


def test_scroll_window_dedup():
    """模拟聊天滚动：前帧 [A,B,C]，下帧 [B,C,D] → 只新增 D。"""
    det = DiffDetector(lru_frames=20, fuzzy_threshold=0)
    det.detect([msg("A", 0), msg("B", 20), msg("C", 40)])
    new = det.detect([msg("B", 0), msg("C", 20), msg("D", 40)])
    assert [m.text for m in new] == ["D"]
