# infra/01-e2e-latency/chr-image — MikroTik CHR カスタムイメージ取り込み

CHR の QCOW2 を lab コンパートメントの Object Storage にアップロードし、OCI カスタムイメージとして取り込む。
**実験スタック（`../terraform`）とは別 state**。VM を destroy してもイメージは残る（取り込みは数分〜数十分かかるため）。

## 流れ

```
prepare_image.sh（ローカル）
  download.mikrotik.com から chr-<ver>-<arch>.img.zip
  → ベンダー公開の SHA-256 を照合
  → raw → QCOW2 変換（qemu-img）。出力は ~/.cache/soar-net-lab/chr/（リポジトリ外）
terraform（SOAR_DEPLOY プロファイル）
  → バケット soar-net-lab-images（非公開・Standard）
  → オブジェクト（tfvars の image_sha256 とファイルが一致しないとアップロード拒否）
  → oci_core_image（QCOW2, PARAVIRTUALIZED）
  → arm64: Compute.Firmware = UEFI_64 のケイパビリティスキーマ + A1.Flex 互換
     x86_64: E2.1.Micro 互換
```

| `chr_arch` | 用途 | 互換 Shape |
|---|---|---|
| `arm64`（既定） | `chr_mode = "dual-nic"` | VM.Standard.A1.Flex |
| `x86_64` | `chr_mode = "single-nic"` | VM.Standard.E2.1.Micro |

## 使い方

```bash
cd infra/01-e2e-latency/chr-image
./prepare_image.sh 7.25.1 arm64          # 出力を terraform.tfvars に貼る
stat -c %s <image_path>                  # image_size_bytes
cp terraform.tfvars.example terraform.tfvars  # 残りを記入（git-ignored）
terraform init
terraform plan -out chr-image.tfplan     # → オーナー承認 → terraform apply chr-image.tfplan
terraform output chr_image_ocid          # → ../terraform/terraform.tfvars の chr_image_ocid へ
```

## バージョン選定

公開から 2 週間以上経った 7.x を使う。2026-11-24 時点:
stable 7.25.2 / long-term 7.24.7 は公開から数日のため見送り、**7.25.1（2026-11-03 公開）** を採用。

## 無料枠

- Object Storage: Always Free は合計 20 GB。CHR の QCOW2 は約 25 MiB（仮想サイズ 128 MiB）
- `check "always_free_object_storage"` がイメージサイズ上限（既定 1 GiB）とバケット設定を plan 時に確認
- 取り込み後のオブジェクトは再取り込み用に残している（不要なら別途削除可）

## オフラインテスト

```bash
terraform init -backend=false && terraform test   # mock provider。OCI に接続しない
```

## 要実機確認

- CHR arm64 が A1.Flex で UEFI ブートするか（コンソール接続でブートログを確認）
- 起動時のブートボリューム（50 GB）に対して CHR がディスクを正しく扱うか（仮想サイズ 128 MiB のイメージ）
