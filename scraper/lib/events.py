"""
打席結果の分類
===============
スポナビの打席結果テキスト（result_summary）を構造化イベントに変換する。

実データで確認した表記例:
    右本塁打 ＋1点 / 右中本塁打 ＋3点 / 中2塁打 / 右安打
    一ゴロ / 左飛 / 空振り三振 / 見逃し三振 / 四球 / 死球

方針:
  - 公式ボックススコアに無い「二塁打・三塁打・犠飛」をここで復元する
  - 判別できないものは推測で埋めず None / 0 のままにする
"""

import re

# 打球方向の頭文字（打者の結果テキストの先頭に付く）
DIRECTIONS = "投捕一二三遊左中右"

# 全角/半角/漢数字のゆれを吸収
_DOUBLE = re.compile(r"(?:二|2|２)塁打")
_TRIPLE = re.compile(r"(?:三|3|３)塁打")


def _clean(rs: str | None) -> str:
    return (rs or "").strip()


def parse_rbi(rs: str | None) -> int:
    """「＋2点」から打点を取り出す（全角・半角プラス両対応）"""
    m = re.search(r"[＋+](\d+)\s*点", _clean(rs))
    return int(m.group(1)) if m else 0


def classify_result(rs: str | None) -> dict:
    """
    打席結果を分類して返す。

    返り値のキー:
      pa           打席（打席として成立していれば1）
      ab           打数
      hit/single/double/triple/hr
      bb           四球  hbp 死球
      so           三振   sf 犠飛   sh 犠打
      gidp         併殺打  error 相手失策で出塁
      rbi          打点
      out_type     ゴロ/フライ/ライナー/三振 など（分かる範囲）
      direction    打球方向の1文字（分かる範囲）
      valid        打席として集計対象か
    """
    s = _clean(rs)
    ev = {
        "pa": 0, "ab": 0, "hit": 0, "single": 0, "double": 0, "triple": 0,
        "hr": 0, "bb": 0, "ibb": 0, "hbp": 0, "so": 0, "sf": 0, "sh": 0,
        "gidp": 0, "error": 0, "rbi": 0,
        "out_type": None, "direction": None, "valid": False,
    }
    if not s or "試合前" in s:
        return ev

    ev["valid"] = True
    ev["pa"] = 1
    ev["rbi"] = parse_rbi(s)

    # 打球方向（先頭1文字。「右中」「左中」は先頭のみ採用）
    if s and s[0] in DIRECTIONS:
        ev["direction"] = s[0]

    # --- 打数に数えないもの ---
    if "敬遠" in s or "四球" in s:
        # 敬遠（故意四球）も四球に含めつつ、内訳として別に持つ
        ev["bb"] = 1
        if "敬遠" in s or "故意四球" in s:
            ev["ibb"] = 1
        return ev
    if "死球" in s:
        ev["hbp"] = 1
        return ev
    if "犠飛" in s:
        ev["sf"] = 1
        ev["out_type"] = "フライ"
        return ev
    if "犠打" in s or "犠barbunt" in s or "送りバント" in s:
        ev["sh"] = 1
        ev["out_type"] = "バント"
        return ev

    # 相手の失策・野選での出塁（打数には数える）
    if "失策" in s or "エラー" in s:
        ev["ab"] = 1
        ev["error"] = 1
        ev["out_type"] = "失策"
        return ev

    # --- ここから打数にカウント ---
    ev["ab"] = 1

    if "三振" in s:
        ev["so"] = 1
        ev["out_type"] = "三振"
        return ev

    if "本塁打" in s:
        ev["hit"] = ev["hr"] = 1
        ev["out_type"] = None
        return ev
    if _TRIPLE.search(s):
        ev["hit"] = ev["triple"] = 1
        return ev
    if _DOUBLE.search(s):
        ev["hit"] = ev["double"] = 1
        return ev
    if "安打" in s:
        ev["hit"] = ev["single"] = 1
        return ev

    # --- アウトの種類 ---
    if "併殺" in s:
        ev["gidp"] = 1
        ev["out_type"] = "併殺"
    elif "ゴロ" in s:
        ev["out_type"] = "ゴロ"
    elif "邪飛" in s:
        ev["out_type"] = "邪飛"
    elif "飛" in s:
        ev["out_type"] = "フライ"
    elif "直" in s or "ライナー" in s:
        ev["out_type"] = "ライナー"

    return ev


# ---- 投球単位 ----

# 投球結果 → スイングしたか / コンタクトしたか
_SWING_MISS = ("空振り",)
_CALLED = ("見逃し",)
_FOUL = ("ファウル", "ファール")
_BALL = ("ボール",)


def classify_pitch(result: str | None, kind: str | None) -> dict:
    """
    1球の結果を分類する。
      is_swing    スイングした
      is_miss     空振り
      is_called   見逃しストライク
      is_foul     ファウル
      is_ball     ボール
      is_inplay   インプレー（打球が飛んだ）
      is_strike   ストライクとしてカウントされる
    """
    r = (result or "").strip()
    k = (kind or "").strip()

    d = {"is_swing": False, "is_miss": False, "is_called": False,
         "is_foul": False, "is_ball": False, "is_inplay": False,
         "is_strike": False}

    if any(x in r for x in _BALL):
        d["is_ball"] = True
        return d
    if any(x in r for x in _SWING_MISS):
        d.update(is_swing=True, is_miss=True, is_strike=True)
        return d
    if any(x in r for x in _CALLED):
        d.update(is_called=True, is_strike=True)
        return d
    if any(x in r for x in _FOUL):
        d.update(is_swing=True, is_foul=True, is_strike=True)
        return d

    # 上記以外で結果テキストがある＝打球が飛んだ（安打・凡打・犠打）
    if r or k in ("hit", "out", "bunt"):
        d.update(is_swing=True, is_inplay=True)
    return d


def count_before(pitches: list, idx: int) -> tuple[int, int]:
    """
    idx番目の投球を投げる直前のボール・ストライクカウントを求める。
    公式のBSO表示は打席全体の状態なので、投球列から自前で積み上げる。
    """
    b = s = 0
    for i in range(idx):
        p = pitches[i]
        c = classify_pitch(p.get("result"), p.get("kind"))
        if c["is_ball"]:
            b = min(b + 1, 3)
        elif c["is_foul"]:
            if s < 2:
                s += 1
        elif c["is_strike"]:
            s = min(s + 1, 2)
    return b, s
