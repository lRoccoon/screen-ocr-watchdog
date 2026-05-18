"""ImageDiffDetector 单测：用 PIL 构造合成图，覆盖各分支。"""
from __future__ import annotations

from PIL import Image, ImageDraw

from app.diff.image_detector import ImageDiffDetector


W, H = 200, 100


def _solid(color=(255, 255, 255)) -> Image.Image:
    return Image.new("RGB", (W, H), color)


def _with_rect(color=(255, 255, 255), rect=(10, 10, 40, 40), fill=(0, 0, 0)) -> Image.Image:
    img = _solid(color)
    ImageDraw.Draw(img).rectangle(rect, fill=fill)
    return img


def test_first_frame_sets_baseline_returns_none():
    d = ImageDiffDetector()
    assert d.detect(_solid(), now=0.0) is None


def test_identical_frame_not_triggered():
    d = ImageDiffDetector()
    d.detect(_solid(), now=0.0)
    assert d.detect(_solid(), now=10.0) is None


def test_tiny_change_below_ratio_not_triggered():
    """单个像素改变远低于 0.5% 占比阈值。"""
    d = ImageDiffDetector(change_ratio_threshold=0.005)
    d.detect(_solid(), now=0.0)
    img = _solid()
    img.putpixel((0, 0), (0, 0, 0))  # 1 / 20000 = 0.005% < 0.5%
    assert d.detect(img, now=10.0) is None


def test_large_change_triggered_and_baseline_advances():
    d = ImageDiffDetector(pixel_diff_threshold=30, change_ratio_threshold=0.005, bbox_padding=0)
    d.detect(_solid(), now=0.0)
    result = d.detect(_with_rect(), now=10.0)
    assert result is not None
    bbox, crop = result
    # bbox 应覆盖刚画的矩形 (10,10,40,40)
    assert bbox[0] <= 10 and bbox[1] <= 10
    assert bbox[2] >= 40 and bbox[3] >= 40
    assert crop.size == (bbox[2] - bbox[0], bbox[3] - bbox[1])

    # 立刻再传同样的新图，基线已推进，diff=0 → 不触发
    assert d.detect(_with_rect(), now=20.0) is None


def test_bbox_padding_expands_and_clamps_to_bounds():
    d = ImageDiffDetector(pixel_diff_threshold=30, change_ratio_threshold=0.001, bbox_padding=8)
    d.detect(_solid(), now=0.0)
    # 在画面正中央画一个小变化
    result = d.detect(_with_rect(rect=(95, 45, 105, 55)), now=10.0)
    assert result is not None
    bbox, _ = result
    # padding 让 bbox 向外扩 8px
    assert bbox[0] <= 95 - 8 + 1  # 允许 ±1 容差（getbbox 边界包含语义）
    assert bbox[2] >= 105 + 8 - 1

    # 在角落画变化，padding 不能越界
    d2 = ImageDiffDetector(pixel_diff_threshold=30, change_ratio_threshold=0.001, bbox_padding=8)
    d2.detect(_solid(), now=0.0)
    result2 = d2.detect(_with_rect(rect=(0, 0, 5, 5)), now=10.0)
    assert result2 is not None
    bbox2, _ = result2
    assert bbox2[0] == 0
    assert bbox2[1] == 0


def test_min_interval_throttles_and_keeps_baseline():
    """节流期内即使 diff 超阈也不推，且基线不推进——等下一帧再评估。"""
    d = ImageDiffDetector(min_interval_seconds=5.0, pixel_diff_threshold=30, change_ratio_threshold=0.001)
    # 首帧建立基线
    d.detect(_solid(), now=0.0)
    # 第二帧触发，推送时刻 t=10
    assert d.detect(_with_rect(), now=10.0) is not None
    # 第三帧 t=11，距上次 < 5s 节流 → 返回 None，基线"应当"仍是上一次推送过的画面
    assert d.detect(_with_rect(rect=(100, 50, 150, 80)), now=11.0) is None
    # 第四帧 t=20，节流过期；diff 是相对于"上次推送过的画面"（含第一个 rect）
    # 第三帧的新 rect 在第四帧也存在 → diff 超阈 → 推送
    assert d.detect(_with_rect(rect=(100, 50, 150, 80)), now=20.0) is not None


def test_size_mismatch_resets_baseline_returns_none():
    """frame 与 baseline 尺寸不一致时，重置基线、返回 None，下一帧才开始正常对比。"""
    d = ImageDiffDetector(pixel_diff_threshold=30, change_ratio_threshold=0.001)
    d.detect(Image.new("RGB", (200, 100), (255, 255, 255)), now=0.0)
    # 不同尺寸的新帧 → 不触发，但 baseline 被替换为新尺寸
    bigger = Image.new("RGB", (300, 150), (255, 255, 255))
    assert d.detect(bigger, now=10.0) is None
    # 再来一张同尺寸但有变化的帧 → 正常触发
    bigger_changed = bigger.copy()
    ImageDraw.Draw(bigger_changed).rectangle((10, 10, 80, 80), fill=(0, 0, 0))
    result = d.detect(bigger_changed, now=20.0)
    assert result is not None
