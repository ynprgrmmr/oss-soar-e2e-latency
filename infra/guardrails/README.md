# infra/guardrails — コストガードレール（Budget / 夜間停止）

全実験で共通の安全網。**実験スタック（`infra/01-e2e-latency/terraform` 等）とは別の Terraform root / state** にしてあり、
実験側を `terraform destroy` しても Budget と夜間停止は残る。

設計の背景は [`../01-e2e-latency/AUTO_STOP.md`](../01-e2e-latency/AUTO_STOP.md) を参照。
権限の切り分け（管理者プロファイルで apply する理由など）は [`../IAM.md`](../IAM.md) を参照。

## 作るもの

| リソース | 内容 | 既定 |
|---|---|---|
| `oci_budget_budget.lab` | lab compartment を対象にした月次 Budget（root compartment に作成） | 100（請求通貨） |
| `oci_budget_alert_rule.lab` | ACTUAL 1% / ACTUAL 100% / FORECAST 100% のメール通知 | 3 本 |
| `oci_resource_scheduler_schedule.nightly_stop` | lab compartment 内の全インスタンスを毎日 STOP | `0 15 * * *`（UTC = 24:00 JST） |
| `oci_identity_policy.scheduler` | 上記スケジュールだけにインスタンス停止を許可する IAM ポリシー | lab compartment に作成 |

`enable_budget` / `enable_scheduler` / `create_scheduler_policy` で個別に無効化できる。

## 設計上の注意

- **夜間停止の対象はコンパートメント単位**。Resource Scheduler のフィルタは defined tag にしか対応しておらず、
  実験スタックが付けている freeform tag `auto-stop=true` では絞り込めないため。
  → lab compartment には実験リソース以外を置かない。
- アクションは `STOP_RESOURCE` のみ（終了・削除はしない）。起動は実験時に手動で行う。
- Budget は root compartment に作るため、`manage usage-budgets in tenancy` 相当の権限が必要。
- IAM ポリシーの作成権限が無い場合は `create_scheduler_policy = false` にし、次の文を管理者に作成してもらう:

  ```
  Allow any-user to manage instance-family in compartment id <lab_compartment_ocid> where all {request.principal.type='resourceschedule', request.principal.id='<schedule_ocid>'}
  ```

- Quota（Shape 制限）はテナンシ管理者権限が必要なため後回し（オーナー判断 2026-11-23）。

## 適用状況

2026-11-24 に `ADMIN` プロファイル・`us-phoenix-1` で apply 済み（5 リソース）。
state はローカル（`infra/guardrails/terraform.tfstate`、git 管理外）。

## 使い方

```bash
cd infra/guardrails
cp terraform.tfvars.example terraform.tfvars   # メールアドレス等はここだけに書く（git-ignored）
terraform init
terraform plan -out tfplan                      # apply はオーナー承認後
```

## オフラインテスト

```bash
terraform init -backend=false
terraform test        # mock provider。OCI には一切接続しない
```

## 要実機確認

- ~~`recurrence_type = "CRON"` の書式と UTC 解釈~~ → 確認済み（2026-11-24 apply 後、`time_next_run = 15:00 UTC`）
- `resource_filters` の `COMPARTMENT_ID` フィルタだけで、インスタンスが対象として解決されること
- ポリシー文の `request.principal.type='resourceschedule'` 条件で停止が成功すること（スケジュールの実行履歴で確認）
- ~~請求通貨~~ → JPY を確認済み（`budget_amount = 100` = ¥100）
