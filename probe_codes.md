# コード解読プローブ

- 試合ID: 2021039164
- 収集打席数: 40

## 1. ランナー状況コード（base）

| コード | 出現数 | よく出る結果 |
|---|---|---|
| `b000` | 19 | 遊ゴロ(5), 四球(2), 中安打(2) |
| `b100` | 8 | 右本塁打 ＋2点(1), 左安打(1), 空振り三振(1) |
| `b110` | 6 | 空振り三振(2), 一ファウルフライ(1), 三エラー(1) |
| `b011` | 3 | 遊フライ(2), 空振り三振(1) |
| `b010` | 2 | 投犠打(1), 中2塁打(1) |
| `b001` | 1 | 左安打 ＋1点(1) |
| `b111` | 1 | 右2塁打 ＋2点(1) |

## 2. 打球方向コード（dakyu）

| コード | 出現数 | よく出る結果 |
|---|---|---|
| `dakyu45` | 6 | 遊ゴロ(5), 遊併殺打(1) |
| `dakyu8` | 6 | 中安打(3), 中2塁打(3) |
| `dakyu31` | 5 | 空振り三振(5) |
| `dakyu9` | 3 | 右安打(2), 右2塁打 ＋2点(1) |
| `-` | 3 | 四球(2), 一ファウルフライ(1) |
| `dakyu55` | 3 | 左フライ(3) |
| `dakyu30` | 2 | 右本塁打 ＋2点(1), 右本塁打 ＋1点(1) |
| `dakyu7` | 2 | 左安打(1), 左安打 ＋1点(1) |
| `dakyu44` | 2 | 三ゴロ(2) |
| `dakyu54` | 2 | 遊フライ(2) |
| `dakyu57` | 1 | 右フライ(1) |
| `dakyu56` | 1 | 中フライ(1) |
| `dakyu4` | 1 | 二エラー(1) |
| `dakyu40` | 1 | 投犠打(1) |
| `dakyu5` | 1 | 三エラー(1) |
| `dakyu43` | 1 | 二併殺打(1) |

## 3. ボール種別クラス（ballCircle--X）

| クラス | 出現数 | 対応する投球結果 |
|---|---|---|
| `ball1` | 232 | ファウル(23), 見逃し(22), 空振り(8), 空三振(5) |
| `ball2` | 200 | ボール(48), 四球(2) |
| `ball3` | 68 | 遊ゴロ(5), 左飛(3), 三ゴロ(2), 遊飛(2), 右飛(1) |
| `ball4` | 60 | 中安(3), 中２(3), 右安(2), 右本(2), 左安(2) |
| `ball5` | 4 | 投犠打(1) |

## 4. 打席ごとの生データ

