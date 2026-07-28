# 共通走塁イベント仕様

## 目的

W-Impact、簡易WAR、日刊・週間・月間表彰、分析用CSVで同じ走塁記録を使う。
判定処理は `scraper/lib/baserunning.py` を唯一の実装元とする。

## 採用イベントと得点価値

| event_type | 判定元 | 得点価値 |
|---|---|---:|
| `stolen_base` | 公式ボックススコアの選手別盗塁数 | +0.20 |
| `caught_stealing` | `result_detail` の「盗塁失敗（選手名）」 | -0.40 |
| `baserunning_out` | `result_detail` に暴走、飛び出し、オーバーラン、挟まれる等の根拠語と選手名がある場合 | -0.40 |

通常のタッチアウトだけでは走塁ミスと判定しない。選手を所属チーム内で一意に
特定できない記録と、リプレー検証で判定が覆った記録も採用しない。

## 保存先

- 1イベント1行: `data/{season}/dataset/runner_events.csv`
- 選手シーズン集計: `players/stats.json` の
  `caught_stealing`、`baserunning_outs`、`baserunning_runs`
- 1試合選手集計: `dataset/batting_lines.csv` の同名列
- シーズンCSV: `dataset/season_batting.csv` の同名列

`baserunning_runs` は次式で再計算できる。

```text
盗塁 × 0.20 - 盗塁失敗 × 0.40 - 高確度の走塁死 × 0.40
```

## 利用先

- W-Impact: 走塁成分を80打席相当でリーグ平均へ縮小補正
- 簡易WAR: `R_baser` としてそのまま加算
- 日刊表彰: 盗塁失敗と走塁死を各 -2点
- 週間・月間表彰: 盗塁失敗と走塁死を各 -1点

