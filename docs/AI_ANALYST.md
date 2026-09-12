# AI ANALYST / AI打席分析

## 概要と導入状況

打席リプレイで選択した1打席に対し「🤖 この打席をAI分析」を押すと、球種・球速・配球図上のコース・投球結果を日本語で解説する。回答は「この打席の要約」「配球の流れ」「ポイント」「データ上わからないこと」の専用カードに表示する。実データとAI解説を分離し、投手・捕手・打者の心理や意図は推測しない。

コードとキー不要の統合テストを実装済み。2026-09-12にVercelプロジェクト `npb-ai-analyst` をデプロイし、公開API URLを `https://npb-ai-analyst.vercel.app/api/analyze-atbat` に設定した。本番利用にはVercelのProduction環境変数 `OPENAI_API_KEY` の設定と再デプロイが必要。本番OpenAIへの課金を伴う疎通・生成内容の確認は、キー設定後に実施する。

画面には必ず「AIによるデータ解説」「実データをもとに生成していますが、内容は参考情報です」を表示し、既存の軌道再現の注意書きも維持する。AI回答を試合の保存JSONに書き戻さない。

## 既存実装の調査

基点は `a8264b318`。フロントの各ラボ・トップページ、収集処理、GitHub Actions、docs、既存テストとデータ一覧を確認した。2026-09-06の実データは733試合、54,617打席、209,911球、最長19球。

| 対象 | 調査結果 / 変更方針 |
| --- | --- |
| `pitch_replay_model.js` | `normalizePlateAppearance` と `getPlateAppearanceSummary` をそのまま再利用。コース変換・B/S再計算を重複実装しない |
| `pitch_replay.js` | 読み込み開始・打席選択の2か所で `pitchreplay:selectionchange` を通知 |
| `pitch_replay.html / css` | 投球一覧の下にカードを追加。既存ネイビー・ブルー・白の配色、フォーカス表示を継承 |
| `index.html` | 試合詳細の打席リンクとトップの直接導線を確認。変更なし |
| `analyst_lab.js` | 配球タブの投手・試合を引き継ぐ導線を確認。集計・表示ロジック変更なし |
| `data/YYYY/MM/DD/GAME_ID.json` | `atbats[].pitches[]` が実データ。選択打席だけを既存summaryから抽出。データファイル変更なし |
| `docs/PITCH_REPLAY.md` | コースは図の変換値、カウントは再計算という制約を引き継ぐ |

## アーキテクチャ

```text
GitHub Pages: pitch_replay.html
  → window.getPlateAppearanceSummary()
  → ai_analyst_data.js（許可フィールド抽出）
  → ai_analyst_client.js（HTTPS POST / タイムアウト / キャッシュ）
  → Vercel: backend/api/analyze-atbat.js（CORS / body検証）
  → backend/lib/service.js（制限 / キャッシュ / 同時リクエスト統合）
  → backend/lib/openai.js + prompt.js（Responses API / System Prompt）
  → JSON検証 → ai_analyst_view.js（textContent）
```

ブラウザはOpenAIへ直接接続しない。公開設定 `ai_analyst_config.js` に入るのはVercel API URLのみ。Node標準のfetchを使用し、新しい本番用npm依存・フロントのビルド処理は不要。

`backend/public/ai-contract.js` はフロントとバックエンドで共有する公開スキーマ・検証コード。GitHub Pagesはこのファイルを相対URLで読み込む。VercelのRoot Directoryは `backend` とし、同ディレクトリだけでデプロイ可能。

## 変更ファイル一覧

| ファイル | 役割 |
| --- | --- |
| `ai_analyst.js` | ボタン・状態・選択切り替えの制御 |
| `ai_analyst_data.js` | 既存summaryから必要なデータを抽出 |
| `ai_analyst_client.js` | HTTP通信・タイムアウト・ブラウザキャッシュ |
| `ai_analyst_view.js` | JSONから安全なDOMを生成 |
| `ai_analyst_config.js` | 公開API URLの設定 |
| `backend/api/analyze-atbat.js` | Vercel Functionsの入口、CORS・入力検証 |
| `backend/lib/service.js` | レート制限・結果キャッシュ |
| `backend/lib/openai.js` | OpenAIへのリクエスト・回答検証 |
| `backend/lib/prompt.js` | System Promptと球速差の単純計算 |
| `backend/public/ai-contract.js` | フロントとAPIの共有スキーマ |
| `backend/dev-server.js` | ローカルAPIサーバー |
| `backend/package.json` | Nodeバージョンと起動コマンド |
| `backend/vercel.json` | Functionの実行時間設定 |
| `backend/.env.example` | 値を含まない設定例 |
| `pitch_replay.html` | 分析カードとスクリプト読み込み |
| `pitch_replay.js` | 選択変更のイベント通知2か所 |
| `pitch_replay.css` | 分析カード・スマホ・loadingのスタイル |
| `tests/ai_analyst.test.cjs` | 単体/API検証 |
| `tests/ai_analyst_browser.test.cjs` | 実ブラウザ統合検証 |
| `.gitignore` | 秘密設定とVercelローカル情報の除外 |
| `docs/AI_ANALYST.md` | 本文書 |
| `docs/PITCH_REPLAY.md` | AI接続の説明更新 |
| `README.md` | 機能と導入文書への案内 |