| index | 打者 | 結果 | base | dakyu | ボールクラス列 |
|---|---|---|---|---|---|
| 0110100 | 水野 達稀 | 右安打 | `b000` | `dakyu9` | ball2,ball2,ball4,ball2,ball2,ball4,ball2,ball2,ball4,ball2,ball2,ball4 |
| 0110200 | 清宮 幸太郎 | 右本塁打 ＋2点 | `b100` | `dakyu30` | ball4,ball4,ball4,ball4 |
| 0110300 | レイエス | 右フライ | `b000` | `dakyu57` | ball2,ball1,ball1,ball3,ball2,ball1,ball1,ball3,ball2,ball1,ball1,ball3 |
| 0110400 | 万波 中正 | 遊ゴロ | `b000` | `dakyu45` | ball1,ball3,ball1,ball3,ball1,ball3,ball1,ball3 |
| 0110500 | 郡司 裕也 | 四球 | `b000` | `-` | ball2,ball2,ball1,ball2,ball2,ball2,ball2,ball1,ball2,ball2,ball2,ball2 |
| 0110600 | 野村 佑希 | 左安打 | `b100` | `dakyu7` | ball4,ball4,ball4,ball4 |
| 0110700 | 吉田 賢吾 | 空振り三振 | `b110` | `dakyu31` | ball2,ball1,ball1,ball1,ball2,ball1,ball1,ball1,ball2,ball1,ball1,ball1 |
| 0120100 | 西川 龍馬 | 中フライ | `b000` | `dakyu56` | ball3,ball3,ball3,ball3 |
| 0120200 | 山中 稜真 | 右本塁打 ＋1点 | `b000` | `dakyu30` | ball1,ball4,ball1,ball4,ball1,ball4,ball1,ball4 |
| 0120300 | 紅林 弘太郎 | 遊ゴロ | `b000` | `dakyu45` | ball1,ball3,ball1,ball3,ball1,ball3,ball1,ball3 |
| 0120400 | 中川 圭太 | 遊ゴロ | `b000` | `dakyu45` | ball2,ball2,ball1,ball2,ball3,ball2,ball2,ball1,ball2,ball3,ball2,ball2 |
| 0210100 | 上川畑 大悟 | 空振り三振 | `b000` | `dakyu31` | ball2,ball2,ball1,ball2,ball1,ball1,ball2,ball2,ball1,ball2,ball1,ball1 |
| 0210200 | 清水 優心 | 中安打 | `b000` | `dakyu8` | ball4,ball4,ball4,ball4 |
| 0210300 | 水野 達稀 | 空振り三振 | `b100` | `dakyu31` | ball1,ball1,ball2,ball1,ball1,ball1,ball1,ball2,ball1,ball1,ball1,ball1 |
| 0210400 | 清宮 幸太郎 | 二エラー | `b100` | `dakyu4` | ball2,ball1,ball2,ball2,ball4,ball2,ball1,ball2,ball2,ball4,ball2,ball1 |
| 0210500 | レイエス | 空振り三振 | `b110` | `dakyu31` | ball1,ball1,ball1,ball1,ball1,ball1,ball1,ball1,ball1,ball1,ball1,ball1 |
| 0220100 | 森 友哉 | 遊ゴロ | `b000` | `dakyu45` | ball3,ball3,ball3,ball3 |
| 0220200 | 宗 佑磨 | 左フライ | `b000` | `dakyu55` | ball2,ball2,ball1,ball3,ball2,ball2,ball1,ball3,ball2,ball2,ball1,ball3 |
| 0220300 | 平沼 翔太 | 三ゴロ | `b000` | `dakyu44` | ball1,ball2,ball3,ball1,ball2,ball3,ball1,ball2,ball3,ball1,ball2,ball3 |
| 0310100 | 万波 中正 | 中2塁打 | `b000` | `dakyu8` | ball1,ball2,ball4,ball1,ball2,ball4,ball1,ball2,ball4,ball1,ball2,ball4 |
| 0310200 | 郡司 裕也 | 投犠打 | `b010` | `dakyu40` | ball2,ball5,ball2,ball5,ball2,ball5,ball2,ball5 |
| 0310300 | 野村 佑希 | 左安打 ＋1点 | `b001` | `dakyu7` | ball2,ball2,ball1,ball4,ball2,ball2,ball1,ball4,ball2,ball2,ball1,ball4 |
| 0310400 | 吉田 賢吾 | 中安打 | `b100` | `dakyu8` | ball2,ball1,ball1,ball1,ball1,ball2,ball4,ball2,ball1,ball1,ball1,ball1 |
| 0310500 | 上川畑 大悟 | 一ファウルフライ | `b110` | `-` | ball3,ball3,ball3,ball3 |
| 0310600 | 清水 優心 | 三エラー | `b110` | `dakyu5` | ball2,ball1,ball1,ball4,ball2,ball1,ball1,ball4,ball2,ball1,ball1,ball4 |
| 0310700 | 水野 達稀 | 右2塁打 ＋2点 | `b111` | `dakyu9` | ball1,ball2,ball1,ball1,ball4,ball1,ball2,ball1,ball1,ball4,ball1,ball2 |
| 0310800 | 清宮 幸太郎 | 空振り三振 | `b011` | `dakyu31` | ball1,ball2,ball2,ball1,ball1,ball1,ball1,ball2,ball2,ball1,ball1,ball1 |
| 0320100 | 福永 奨 | 中安打 | `b000` | `dakyu8` | ball1,ball2,ball1,ball2,ball4,ball1,ball2,ball1,ball2,ball4,ball1,ball2 |
| 0320200 | 渡部 遼人 | 右安打 | `b100` | `dakyu9` | ball1,ball2,ball1,ball2,ball1,ball1,ball1,ball4,ball1,ball2,ball1,ball2 |
| 0320300 | 西川 龍馬 | 左フライ | `b110` | `dakyu55` | ball2,ball2,ball1,ball1,ball1,ball3,ball2,ball2,ball1,ball1,ball1,ball3 |
| 0320400 | 山中 稜真 | 二併殺打 | `b110` | `dakyu43` | ball1,ball1,ball3,ball1,ball1,ball3,ball1,ball1,ball3,ball1,ball1,ball3 |
| 0410100 | レイエス | 三ゴロ | `b000` | `dakyu44` | ball1,ball2,ball2,ball1,ball2,ball3,ball1,ball2,ball2,ball1,ball2,ball3 |
| 0410200 | 万波 中正 | 中2塁打 | `b000` | `dakyu8` | ball1,ball2,ball2,ball4,ball1,ball2,ball2,ball4,ball1,ball2,ball2,ball4 |
| 0410300 | 郡司 裕也 | 中2塁打 | `b010` | `dakyu8` | ball2,ball4,ball2,ball4,ball2,ball4,ball2,ball4 |
| 0410400 | 野村 佑希 | 遊フライ | `b011` | `dakyu54` | ball3,ball3,ball3,ball3 |
| 0410500 | 吉田 賢吾 | 遊フライ | `b011` | `dakyu54` | ball1,ball2,ball3,ball1,ball2,ball3,ball1,ball2,ball3,ball1,ball2,ball3 |
| 0420100 | 紅林 弘太郎 | 四球 | `b000` | `-` | ball2,ball2,ball2,ball1,ball2,ball2,ball2,ball2,ball1,ball2,ball2,ball2 |
| 0420200 | 中川 圭太 | 左フライ | `b100` | `dakyu55` | ball1,ball3,ball1,ball3,ball1,ball3,ball1,ball3 |
| 0420300 | 森 友哉 | 遊併殺打 | `b100` | `dakyu45` | ball1,ball3,ball1,ball3,ball1,ball3,ball1,ball3 |
| 0510100 | 上川畑 大悟 | 遊ゴロ | `b000` | `dakyu45` | ball2,ball2,ball1,ball3,ball2,ball2,ball1,ball3,ball2,ball2,ball1,ball3 |