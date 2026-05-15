from app.diff.normalizer import fingerprint, normalize


def test_normalize_strips_whitespace_and_punctuation():
    assert normalize("  你好,世界！  ") == "你好世界"


def test_normalize_full_to_half_width():
    # NFKC 将全角字母数字转为半角
    assert normalize("Ｈｅｌｌｏ，世界") == "Hello世界"


def test_normalize_empty():
    assert normalize("") == ""
    assert normalize("   ") == ""
    assert normalize(None) == ""  # type: ignore[arg-type]


def test_fingerprint_stable_across_whitespace():
    assert fingerprint("你好世界") == fingerprint("  你好世界  ")


def test_fingerprint_stable_across_punctuation():
    assert fingerprint("你好,世界!") == fingerprint("你好世界")


def test_fingerprint_differs_for_different_content():
    assert fingerprint("hello") != fingerprint("world")
