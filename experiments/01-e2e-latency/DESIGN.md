# 01-e2e-latency 計測設計

## 問い

異常イベントの発生から、プログラマブルネットワーク上で実パケットが遮断されるまで
何秒かかり、そのうちどの区間が支配的か。

## タイムスタンプ定義

| 記号 | イベント | 取得元ホスト | 取得方法 | 解像度 |
|---|---|---|---|---|
| **T0** | 異常イベント発生（attacker が sshd に `soar-probe-<run_id>` で接続開始） | attacker | `run_trial.py` が ssh 起動直前に `time.time_ns()` | µs |
| T0' (参考) | sshd がログを書いた時刻 | target | Wazuh アラートの `predecoder.timestamp` / `full_log` | 秒 |
| **T1_detect** | Wazuh がアラート生成 | soar | `alerts.json` の `timestamp` | ms |
| **T1_soar** | Shuffle がワークフローのユーザーコードを実行開始 | soar | Python アクション内 `time.time_ns()` | µs |
| T2_req (参考) | MikroTik REST API へリクエスト送出 | soar | 同上 | µs |
| **T2** | MikroTik REST API 応答受信 (= `t2_resp`) | soar | 同上 | µs |
| **T3** | 実パケット遮断完了 | attacker | UDP プローブの「最初の未応答パケットの送信時刻」 | プローブ間隔（既定 10 ms） |

ユーザー指定の T1（Wazuh 検知 / Shuffle 起動）は内訳を見るため T1_detect と T1_soar に分割する。

### 区間

| 区間 | 式 | 意味 |
|---|---|---|
| D_detect | T1_detect − T0 | ログ収集 + 解析（agent logcollector → manager analysisd） |
| D_dispatch | T1_soar − T1_detect | integratord → webhook → Shuffle キュー/ワーカー起動 |
| D_api | T2 − T1_soar | Shuffle → CHR REST API 往復 |
| D_enforce | T3 − T2 | API 応答後、データプレーンで drop が効くまで |
| **D_e2e** | T3 − T0 | **E2E（主指標）** |

**T0 と T3 は同一ホスト（attacker）の時計で取るため、主指標 D_e2e はホスト間時刻同期誤差の影響を受けない。**
区間分解のみ chrony 同期精度に依存する（下記）。

## T3 の決め方

attacker → target に UDP プローブを `interval` ごとに送り、target の echo 応答を記録する。

- `last_ok` = 応答があった最後の seq
- **T3 = seq `last_ok + 1` の送信時刻**（以後のプローブが全て無応答であること＝「終端連続ロス」を条件とする）
- 誤差: 真の遮断時刻は `(send[last_ok], send[last_ok+1]]` にある → ±interval
- 一時的なロスは終端連続ロスに含まれないため誤判定しない
- 遮断は src アドレスで判定されるので、プローブも ssh トリガも同じ attacker IP から出す

raw テーブル drop（conntrack 前）を既定とし、既存フローでも即時に遮断されることを前提にする。
filter/forward drop は比較条件（established 許可ルールの位置で挙動が変わる）。

## 時刻同期

- 全 Linux VM: chrony で OCI NTP `169.254.169.254` に同期（OCI の Ubuntu 24.04 イメージは systemd-timesyncd なので chrony を追加導入し、`/etc/chrony/sources.d/oci.sources` に `server 169.254.169.254 iburst minpoll 4 maxpoll 6`。2026-11-24 実測で RMS offset 10〜150 µs）
- CHR: `/system ntp client` で同じサーバ
- 各バッチの前後で `scripts/clock_snapshot.sh` を各ホストで実行し、`chronyc tracking` の
  System time offset を `raw/<batch>/clock-*.txt` に保存
- 区間分解の許容誤差目標: |offset| < 1 ms（OCI 内なら通常 µs オーダー）

## 単発試験の結果（2026-11-24, run 223b3f42, 条件 C1-smoke, dual-nic）

