"""
正規化ライブラリ
=================
チーム名・選手ID・表記ゆれを一元的に正規化する。
フェーズ1の基盤：ここを唯一の正としてマスターや集計が参照する。
"""

# 12球団の正式名称・略称・1文字表記の対応表
# key は内部正規名（短縮名）
TEAMS = {
    "ソフトバンク": {"full": "福岡ソフトバンクホークス", "mini": "ソ", "league": "パ", "id": "hawks"},
    "日本ハム": {"full": "北海道日本ハムファイターズ", "mini": "日", "league": "パ", "id": "fighters"},
    "ロッテ": {"full": "千葉ロッテマリーンズ", "mini": "ロ", "league": "パ", "id": "marines"},
    "楽天": {"full": "東北楽天ゴールデンイーグルス", "mini": "楽", "league": "パ", "id": "eagles"},
    "西武": {"full": "埼玉西武ライオンズ", "mini": "西", "league": "パ", "id": "lions"},
    "オリックス": {"full": "オリックス・バファローズ", "mini": "オ", "league": "パ", "id": "buffaloes"},
    "巨人": {"full": "読売ジャイアンツ", "mini": "巨", "league": "セ", "id": "giants"},
    "阪神": {"full": "阪神タイガース", "mini": "神", "league": "セ", "id": "tigers"},
    "中日": {"full": "中日ドラゴンズ", "mini": "中", "league": "セ", "id": "dragons"},
    "広島": {"full": "広島東洋カープ", "mini": "広", "league": "セ", "id": "carp"},
    "ヤクルト": {"full": "東京ヤクルトスワローズ", "mini": "ヤ", "league": "セ", "id": "swallows"},
    "DeNA": {"full": "横浜DeNAベイスターズ", "mini": "De", "league": "セ", "id": "baystars"},
}

# 逆引き表を構築（正式名・略称 → 正規名）
_ALIAS = {}
for norm, info in TEAMS.items():
    _ALIAS[norm] = norm
    _ALIAS[info["full"]] = norm
    _ALIAS[info["mini"]] = norm


def normalize_team(name: str | None) -> str | None:
    """チーム名（正式・略称・1文字）を正規名に変換。不明ならそのまま返す"""
    if not name:
        return None
    name = name.strip()
    return _ALIAS.get(name, name)


def team_info(name: str | None) -> dict:
    """正規名からチーム情報（full/mini/league/id）を返す"""
    norm = normalize_team(name)
    return TEAMS.get(norm, {"full": name, "mini": name, "league": None, "id": None})


def team_mini(name: str | None) -> str | None:
    """1文字略称を返す"""
    return team_info(name).get("mini")


def normalize_player_id(pid) -> str | None:
    """
    選手IDを正規化する。取得元（スポナビ）のIDを文字列キーとして扱う。
    数値でも文字列でも、桁の欠けない文字列に統一する。
    """
    if pid is None:
        return None
    s = str(pid).strip()
    return s if s and s.isdigit() else (s or None)


def player_key(player_id, name: str | None = None) -> str | None:
    """
    選手を一意に識別するキー。選手IDを最優先。
    IDが無い場合のみ名前ベースのフォールバック（正確性は落ちる）。
    """
    pid = normalize_player_id(player_id)
    if pid:
        return f"p{pid}"
    if name:
        return "name:" + name.replace(" ", "").replace("　", "")
    return None


def clean_name(name: str | None) -> str | None:
    """選手名の表記を正規化（全角スペースを半角に統一など）"""
    if not name:
        return None
    return " ".join(name.replace("　", " ").split())