## 必要環境変数

| 変数 | 用途 |
| --- | --- |
| `OPENAI_API_KEY` | 必須。Vercel環境変数またはローカルの `backend/.env.local` に保存。値をGitに追加しない |
| `OPENAI_MODEL` | 任意。空・未設定なら `backend/lib/openai.js` の `DEFAULT_MODEL` を使用。既定は `gpt-4.1-mini-2025-04-14`。Responses APIとStructured Outputsに対応するモデルを指定 |
| `ALLOW_LOCALHOST` | 開発時だけ `true`。localhost / 127.0.0.1のHTTP Originを許可。本番Vercelでは `VERCEL_ENV=production` により無効 |
| `VERCEL / VERCEL_ENV` | Vercelが設定。手動設定しない。信頼できるプロキシのIP取得と本番判定に使用 |

`.env`, `.env.*`, `.vercel/` はGit対象外。コミットできる例外は空の `.env.example` のみ。APIキーをHTML、JavaScript、URL、ブラウザストレージ、ログに入れない。

## ローカル起動

Node.js 22.9以上（本番は22.x）、Python 3を使用。

1. `backend/.env.example` を `backend/.env.local` にコピーし、エディタでキーを設定する。ファイルはGit管理対象外。
2. APIを起動する。

```sh
cd backend
npm run dev
```

3. 別ターミナルでリポジトリルートの静的サイトを起動する。

```sh
python -m http.server 8000 --bind 127.0.0.1
```

4. `http://127.0.0.1:8000/pitch_replay.html` を開く。localhostの場合は `http://127.0.0.1:3000/api/analyze-atbat` が自動選択される。

既存リプレイの再生・試合読み込みはキーなしでも利用できる。AIボタンを押してキー未設定ならAPIは503を返す。自動テストはOpenAIだけをモックするためキー・課金は不要。

## Vercelへのデプロイ

1. GitHubへ変更ブランチをpushし、Vercelで `wocchi09/npb-data` をImportする。
2. Framework Presetは **Other**、Root Directoryは **backend**。Build Commandの上書きは不要、Output Directoryは `public`。Node.jsは22.x。
3. Vercelの対象環境に `OPENAI_API_KEY` を設定する。必要なら `OPENAI_MODEL` を設定。本番に `ALLOW_LOCALHOST` は設定しない。
4. Deployする。`backend/vercel.json` によるFunction最大実行時間は30秒。
5. 安定した本番ドメインのURL（例：`https://YOUR-PROJECT.vercel.app/api/analyze-atbat`）を取得する。
6. `ai_analyst_config.js` の本番側のURLを、そのURLへ変更してコミットする（現在は上記プロジェクトのURLを設定済み）。キーを入れてはいけない。設定スクリプトのバージョン文字列も更新し、古いブラウザキャッシュを避ける。
7. GitHub Pagesの公開元mainへ変更を反映する。Vercel側のProductionも同じ変更を含むことを確認する。
8. `https://wocchi09.github.io/npb-data/pitch_replay.html` から実際に1打席を分析し、NetworkでVercelへの1打席POST・JSON応答・キー非露出を確認する。

Vercel Deployment Protectionが有効なPreview URLでは、GitHub Pagesからの呼び出しが認証画面になる場合がある。本番用API URLを使い、公開APIに必要なProtection設定を確認する。ブラウザへProtection bypass tokenを埋め込まない。直接URLを開くGETやOriginなしのcurlは仕様上405/403になり、疎通成功の判定には使えない。

CLIを利用する場合は `cd backend` から `vercel` でプロジェクトを関連付け、環境変数設定後に `vercel --prod` で公開できる。CLIのログイン・環境変数入力は利用者のVercelアカウントで行う。

公開運用では `/api/analyze-atbat` に対するVercel Firewallのレート制限等、インスタンスをまたぐ対策も設定する。以下のMVP内の制限だけで総支出を保証するものではない。

## API仕様

`POST /api/analyze-atbat`、`Content-Type: application/json`。`OPTIONS` は許可Originだけ204。認証情報をフロントから送信しない。