| 区間 | ms |
|---|---|
| D_detect（T1_detect − T0） | 1098.1 |
| D_dispatch（T1_soar − T1_detect） | **3498.1** |
| D_api（T2 − T1_soar） | 22.5 |
| D_enforce（T3 − T2） | 104.3 |
| **D_e2e（T3 − T0）** | **4723.0**（T3 の誤差 ±10 ms） |

5 つのタイムスタンプがすべて取れ、Wazuh・Shuffle 両方の値が trial.json にマージされることを確認した（n = 1 なので数値は参考値）。
初見の所見（要検証）: D_dispatch が支配的。Webhook を直接叩いたときの Shuffle の実行は約 2.2 秒だったので、
残りは integratord の受け渡しか。D_enforce の 104 ms は API 応答からデータプレーン反映までの遅れとして別途確認する。

## 試験手順（1 回分）

1. 前提: target で `udp_echo_server.py` 稼働、attacker IP が blocklist に無い
2. `run_trial.py` がプローブ開始 → baseline 期間（既定 3 s）で応答を確認（応答が無ければ中止）
3. T0 記録 → `ssh soar-probe-<run_id>@target`（BatchMode、パスワード不送信）
4. 終端連続ロスが `block_detect_s`（既定 2 s）続いたら遮断とみなし、さらに `post_block_s` 観測して停止
5. `timeout_s`（既定 120 s）以内に遮断されなければ `blocked=false` で記録
6. Address List の `timeout`（既定 60 s）で自動解除 → 応答復帰を待って次 trial

trial 後に soar 側で `collect_wazuh.py` / `collect_shuffle.py` を実行し、
`raw/<run_id>/trial.json` に T1/T2 をマージ → `summarize.py` で集計。

## 試験条件

| ID | 変える要素 | 水準 | 結果 |
|---|---|---|---|
| C1 | ベースライン | raw drop、Shuffle 1 アクション構成 | `results/C1.md` |
| C2 | 遮断方式 | filter/forward drop（確立済み通信の許可ルールなし） | `results/C2.md` |
| C3 | Shuffle 構成 | 2 アクション（execute_python → 標準 HTTP アプリ） | `results/C3.md` |
| C4 | 比較対象 | Wazuh Active Response で直接 CHR（SOAR を経由しない） | `results/C4-jitter.md`（`C4.md` は位相同期で偏り、参考のみ） |
| C5 | 負荷 | rule 100510 に一致しない背景アラート 20 件/秒 | `results/C5.md` |

各条件 n = 30。C1 以外は試験前に 0〜4 s のランダム待ちを入れた（位相同期の対策、`results/C4-jitter.md` 参照）。

## 出力ファイル

```
raw/<run_id>/probes.csv        seq,send_ns,recv_ns,rtt_us
raw/<run_id>/trial.json        T0/T3 + 収集した T1/T2 + メタデータ
raw/<batch>/clock-<host>.txt   chrony tracking
results/trials.csv             trial ごとの区間（summarize.py）
results/stats.csv              条件ごとの n/mean/p50/p90/p95/max/stdev
```

生ログは private IP のみを含む。コミット前に `grep -E` でグローバル IP が無いことを確認する。

## 既知の限界

- T3 はデータプレーン上の「CHR に到達した attacker → target 方向パケット」の遮断で定義しており、
  CHR の FastTrack 等が有効だと挙動が変わりうる（bootstrap では FastTrack を設定していない）
- Wazuh アラートの `timestamp` は ms 解像度
- E2.1.Micro は CPU バーストのため、attacker/target 側の処理遅延にばらつきが出る可能性
- `chr_mode = single-nic`（CHR が E2.1.Micro）の場合、CHR 自身の処理遅延にもバーストの影響が出うる。条件ラベル（`--condition`）に CHR モードを含め、dual-nic の結果と混ぜて集計しない
