# 自動停止・コストガードレール設計メモ

目的: 「実験が終わったのに放置」で課金・枠消費・攻撃面が残ることを防ぐ。
Always Free 構成でも、アカウントが PAYG（従量課金）に昇格している場合や
Shape を誤って変更した場合に課金が発生しうるため、多層で防ぐ。

## 層構造

| 層 | 仕組み | 役割 | 状態 |
|---|---|---|---|
| L1 | `terraform destroy`（実験の最後に必ず実行） | 主手段。構成ごと消す | 手順化済み |
| L2 | OCI **Resource Scheduler** で lab compartment 内のインスタンスを毎晩停止 | 消し忘れ時の安全網（停止のみ） | **適用済み**（`infra/guardrails/`、2026-11-24） |
| L3 | Compartment **Quota** で A1 4 OCPU / E2.1.Micro 2 台以外を作成不可に | Shape 誤設定による課金の防止 | 後回し（テナンシ管理者権限が必要） |
| L4 | **Budget** アラート（月 100 等）をメール通知 | 最終検知 | **適用済み**（`infra/guardrails/`、2026-11-24） |
| L4' | Terraform の `check` ブロックで Always Free 超過（A1 > 4 OCPU / Micro > 2 台）を plan 時に警告 | 設定ミスの早期発見 | **実装済み** |
| L5 | `expires-at` タグ + 期限切れチェックスクリプト（Linux / Control Host から手動/定期実行） | 期限切れの可視化 | タグのみ実装 |

### L1: 実験ごとの destroy

```bash
terraform destroy   # 実行前にユーザー確認（CLAUDE.md: 破壊的変更は承認必須）
```

CHR カスタムイメージと Object Storage のイメージファイルは Terraform 管理外なので残る
（再デプロイを速くするため意図的）。不要になったら手動削除。

### L2: Resource Scheduler（夜間停止）

- 実装: `infra/guardrails/`（実験スタックとは**別 state**。実験を destroy しても残る）
- 対象: lab compartment 内のインスタンス全部
  （Resource Scheduler のフィルタは defined tag のみ対応で、freeform tag `auto-stop=true` は使えないため）
- スケジュール: 毎日 15:00 UTC（= 24:00 JST）に STOP（`stop_cron_utc` で変更可）
- 起動は手動（実験時のみ）
- 停止権限はスケジュール自身を principal とする IAM ポリシーで付与（同ディレクトリで作成）
- 注意: 停止中もブートボリュームは残る（Always Free 200 GB 枠内）。A1 は長期アイドルで
  回収対象になりうるため、停止が長引く場合は L1 で消す方が確実。

### L3: Compartment Quota（例・要文法確認）

```
zero compute-core quotas in compartment soar-net-lab
set compute-core quota standard-a1-core-count to 4 in compartment soar-net-lab
set compute-memory quota standard-a1-memory-count to 24 in compartment soar-net-lab
set compute-core quota standard-e2-micro-core-count to 2 in compartment soar-net-lab
```

※ quota 名はリージョン/時期で異なる可能性があるため、適用前に
`oci limits definition list` で正確な名前を確認する。テナンシ管理者権限が必要。

### L4: Budget

- 実装: `infra/guardrails/`
- 対象: lab compartment（Budget 自体は root compartment に作成）
- 金額: 既定 100（請求通貨）
- アラート: 実績 1% / 実績 100% / 予測 100% でメール通知（宛先は `terraform.tfvars` のみに記載）

### L5: expires-at

`terraform.tfvars` の `expires_at` が全リソースに freeform tag として付く。
将来、`oci search resource structured-search` で期限切れリソースを一覧する
スクリプトを `infra/` に追加予定。

## Linux / Control Host の cron を主手段にしない理由

Linux / Control Host（ノート PC 上の Linux VM など）はスリープやシャットダウンで止まるため、cron が確実に動く保証がない。
クラウド側（L2/L4）を安全網とし、ローカルは「手動 destroy の手順化」に留める。
