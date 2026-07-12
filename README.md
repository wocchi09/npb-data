# npb-data ⚾📊

スポナビ（Yahoo!スポーツ）の一球速報を毎日自動収集し、
**球種・球速・コース・結果**を貯めて、スマホ・PCから見られるリポジトリ。

## 取れるデータ

各打席の1球ごとに以下を記録します（Seleniumなし・requestsのみで動作）:

- 球種（ストレート / フォーク / スライダー など）
- 球速（km/h）
- 結果（見逃し / 空振り / ファウル / 安打 など）
- コース（配球図の座標を「高め・外」などの5×5ゾーンに変換）
- 打席結果（本塁打・凡退など）

## 仕組み

```
毎晩 JST23時台の自動実行（cron） ─┐
スマホ/PCの手動実行ボタン ─────┼─▶ Actions ─▶ scraper ─▶ data/ にJSON蓄積
                                 │              (全試合・全打席を巡回)
                                 ▼
                    GitHub Pages のビューア（index.html）
                    https://あなたのID.github.io/npb-data/
```

## ファイル構成

| ファイル | 役割 |
|---|---|
| `.github/workflows/daily.yml` | 毎日実行＋手動実行（日付・試合ID指定可） |
| `scraper/main.py` | 収集本体（全試合・全打席を巡回） |
| `scraper/parser.py` | 一球速報HTMLのパーサー（球種・球速・コース抽出） |
| `index.html` | Pages公開用ビューア |
| `requirements.txt` | 依存ライブラリ |
| `data/` | 収集データ（自動生成） |

### データの保存形式

```
data/2026/07/12/2021038864.json   … 試合ごとの一球速報フル
data/2026/07/12/_summary.json     … その日の試合一覧
data/index.json                   … 収集済みファイル一覧（ビューア用）
```

試合JSONの中身（抜粋）:

```json
{
  "game_id": "2021038864",
  "atbat_count": 74,
  "pitch_count": 280,
  "atbats": [
    {
      "inning": 9, "top_bottom": "表",
      "result_summary": "右本塁打 ＋1点",
      "pitches": [
        {"no":1,"type":"ストレート","speed_kmh":149,"result":"ファウル",
         "course":{"top_px":32.76,"left_px":36.0,"grid_row":2,"grid_col":2,"label":"真ん中・真ん中"}}
      ]
    }
  ]
}
```

---

## セットアップ手順（PC・最初の1回だけ）

### STEP 1: リポジトリ作成
1. github.com →「New repository」
2. 名前 `npb-data`、**Public** を選択（無料Pagesに必要）
3. READMEなどのチェックは全部OFF →「Create repository」

### STEP 2: プッシュ
```bash
cd npb-data
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/あなたのID/npb-data.git
git push -u origin main
```
> 事前に `git config --global user.name "名前"` と
> `git config --global user.email "メール"` を設定しておくとコミットが通ります。

### STEP 3: 動作確認
1. Actionsタブ → 有効化ボタンを押す
2. 「Daily NPB Data Collection」→「Run workflow」
3. 過去の試合日を入れて実行（例: 2026-07-12）
4. ✅になったら `data/日付/` にJSONができる

### STEP 4: Pages公開
1. Settings → Pages
2. Source「Deploy from a branch」／ Branch「main」「/(root)」→ Save
3. 数分後 `https://あなたのID.github.io/npb-data/` が開ける

---

## ふだんの使い方

| やりたいこと | 方法 |
|---|---|
| 今日のデータを見る | ビューアURLを開く（毎晩自動更新） |
| 過去日を収集 | Actions →「Run workflow」→ 日付入力 |
| 特定試合だけ収集 | Run workflow の「game」に試合IDを入力 |
| ローカルでテスト | `python scraper/main.py --date 2026-07-12` |

## マナー・法的メモ

- リクエスト間隔を1.5秒空け、1日1回の夜間アクセスに留めています
- 個人利用・分析目的の範囲での運用を想定
- 生データの再配布は避け、公開するなら「自分で集計・加工した結果」に留めるのが安全

## 次の開発ステップ

- [ ] コース座標のゾーン変換精度を実測で微調整
- [ ] pandasで配球分析（球種配分・コース別成績のヒートマップ）
- [ ] 打者/投手ごとの成績集計ページ
"# npb-data" 
