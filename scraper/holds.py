"""
ホールドのルールベース算出
============================
取得元（スポナビの出場成績）はホールドを記録していないため、
打席データと出場成績から NPB のホールド条件を当てはめて推定する。

★これは推定値である★
公式記録ではないので、集計結果には "holds_est"（推定）として保持し、
表示側でも推定であることを明示する。取得元が公式のホールドを
出すようになった場合は、そちらを優先すること。

── 適用するルール ──────────────────────────
前提（すべて満たすこと）
  1. 先発ではない
  2. 勝利・敗戦・セーブのいずれも記録していない
  3. 試合の最終アウトを取った投手ではない
  4. 1つ以上のアウトを取っている
  5. 降板時にリードを保っている（同点で登板したケースを除く）

いずれかの場面に当てはまること
  A. 3点差以内のリードで1イニング（3アウト）以上を投げた
  B. 一発同点のピンチ（点差 ≦ 走者数 + 2）で1アウト以上を取った
  C. 点差に関係なく3イニング（9アウト）以上を投げた
  D. 同点で登板し、無失点で降板した（登板中に勝ち越した場合を含む）

ホールドポイント HP = ホールド + 救援勝利
"""


def _score_map(score_at):
    """score_at（[{team, score}, ...]）を {チーム名: 得点} に変換する"""
    m = {}
    for s in (score_at or []):
        t = s.get("team")
        if t is not None and s.get("score") is not None:
            m[t] = s["score"]
    return m


def _runners_on(ab):
    r = ab.get("runners") or {}
    return sum(1 for k in ("first", "second", "third") if r.get(k))


def _diff_for(score_map, my_team, opp_team):
    """自チームから見た点差。取れない場合は None"""
    if my_team not in score_map or opp_team not in score_map:
        return None
    return score_map[my_team] - score_map[opp_team]


def estimate_holds(game: dict) -> dict:
    """
    1試合ぶんのホールドを推定する。
    戻り値: {"投手名": True/False, ...}（名前をキーにする）
            判定できなかった投手はキーを作らない
    """
    atbats = [a for a in (game.get("atbats") or []) if a.get("valid", True)]
    box = game.get("boxscore") or {}
    pit = box.get("pitching") or {}
    if not atbats or not pit:
        return {}

    home = game.get("home")
    away = game.get("away")

    # 最終アウトを取った投手（＝最後の打席の投手）
    last_pitcher = None
    for ab in reversed(atbats):
        p = (ab.get("pitcher") or {}).get("name")
        if p:
            last_pitcher = p
            break

    # 投手ごとに「最初に投げた打席」「最後に投げた打席」の位置を求める
    first_idx, last_idx = {}, {}
    for i, ab in enumerate(atbats):
        name = (ab.get("pitcher") or {}).get("name")
        if not name:
            continue
        if name not in first_idx:
            first_idx[name] = i
        last_idx[name] = i

    result = {}

    for side in ("away", "home"):
        rows = pit.get(side) or []
        my_team = away if side == "away" else home
        opp_team = home if side == "away" else away

        for order, row in enumerate(rows):
            name = row.get("name")
            if not name:
                continue

            # --- 前提1: 先発でない ---
            if order == 0:
                continue
            # --- 前提2: 勝敗・セーブがついていない ---
            dec = row.get("decision") or ""
            if any(x in dec for x in ("勝", "敗", "Ｓ", "S")):
                continue
            # --- 前提3: 最終アウトを取っていない ---
            if name == last_pitcher:
                continue
            # --- 前提4: 1アウト以上 ---
            outs = row.get("outs") or 0
            if outs < 1:
                continue

            fi = first_idx.get(name)
            li = last_idx.get(name)
            if fi is None or li is None:
                continue

            entry_ab = atbats[fi]
            entry_map = _score_map(entry_ab.get("score_at"))
            diff_in = _diff_for(entry_map, my_team, opp_team)

            # 降板時の点差＝次の打席のスコア（無ければ最終スコア）
            exit_map = None
            if li + 1 < len(atbats):
                exit_map = _score_map(atbats[li + 1].get("score_at"))
            if not exit_map:
                exit_map = _score_map(game.get("final_score"))
            diff_out = _diff_for(exit_map, my_team, opp_team)

            if diff_in is None or diff_out is None:
                continue   # スコアが取れない試合は判定しない

            runners = _runners_on(entry_ab)
            runs_allowed = row.get("runs_allowed") or 0

            hold = False

            # D. 同点で登板し無失点で降板（登板中の勝ち越しを含む）
            if diff_in == 0 and runs_allowed == 0 and diff_out >= 0:
                hold = True

            # リードして登板したケースは、降板時もリードしていること
            elif diff_in > 0 and diff_out > 0:
                # A. 3点差以内で1イニング以上
                if diff_in <= 3 and outs >= 3:
                    hold = True
                # B. 一発同点のピンチ（点差 ≦ 走者数 + 2）で1アウト以上
                elif diff_in <= runners + 2 and outs >= 1:
                    hold = True
                # C. 点差不問で3イニング以上
                elif outs >= 9:
                    hold = True

            # C. 大量リードでも3イニング以上投げていれば対象
            elif diff_in > 0 and outs >= 9 and diff_out > 0:
                hold = True

            if hold:
                result[name] = True

    return result


def hold_points(holds: int, relief_wins: int) -> int:
    """ホールドポイント = ホールド + 救援勝利"""
    return (holds or 0) + (relief_wins or 0)