本文は `backend/public/ai-contract.js::requestSchema` に厳密に一致する必要がある。余分なキーはネスト内も拒否。主な形は次の通り（構造説明用、実データではない）。

```json
{
  "schemaVersion": 1,
  "game_id": "2021038622",
  "atbat_index": "0110200",
  "pitcher": { "name": "投手名", "hand": "左投" },
  "batter": { "name": "打者名", "hand": "左打" },
  "inning": 1,
  "topBottom": "表",
  "result": "三ゴロ",
  "pitches": [{
    "no": 1,
    "display_order": 1,
    "type": "ストレート",
    "speed_kmh": 142,
    "result": "ボール",
    "course": { "top_px": null, "left_px": null, "grid_row": null, "grid_col": null },
    "derived": { "location": null, "countBefore": { "balls": 0, "strikes": 0 }, "countAfter": { "balls": 1, "strikes": 0 } }
  }]
}
```

`atbat_index` は保存index、欠損時は `array-<試合内配列位置>`。`no` は保存球順、`display_order` は既存モデルの表示順。欠番・不明値を新しい保存値として埋めない。`null` を欠損として保持する。

成功200:

```json
{
  "schemaVersion": 1,
  "cached": false,
  "analysis": {
    "summary": "この打席の要約",
    "pitch_flow": [{ "pitch": 1, "description": "この投球の説明" }],
    "points": ["観測できるポイント"],
    "limitations": ["このデータだけでは意図を判断できません。"]
  }
}
```

`pitch_flow[].pitch` は `display_order`。全投球と同数・同順であることをサーバーとフロントで検証する。画面は`textContent`とDOM生成のみを用いる。

エラー形式は `{ "error": { "code": "INVALID_REQUEST", "message": "AI分析を取得できませんでした。少し時間を置いて再度お試しください。" } }`。画面は未知のサーバーエラー本文をそのまま表示せず、固定メッセージに置換する。

| HTTP | 主な原因 |
| --- | --- |
| 400 | 不正JSON、スキーマ不一致、選択なし、投球なし |
| 403 / 405 / 415 | Origin不許可 / メソッド不許可 / Content-Type不許可 |
| 413 | 24KB超過 |
| 429 | 連打・回数制限、OpenAIのレート制限。`Retry-After: 60` |
| 502 | 通信失敗、OpenAIエラー、不正回答・拒否・出力未完了 |
| 503 | APIキー未設定 |
| 504 | OpenAI応答タイムアウト |
| 500 | その他の内部エラー |

## AIへ送信する情報と境界

- **保存値**：投手・打者の名前と左右、回・表裏、打席結果、球種、球速、保存球順、投球結果、限定したcourse座標/グリッド。
- **既存コードによる導出値**：`derived.location` と `countBefore/countAfter`。コースは配球図の近似的な変換であり、カウントは完全な投球列からの再計算。公式実測値とは表現しない。
- **サーバーでの単純計算**：保存球順が連続し、両方の球速がある隣接球について、球速差を小数1桁で算出する。AIに独自の数値計算をさせない。
- **API内だけで使用する情報**：game_idとatbat_indexはキャッシュ識別用。OpenAI入力から除外する。
- **送信しない情報**：HTML、全試合JSON、シーズン集計、自由な質問文、球場や他打席、選手IDや背番号、軌道・リリース・飛行時間の表示モデル、出典不明の固定カウント、保存course.label、過去のAI回答。

使用してよい説明は球種・球速・順序・球速差・配球図上の高低/内外角・保存された打者の反応・打席結果。球種変更や繰り返しを言葉で説明する。

推測してはいけない情報は投手・捕手・打者の心理や狙い、効果や原因、打者の体勢や目線、実測されていない軌道/回転、欠損値、将来予測、独自に計算した成績値。打席結果と終球の投球結果が異なる場合も勝手に補正しない。

NG：「捕手はフォークを意識させるためにストレートを投げさせた」

OK：「ストレートの後に、配球図上では低めのフォークが使われています」

System Promptはサーバーの `backend/lib/prompt.js` に固定する。ユーザー本文中の指示は資料として扱い実行しないよう指示する。回答のJSON検証は形式の保証であり、文章の事実性を完全保証する仕組みではない。運用開始時に元の投球一覧と照合し、モデル変更時にも確認する。

## セキュリティとコスト

