# OCI 権限設計: テナンシ管理者作業と最小権限デプロイアカウントの切り分け

前提（オーナー判断 2026-11-24）: lab コンパートメントは実験専用。Terraform の操作は最小権限の
デプロイ用アカウントで行い、`plan` 提示 → オーナー承認 → `apply`（CLAUDE.md §5）を守る。

## 1. 誰が何をするか

| 作業 | 必要な権限レベル | 実施者 | 頻度 |
|---|---|---|---|
| lab コンパートメント作成 | テナンシ管理者 | 管理者（コンソール） | 1 回 |
| デプロイ用ユーザ/グループ作成、API キー登録 | テナンシ管理者（IAM） | 管理者 | 1 回 |
| §2 のポリシー作成 | テナンシ管理者（root に置くため） | 管理者 | 1 回 |
| **guardrails の Budget** | `usage-budgets` は **テナンシ単位**の権限 | **管理者プロファイル**で guardrails を apply（推奨） | 1 回 |
| guardrails の Resource Scheduler | lab コンパートメント内 | デプロイ用 or 管理者 | 1 回 |
| Resource Scheduler 用 IAM ポリシー | ポリシー作成権限 | **管理者が手動作成**（`create_scheduler_policy = false`） | 1 回 |
| CHR カスタムイメージ取り込み | lab コンパートメント内（images, objects） | デプロイ用 | 実験ごと |
| 実験スタック（VCN / VM） | lab コンパートメント内 | デプロイ用 | 実験ごと |
| Quota | テナンシ管理者 | 後回し（オーナー判断） | — |

**テナンシ管理者が必要なもの = Budget、IAM（ユーザ/グループ/ポリシー）、コンパートメント作成、Quota。**
それ以外はすべて lab コンパートメント内に閉じた権限で動かせる。

### なぜデプロイ用アカウントに `manage policies` を与えないか

ポリシー作成権限があると、そのアカウントは自分で権限を広げられる（`any-user` への許可も書ける）。
最小権限の意味がなくなるため、Resource Scheduler 用のポリシーは管理者が 1 回だけ手で作る。

### なぜ Budget を管理者プロファイルで apply するか

Budget は root コンパートメントのリソースで、`manage usage-budgets in tenancy` が必要。
これをデプロイ用に与えると、テナンシ全体の Budget を削除・変更できてしまう。
guardrails は 1 回作れば終わりなので、管理者プロファイル（`oci_profile = "ADMIN"` 等）で plan/apply する方が安全。

## 2. 管理者が作成するポリシー（root コンパートメントに配置）

例中の `soar-net-lab` は実際の lab コンパートメント名（このテナンシでは `lab`）に読み替える。

```
# --- デプロイ用グループ: lab コンパートメント内のみ ---
Allow group soar-lab-deployers to manage virtual-network-family in compartment soar-net-lab
Allow group soar-lab-deployers to manage instance-family        in compartment soar-net-lab
Allow group soar-lab-deployers to manage volume-family          in compartment soar-net-lab
Allow group soar-lab-deployers to manage instance-images        in compartment soar-net-lab
# カスタムイメージの UEFI 設定（chr-image スタック）。instance-images には含まれない
# （2026-11-24 の apply で 404-NotAuthorizedOrNotFound を確認）
Allow group soar-lab-deployers to manage compute-image-capability-schema in compartment soar-net-lab
Allow group soar-lab-deployers to manage object-family          in compartment soar-net-lab
Allow group soar-lab-deployers to manage resource-schedule-family in compartment soar-net-lab
Allow group soar-lab-deployers to read all-resources            in compartment soar-net-lab
# Availability domain 一覧、Ubuntu 公式イメージの参照
Allow group soar-lab-deployers to inspect compartments in tenancy
Allow group soar-lab-deployers to read app-catalog-listing in tenancy

# --- Resource Scheduler 自身（夜間停止の実行主体） ---
Allow any-user to manage instance-family in compartment soar-net-lab where all {request.principal.type='resourceschedule'}
```

注: 最後の文は guardrails の自動作成版（スケジュール OCID で限定）より少し広く、
「lab コンパートメント内の任意のスケジュール」が対象。lab は実験専用なので許容範囲とする。
より厳密にしたい場合は、guardrails を apply してスケジュール OCID が確定した後に
`request.principal.id='<schedule_ocid>'` を条件に追加する。

ポリシーの動詞（verb）とリソースタイプ（resource-type）の名前は apply 前に OCI ドキュメントで確認する（要実機確認）。

## 3. Terraform 側の設定

```hcl
# infra/guardrails/terraform.tfvars
oci_profile             = "ADMIN"      # Budget のため管理者プロファイル
create_scheduler_policy = false        # ポリシーは §2 で管理者が作成済み

# infra/01-e2e-latency/terraform/terraform.tfvars
oci_profile = "SOAR_DEPLOY"            # 最小権限プロファイル
```

`~/.oci/config` にはプロファイルを分けて登録し、秘密鍵は `~/.oci/` 配下（リポジトリ外）に置く。
