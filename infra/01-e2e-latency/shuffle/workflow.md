# Shuffle ワークフロー仕様: `e2e-block-src`

Wazuh アラート（rule 100510）を受けて、攻撃元 IP を MikroTik CHR の `soar-blocklist` に追加する最小ワークフロー。
計測用のタイムスタンプをアクション結果に埋め込み、Shuffle 内部のメタデータ（秒解像度）に頼らず
ns 解像度で T1_soar / T2 を取る。

## 構成

```
Wazuh integratord ──POST──▶ [Webhook: wazuh_in] ──▶ [stamp_and_block (Shuffle Tools 1.2.0 / execute_python)] ──PUT──▶ CHR REST
   http://127.0.0.1:5001/api/v1/hooks/webhook_<id>                                                       https://10.10.0.10/rest/ip/firewall/address-list
```

- Webhook は soar 上の backend を **127.0.0.1:5001** で直接叩く（同一ホスト、TLS なし、外部に出ない）
- アクションを 1 つにまとめているのは、アクション間のスケジューリング遅延を「計測対象」と「計測手段」で混同しないため

## 比較条件 C3: 2 アクション版 `e2e-block-src-2step`

`create_workflow.py --variant two-step` で作成する。`stamp`（execute_python、`stamp_only.py`）→ `chr_put`（http 1.4.0 / PUT）。
T2 は Shuffle の結果の `completed_at`（ms）で代替し、標準 HTTP アプリは CA を指定できないため CHR への TLS 検証は無効。
集計時は `collect_shuffle.py --t2-action chr_put` を使う。結果は `experiments/01-e2e-latency/results/C3.md`。

## ファイル

| ファイル | 内容 |
|---|---|
| `stamp_and_block.py` | execute_python のコード。T1_soar / T2_req / T2_resp を記録して JSON を 1 行出力 |
| `create_workflow.py` | ワークフローと Webhook を API で作成（同名があれば作り直す）。soar 上で実行。`--variant two-step` で C3 用 |
| `stamp_only.py` | C3 の 1 つ目のアクション（T1_soar の記録と srcip・run_id の抽出のみ） |

## 作成手順（soar 上）

```bash
# 環境変数: SHUFFLE_API_KEY, MIKROTIK_URL, MIKROTIK_USER, MIKROTIK_PASSWORD, MIKROTIK_CA_FILE, BLOCK_TIMEOUT
python3 create_workflow.py      # -> {"workflow_id": ..., "webhook_path": "/api/v1/hooks/webhook_<id>"}
```

出力された `webhook_path` を `../wazuh/ossec-integration.xml` の `hook_url` に設定する。

## Workflow variables（Shuffle の DB にだけ保存。リポジトリには入れない）

| 変数 | 例 | 備考 |
|---|---|---|
| `mikrotik_url` | `https://10.10.0.10` | |
| `mikrotik_user` | `soar-api` | 最小権限ユーザ |
| `mikrotik_password` | (secret) | |
| `mikrotik_ca_pem` | soar-lab-ca の PEM | TLS はこの CA で検証（ホスト名照合のみ無効: 証明書の CN が IP のため） |
| `block_timeout` | `60s` | 自動失効で試験間をリセット |

## 実機での確認（2026-11-24）

| 確認 | 結果 |
|---|---|
| Webhook に疑似アラートを直接 POST | 実行 FINISHED（約 2.2 秒）、CHR が 201、`timeout=60s`・`comment=run=<id>` で登録 |
| Wazuh 経由の単発試験（run 223b3f42） | T1_soar / T2 を取得し `collect_shuffle.py` で trial.json にマージ |

## 注意

- コード中で `$` を変数参照以外に使わない（Shuffle が実行前に置換するため）
- Wazuh の shuffle integration はアラートを `all_fields` に包んで送る。コードは包まれていない形にも対応
