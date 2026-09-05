# 打者イメージ（2026-09-06）

- 使用方法: 組み込み `image_gen`。CLI/APIフォールバックは使用していない。
- 採用画像: 最初の生成結果。背景透過のアルファチャンネルを保持し、512×768 WebPへ縮小・圧縮した。元画像の構図・色・人物は変更していない。
- 配信用ファイル: `replay_batter_v2.webp`（49,346 bytes）。
- 用途: 全身の打者表示と打者情報欄。特定の実在選手の写真ではなく、右打ち・左打ちで反転する共通イメージ。UIに「共通イメージ・AI生成」と表示する。
- 確認: 実ブラウザで透明な背景、輪郭、左右反転、画像の読み込み、表示切り替え、PC/スマホ表示を確認。

## 採用画像の最終プロンプト

```text
Use case: stylized-concept. Asset type: transparent cutout for a Japanese baseball pitch-replay website. Create ONE anatomically natural adult male baseball batter in a right-handed batting ready stance, full body including the entire bat and both cleats. Side/three-quarter view, his face and gaze looking toward the RIGHT edge at the pitcher. Athletic realistic adult proportions, knees slightly flexed, feet shoulder-width apart, both gloved hands together correctly gripping one wooden bat raised behind the rear shoulder; relaxed credible professional baseball stance. Premium editorial sports illustration with subtle painterly shading and clean realistic silhouette, recognizable as a human athlete, not a cartoon mascot, not chibi, not a geometric stick figure. Plain dark navy batting helmet, plain white baseball jersey and trousers, navy undershirt and belt, dark cleats, understated blue accents. Facial features are subtle in helmet shadow, no named player identity. No team logos, no text, no numbers, no watermarks. Portrait composition, figure centered with 8 percent margin, all equipment and body completely inside the image. Truly transparent background with alpha; no ground, no baseball diamond, no backdrop, no decorative effects, no fake checkerboard. Crisp readable edges suitable for showing at approximately 120-200 pixels tall. Exactly one person, two arms, two legs, two hands and one bat.
```