| 対策 | 実装 |
| --- | --- |
| キー保護 | バックエンド環境変数のみ。秘密や生のエラー本文をログに出さない |
| CORS | `https://wocchi09.github.io` 完全一致。ワイルドカード・Originなし・nullは禁止 |
| 入力 | 1打席、1〜30球、24,576 bytes、文字列長/数値範囲/型/未知キーを検証 |
| 出力 | 最大3,500トークン、Structured Outputs、受信サイズ制限、型/文字数/球順再検証 |
| タイムアウト | OpenAI25秒、ブラウザ28秒、Vercel Function30秒。自動再試行なし |
| 二重送信 | ボタンdisabled、フロント実行ロック、サーバーの同一入力処理統合 |
| 連打 | フロント5秒間隔、サーバー同IP5秒間隔・6リクエスト/分 |
| サーバー上限 | 各インスタンス60回/時、同時OpenAI呼び出し4件。失敗した呼び出しも回数に含む |
| キャッシュ | フロント64件、サーバー256件、TTL1時間。game_id + atbat_indexに加えて本文・モデル・プロンプト版を反映しデータ訂正後は別結果 |
| XSS | AI文字列はtextContent。HTMLは文字として表示 |
| 状態競合 | 打席・試合・日付変更時にキャンセルし、選択世代番号で旧回答の描画を禁止 |

フロントキャッシュは同一ページのメモリ内。リロードで消える。サーバーキャッシュ・レート制限も稼働インスタンス内のメモリで、コールドスタートや再デプロイ時に消える。複数インスタンス間では共有されず、1日全体の支出上限ではない。

CORSはブラウザ向けの制御で認証ではない。Originを偽装できるスクリプト等の直接アクセスはCORSだけでは防げず、同じGitHub Pagesオリジン内の別パスも区別できない。公開運用で厳密な全体上限が必要なら、Vercel Firewall等の分散レート制限、永続ストアによる原子的な回数管理/共有キャッシュを追加する。ブラウザに共通秘密鍵を配る方法では解決しない。MVPでは新しいDB基盤は追加していない。

APIは送信された打席データの型とサイズを検証するが、GitHubの原本との照合認証までは行わない。ゲームIDだけで結果をキャッシュせず、内容もキーに含めることで異なるデータによるキャッシュ混同を防ぐ。

## テスト

```sh
node --test tests/pitch_replay_model.test.cjs tests/ai_analyst.test.cjs
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p 'test_*.py'
npm install --no-save --package-lock=false playwright
npx playwright install chromium
node --test tests/pitch_replay_browser.test.cjs tests/ai_analyst_browser.test.cjs
```

インストール済みChromeを使う場合は環境変数 `REPLAY_BROWSER_CHANNEL=chrome`。`AI_QA_DIR` に出力先を指定すると追加テストのPC/390pxスクリーンショットを保存する。

確認結果（2026-09-12、最新mainとの統合後）：既存Python202件、既存モデル15件、既存ブラウザ11件、AI単体14件、AIブラウザ5件の計247件が成功。AIブラウザテストは実ブラウザからHTTPサーバーの本番ハンドラー・OpenAIリクエスト生成処理まで通し、OpenAIの応答だけをモックする。Vercel本番APIはGitHub PagesのOriginを持つOPTIONSに204と限定したCORSヘッダーを返すことを確認した。

未選択・投球なし、成功、通信/OpenAI失敗、レート制限、不正JSON・回答、タイムアウト、二重送信、キャッシュ/期限/本文変更、打席切り替え競合、HTMLの非実行、キーボード/フォーカス/aria-live、PC/390pxのはみ出しを検証。全実データの非空打席も送信スキーマを検証。目視画像はモック回答であり、実際のモデル出力例ではない。

## 既知の制約・今回の範囲外

- 本番キー・公開API URLが未設定の場合、AI分析は利用できない。
- 語句の事実性・意図の不推測はSystem Promptで制約するが、生成AIの誤記を完全に排除するものではない。
- 30球超・非常に長い保存文字列などは安全側で拒否する。出力上限で全投球を返せない場合も部分回答は表示しない。
- ブラウザでキャンセルしても、既に始まったOpenAI処理・料金を必ず取り消せるわけではない。
- 欠番や不明な打者の左右、取得されていない値は復元しない。
- 390px幅のChromeで検証済み。実機iPhone Safariでの検証は別途必要。
- 全体検索チャット、シーズン全データ送信、RAG、ベクトルDB、アカウント、課金機能、予測、意図の推測は含まない。

将来の選手・試合分析等は、リクエスト整形・API処理・プロンプト・表示の各モジュールを分離したまま、別のスキーマとエンドポイントとして拡張する。

## 参照した公式仕様

- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [GPT-4.1 mini（対応機能・固定モデル版）](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
- [Vercel Node.js runtime](https://vercel.com/docs/functions/runtimes/node-js)
- [Vercel Functionの最大実行時間](https://vercel.com/docs/functions/configuring-functions/duration)
- [Vercel request headers / IPの扱い](https://vercel.com/docs/headers/request-headers)
