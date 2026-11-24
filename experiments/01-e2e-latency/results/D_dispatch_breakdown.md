# D_dispatch の内訳（C1、n = 30）

D_dispatch = T1_soar − T1_detect（中央値 3,813 ms、E2E の 74.6%）を、ログと設定の**読み取りだけ**で分解した。
設定変更やデバッグログの有効化はしていない。

## 使ったデータ

| 時点 | 取得元 | 解像度 |
|---|---|---|
| T1_detect | Wazuh `alerts.json` の `timestamp` | ms |
| integratord の受け取り | `integrations.log` の一時ファイル名 `/tmp/shuffle-<epoch>-…`（integratord が作成した秒） | 1 s |
| Webhook 受信 | shuffle-backend の `docker logs -t`（`HOOKS: webhook callback`） | ns |
| 実行の作成 | 同上（`Execution: should execute onprem`、execution_id 付き） | ns |
| worker が実行を拾う | shuffle-worker の `docker logs -t`（`Inside Decide`） | ns |
| worker がアクションを送る | 同上（`Action: Send`） | ns |
| アプリコンテナへ送信 | 同上（`Should run towards port … for app shuffle-tools_1-2-0`） | ns |
| T1_soar | アクションの Python コード先頭 | ns |

Webhook と実行は execution_argument 内の `soar-probe-<run_id>` で試験と 1 対 1 に対応づけた（30/30）。

## 結果（ms）

| 区間 | 担当 | min | p50 | mean | p95 | max | 平均に占める割合 |
|---|---|---|---|---|---|---|---|
| T1_detect → Webhook 受信 | **Wazuh**（integratord + 連携スクリプト） | 1,353 | 1,874 | 1,859 | 2,339 | 2,434 | **46.2%** |
| Webhook 受信 → 実行の作成 | Shuffle backend | 50 | 66 | 180 | 594 | 1,344 | 4.5% |
| 実行の作成 → worker が拾う | Shuffle（キュー → orborus → worker） | 36 | 664 | 837 | 1,867 | 1,895 | **20.8%** |
| worker の判断 → 送信 | Shuffle worker | 7 | 10 | 11 | 16 | 19 | 0.3% |
| 送信 → アプリコンテナへ | Shuffle worker → shuffle-tools | 15 | 742 | 769 | 1,379 | 1,479 | **19.1%** |
| アプリコンテナ → コード開始 | shuffle-tools（execute_python の準備） | 126 | 339 | 366 | 579 | 624 | 9.1% |
| **D_dispatch 合計** | | 2,867 | 3,813 | 4,022 | 4,962 | 6,358 | 100% |

大まかには **Wazuh 側 約 1.9 s（46%）／Shuffle 側 約 2.2 s（54%）**。

## Wazuh 側（T1_detect → Webhook、約 1.9 s）の仮説と根拠

1. **integratord がアラートを拾うまでの待ち: 0〜約 2 s（中央値 約 0.8 s）**
   - 一時ファイル名の秒と T1_detect の差は min −0.16 / p50 0.78 / max 1.72 s（ファイル名が秒単位なので ±1 s の誤差を含む）
   - 0〜2 s に一様に散らばる形は、integratord が `alerts.json` を一定間隔で読みに行く動きと合う（間隔は約 1〜2 s と推定。ソースでの確認は未実施）
2. **連携スクリプトの起動: 約 0.6 s**
   - `integrations/shuffle` はシェルのラッパーで、Wazuh 同梱の Python で `shuffle.py` を起動する
   - 同梱 Python で `import json, os, sys, requests` だけを実行すると **0.60〜0.68 s**（soar 上で 3 回計測、送信なし）
3. 残り約 0.4 s は、一時ファイルの作成・アラートの整形・HTTP POST の合計と推定

## Shuffle 側（Webhook → T1_soar、約 2.2 s）の仮説と根拠

1. **実行の作成 → worker が拾うまで: 0〜約 1.9 s（中央値 0.66 s）**
   - 36 ms から 1,895 ms まで広く散らばる。orborus がキューを定期的に取りに行く間隔待ち（約 2 s）と推定
   - `.env` の `SHUFFLE_ORBORUS_PULL_TIME` は空（既定値を使用）
2. **worker → アプリコンテナへの送信: 中央値 0.74 s**
   - 15 ms で済む回と 1.4 s かかる回がある。アプリのレプリカ（`SHUFFLE_APP_REPLICAS=3`）の状態待ちなどが候補（未確認）
3. **アプリコンテナでのコード開始まで: 約 0.34 s**（execute_python が Python のサブプロセスを起動する時間と推定）

## 次に確かめること

- integratord の読み取り間隔をソース（4.14.10）で確認する
- C3（Shuffle のアクション 2 つ）で、アクションが増えたときに「送信 → アプリ」の待ちがどう増えるかを見る
- 縮める手段の候補（オーナー判断後に別条件として計測）:
  - 連携スクリプトをシステムの python3 + 標準ライブラリで書き直す（約 0.6 s 減の見込み）
  - orborus の pull 間隔を短くする
- 比較: C4（Wazuh Active Response で直接 CHR）は Shuffle も integratord も通らない
