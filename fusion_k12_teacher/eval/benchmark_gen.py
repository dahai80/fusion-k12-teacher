"""BNUP 评估基准集生成器 — 300-500 题域内/域外/对抗 (issue #24 A5)。

从 train_bridge_bank.json (134 题) + 7 个模板生成器组装 360 题:
  60% in-domain (216): 134 train_bridge + 82 其他 7 模板
  20% OOD (72): 人教版/苏教版应用题 + 初中物理
  20% adversarial (72): 单位混用/冗余条件/表达模糊

运行: python -m fusion_k12_teacher.eval.benchmark_gen
输出: fusion_k12_teacher/eval/data/bnup_benchmark.json
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent / "data"
_TRAIN_BANK = Path(__file__).parent.parent / "course" / "subjects" / "math" / "data" / "train_bridge_bank.json"
_OUTPUT = _DATA_DIR / "bnup_benchmark.json"


def _item(
    item_id: str,
    question: str,
    ground_truth: float,
    category: str,
    grade: int,
    topic: str,
    template_type: str,
    visual_type: str,
    variables: dict[str, Any] | None = None,
    misconception_tags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "question": question,
        "ground_truth": ground_truth,
        "category": category,
        "grade": grade,
        "topic": topic,
        "template_type": template_type,
        "expected_visual_type": visual_type,
        "variables": variables or {},
        "misconception_tags": misconception_tags or [],
    }


def _load_train_bridge() -> list[dict[str, Any]]:
    with open(_TRAIN_BANK, encoding="utf-8") as f:
        data = json.load(f)
    problems = data.get("problems", [])
    items = []
    seen_ids: set[str] = set()
    for p in problems:
        expected = p.get("expected", {})
        gt = 0.0
        for pref in ("answer", "t", "total_time", "result", "final"):
            if pref in expected and isinstance(expected[pref], (int, float)):
                gt = float(expected[pref])
                break
        if gt == 0.0:
            for v in reversed(list(expected.values())):
                if isinstance(v, (int, float)):
                    gt = float(v)
                    break
        base_id = f"ind-{p['id']}"
        item_id = base_id
        suffix = 2
        while item_id in seen_ids:
            item_id = f"{base_id}-{suffix}"
            suffix += 1
        seen_ids.add(item_id)
        items.append(_item(
            item_id=item_id,
            question=p.get("problem_text", ""),
            ground_truth=gt,
            category="in_domain",
            grade=5,
            topic="火车过桥",
            template_type=p.get("template_id", "train_crossing_bridge"),
            visual_type="track_timeline",
            variables=p.get("variables", {}),
            misconception_tags=p.get("misconception_tags", []),
        ))
    logger.info("loaded %d train_bridge problems", len(items))
    return items


def _gen_array_grid(rng: random.Random) -> list[dict[str, Any]]:
    items = []
    templates = [
        ("{rows}行{cols}列苹果阵列, 一共有几个苹果?", lambda r, c: r * c, "array_grid", "乘法阵列"),
        ("教室里有{rows}排桌子, 每排{cols}张, 一共多少张桌子?", lambda r, c: r * c, "array_grid", "乘法阵列"),
        ("小明摆了{rows}行{cols}列积木, 共多少块?", lambda r, c: r * c, "array_grid", "乘法阵列"),
        ("花坛里有{rows}行花, 每行{cols}朵, 一共多少朵花?", lambda r, c: r * c, "array_grid", "乘法阵列"),
    ]
    for i in range(12):
        r, c = rng.randint(2, 9), rng.randint(2, 9)
        grade = rng.choice([1, 2])
        tmpl = templates[i % len(templates)]
        items.append(_item(
            item_id=f"ind-ag-{i+1:02d}",
            question=tmpl[0].format(rows=r, cols=c),
            ground_truth=float(tmpl[1](r, c)),
            category="in_domain",
            grade=grade,
            topic=tmpl[3],
            template_type="array_counting",
            visual_type=tmpl[2],
            variables={"rows": r, "cols": c},
            misconception_tags=["count_error"],
        ))
    return items


def _gen_tape_diagram(rng: random.Random) -> list[dict[str, Any]]:
    items = []
    for i in range(12):
        b = rng.randint(3, 20)
        multiple = rng.randint(2, 5)
        a = b * multiple
        total = a + b
        grade = rng.choice([3, 4])
        qtype = i % 3
        if qtype == 0:
            q = f"甲数是乙数的{multiple}倍, 甲乙两数共{total}, 求乙数。"
            gt = float(b)
        elif qtype == 1:
            q = f"甲数是乙数的{multiple}倍, 甲数比乙数多{a - b}, 求乙数。"
            gt = float(b)
        else:
            q = f"甲数比乙数的{multiple}倍多{rng.randint(1, 5)}, 甲数是{a + rng.randint(1, 5)}, 求乙数。"
            gt = float(b)
        items.append(_item(
            item_id=f"ind-td-{i+1:02d}",
            question=q,
            ground_truth=gt,
            category="in_domain",
            grade=grade,
            topic="和差倍比",
            template_type="sum_multiple",
            visual_type="tape_diagram",
            variables={"a": a, "b": b, "multiple": multiple},
            misconception_tags=["multiple_confusion"],
        ))
    return items


def _gen_geometry_2d(rng: random.Random) -> list[dict[str, Any]]:
    items = []
    for i in range(12):
        length = rng.randint(4, 20)
        width = rng.randint(3, 15)
        grade = rng.choice([3, 4, 5])
        qtype = i % 3
        if qtype == 0:
            q = f"长方形长{length}厘米宽{width}厘米, 求面积。"
            gt = float(length * width)
            topic = "长方形面积"
        elif qtype == 1:
            q = f"长方形长{length}厘米宽{width}厘米, 求周长。"
            gt = float(2 * (length + width))
            topic = "长方形周长"
        else:
            side = rng.randint(3, 15)
            q = f"正方形边长{side}厘米, 求面积。"
            gt = float(side * side)
            topic = "正方形面积"
        items.append(_item(
            item_id=f"ind-g2d-{i+1:02d}",
            question=q,
            ground_truth=gt,
            category="in_domain",
            grade=grade,
            topic=topic,
            template_type="rectangle_area",
            visual_type="geometry_2d",
            variables={"length": length, "width": width},
            misconception_tags=["perimeter_area_confusion"],
        ))
    return items


def _gen_isometric_3d(rng: random.Random) -> list[dict[str, Any]]:
    import math
    items = []
    for i in range(12):
        r = rng.randint(2, 8)
        h = rng.randint(3, 12)
        grade = rng.choice([5, 6])
        qtype = i % 2
        if qtype == 0:
            cyl_vol = math.pi * r * r * h
            q = f"圆柱底面半径{r}厘米高{h}厘米, 削成最大圆锥, 削去部分的体积是多少立方厘米? (π取3.14)"
            gt = round(cyl_vol * 2 / 3, 2)
            topic = "圆柱削圆锥"
            miscon = ["cone_third_error"]
        else:
            box_vol = r * r * h
            q = f"长方体长{r}厘米宽{r}厘米高{h}厘米, 求体积。"
            gt = float(box_vol)
            topic = "长方体体积"
            miscon = []
        items.append(_item(
            item_id=f"ind-i3d-{i+1:02d}",
            question=q,
            ground_truth=gt,
            category="in_domain",
            grade=grade,
            topic=topic,
            template_type="cylinder_cone_cut",
            visual_type="isometric_3d",
            variables={"r": r, "h": h},
            misconception_tags=miscon,
        ))
    return items


def _gen_bucket_divider(rng: random.Random) -> list[dict[str, Any]]:
    items = []
    for i in range(12):
        total = rng.randint(6, 20)
        people = rng.randint(2, 4)
        per = total // people
        remainder = total % people
        grade = rng.choice([4, 5, 6])
        if remainder == 0:
            q = f"把{total}本书平均分给{people}个人, 每人得几本?"
            gt = float(per)
        else:
            q = f"{total}个苹果分给{people}个人, 每人尽量多且一样多, 剩几个?"
            gt = float(remainder)
        items.append(_item(
            item_id=f"ind-bd-{i+1:02d}",
            question=q,
            ground_truth=gt,
            category="in_domain",
            grade=grade,
            topic="组合分配",
            template_type="equal_division",
            visual_type="bucket_divider",
            variables={"total": total, "people": people},
            misconception_tags=["remainder_error"],
        ))
    return items


def _gen_data_chart(rng: random.Random) -> list[dict[str, Any]]:
    items = []
    for i in range(12):
        count = rng.randint(4, 7)
        values = [rng.randint(10, 100) for _ in range(count)]
        avg = sum(values) / count
        grade = rng.choice([4, 5])
        qtype = i % 2
        if qtype == 0:
            vals_str = "、".join(str(v) for v in values)
            q = f"某商店{count}天销售额分别为: {vals_str} 元, 求平均日销售额。"
            gt = round(avg, 2)
            topic = "平均数"
        else:
            q = f"某地连续{count}天最高气温分别为: {'、'.join(str(v) for v in values)} 度, 求平均气温。"
            gt = round(avg, 2)
            topic = "平均数"
        items.append(_item(
            item_id=f"ind-dc-{i+1:02d}",
            question=q,
            ground_truth=gt,
            category="in_domain",
            grade=grade,
            topic=topic,
            template_type="statistics_mean",
            visual_type="data_chart",
            variables={"values": values},
            misconception_tags=["mean_division_error"],
        ))
    return items


def _gen_flow_card(rng: random.Random) -> list[dict[str, Any]]:
    items = []
    for i in range(10):
        a = rng.randint(5, 50)
        b = rng.randint(5, 50)
        grade = rng.choice([5, 6])
        qtype = i % 2
        if qtype == 0:
            c = a + b
            q = f"解方程: x + {a} = {c}, 求 x。"
            gt = float(a)
            topic = "一元一次方程"
        else:
            c = a * b
            q = f"解方程: {a}x = {c}, 求 x。"
            gt = float(b)
            topic = "一元一次方程"
        items.append(_item(
            item_id=f"ind-fc-{i+1:02d}",
            question=q,
            ground_truth=gt,
            category="in_domain",
            grade=grade,
            topic=topic,
            template_type="linear_equation",
            visual_type="flow_card",
            variables={"a": a, "b": b, "c": a + b if qtype == 0 else a * b},
            misconception_tags=[],
        ))
    return items


def _gen_ood(rng: random.Random) -> list[dict[str, Any]]:
    items = []
    for i in range(36):
        qtype = i % 4
        if qtype == 0:
            speed = rng.randint(40, 120)
            time = rng.randint(2, 8)
            q = f"一辆汽车以每小时{speed}千米的速度行驶{time}小时, 行驶了多少千米? (人教版)"
            gt = float(speed * time)
            topic = "行程问题"
            vt = "track_timeline"
        elif qtype == 1:
            price = rng.randint(3, 20)
            qty = rng.randint(5, 50)
            q = f"苹果每千克{price}元, 买{qty}千克需要多少元? (苏教版)"
            gt = float(price * qty)
            topic = "单价数量"
            vt = "tape_diagram"
        elif qtype == 2:
            mass = rng.randint(50, 500)
            density = rng.choice([1, 2, 5, 8])
            q = f"某物体质量{mass}克, 密度为{density}克/立方厘米, 求体积。 (初中物理)"
            gt = round(mass / density, 2)
            topic = "密度计算"
            vt = "flow_card"
        else:
            efficiency = rng.randint(60, 90)
            total_w = rng.randint(100, 1000)
            q = f"机械效率{efficiency}%, 总功{total_w}焦耳, 求有用功。 (初中物理)"
            gt = round(total_w * efficiency / 100, 2)
            topic = "机械效率"
            vt = "flow_card"
        items.append(_item(
            item_id=f"ood-{i+1:02d}",
            question=q,
            ground_truth=gt,
            category="ood",
            grade=rng.choice([4, 5, 6, 7]),
            topic=topic,
            template_type="ood_general",
            visual_type=vt,
            variables={},
            misconception_tags=[],
        ))
    for i in range(36):
        a = rng.randint(10, 99)
        b = rng.randint(10, 99)
        q = f"计算: {a} + {b} = ? (通用计算)"
        items.append(_item(
            item_id=f"ood-calc-{i+1:02d}",
            question=q,
            ground_truth=float(a + b),
            category="ood",
            grade=1,
            topic="加法计算",
            template_type="arithmetic",
            visual_type="flow_card",
            variables={"a": a, "b": b},
        ))
    return items


def _gen_adversarial(rng: random.Random) -> list[dict[str, Any]]:
    items = []
    for i in range(24):
        qtype = i % 3
        if qtype == 0:
            length_mm = rng.randint(100, 900)
            length_m = length_mm / 1000
            q = f"一根铁丝长{length_mm}毫米, 剪成相等的4段, 每段长多少米? (注意单位转换)"
            gt = round(length_m / 4, 4)
            topic = "单位混用"
            vt = "tape_diagram"
        elif qtype == 1:
            speed = rng.randint(40, 80)
            time = rng.randint(2, 6)
            color = rng.choice(["红色", "蓝色", "绿色"])
            q = f"一辆{color}汽车以每小时{speed}千米行驶{time}小时, 行驶多少千米? (颜色为干扰条件)"
            gt = float(speed * time)
            topic = "冗余条件"
            vt = "track_timeline"
        else:
            total = rng.randint(20, 50)
            given = rng.randint(5, total - 5)
            q = f"小明有一些苹果, 给了小红{given}个后还剩{total - given}个, 小明原有多少苹果? (表述较绕)"
            gt = float(total)
            topic = "表达模糊"
            vt = "tape_diagram"
        items.append(_item(
            item_id=f"adv-{i+1:02d}",
            question=q,
            ground_truth=gt,
            category="adversarial",
            grade=rng.choice([3, 4, 5, 6]),
            topic=topic,
            template_type="adversarial",
            visual_type=vt,
            variables={},
            misconception_tags=["unit_mixing" if qtype == 0 else "redundant" if qtype == 1 else "ambiguous"],
        ))
    for i in range(24):
        speed = rng.randint(20, 60)
        bridge = rng.randint(200, 800)
        train_len = rng.randint(100, 300)
        time_sec = (bridge + train_len) / speed
        temp = rng.choice(["今天", "昨天", "上午", "下午"])
        q = f"{temp}一列长{train_len}米的火车以{speed}米每秒通过{bridge}米大桥, 求通过时间。 (含时间干扰词)"
        items.append(_item(
            item_id=f"adv-train-{i+1:02d}",
            question=q,
            ground_truth=round(time_sec, 2),
            category="adversarial",
            grade=5,
            topic="行程过桥(对抗)",
            template_type="train_crossing_bridge",
            visual_type="track_timeline",
            variables={"L_bridge": bridge, "L_train": train_len, "v_train": speed},
            misconception_tags=["redundant", "forget_train_length"],
        ))
    for i in range(24):
        r = rng.randint(2, 6)
        h = rng.randint(4, 10)
        import math
        cyl_vol = math.pi * r * r * h
        extra = rng.randint(1, 5)
        q = f"圆柱底面半径{r}厘米高{h}厘米, 旁边有一个边长{extra}厘米的小立方体(无关条件), 削最大圆锥求削去体积。 (π取3.14)"
        items.append(_item(
            item_id=f"adv-3d-{i+1:02d}",
            question=q,
            ground_truth=round(cyl_vol * 2 / 3, 2),
            category="adversarial",
            grade=6,
            topic="圆柱圆锥(对抗)",
            template_type="cylinder_cone_cut",
            visual_type="isometric_3d",
            variables={"r": r, "h": h, "extra": extra},
            misconception_tags=["redundant", "cone_third_error"],
        ))
    return items


def generate() -> dict[str, Any]:
    rng = random.Random(42)
    items: list[dict[str, Any]] = []
    items.extend(_load_train_bridge())
    items.extend(_gen_array_grid(rng))
    items.extend(_gen_tape_diagram(rng))
    items.extend(_gen_geometry_2d(rng))
    items.extend(_gen_isometric_3d(rng))
    items.extend(_gen_bucket_divider(rng))
    items.extend(_gen_data_chart(rng))
    items.extend(_gen_flow_card(rng))
    items.extend(_gen_ood(rng))
    items.extend(_gen_adversarial(rng))

    in_count = sum(1 for i in items if i["category"] == "in_domain")
    ood_count = sum(1 for i in items if i["category"] == "ood")
    adv_count = sum(1 for i in items if i["category"] == "adversarial")
    total = len(items)

    return {
        "version": "1.0.0",
        "description": "BNUP K-12 数学评估基准集 — 域内/域外/对抗三分类 (PRD A5)",
        "total": total,
        "distribution": {
            "in_domain": in_count,
            "ood": ood_count,
            "adversarial": adv_count,
            "in_domain_pct": round(in_count / total * 100, 1),
            "ood_pct": round(ood_count / total * 100, 1),
            "adversarial_pct": round(adv_count / total * 100, 1),
        },
        "items": items,
    }


def main() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = generate()
    with open(_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    dist = data["distribution"]
    logger.info(
        "benchmark generated: %d items (in=%d ood=%d adv=%d) -> %s",
        data["total"], dist["in_domain"], dist["ood"], dist["adversarial"], _OUTPUT,
    )
    print(f"Generated {data['total']} items -> {_OUTPUT}")
    print(f"  in_domain: {dist['in_domain']} ({dist['in_domain_pct']}%)")
    print(f"  ood:       {dist['ood']} ({dist['ood_pct']}%)")
    print(f"  adversarial: {dist['adversarial']} ({dist['adversarial_pct']}%)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    main()
