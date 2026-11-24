# infra/01-e2e-latency

OSS SOAR (Wazuh + Shuffle) × MikroTik CHR on OCI — E2E 遮断レイテンシ実証用インフラ。

## トポロジ

```
                         Internet
                            │  (admin_cidr のみ SSH/UI 許可)
                       ┌────┴────┐
                       │   IGW   │
                       └────┬────┘
 VCN 10.10.0.0/16           │
 ┌──────────────────────────┼─────────────────────────────────────────┐
 │ public 10.10.0.0/24      │                                         │
 │   ┌───────────────┐  ┌───┴───────────┐                             │
 │   │ soar .20      │  │ CHR ether1 .10│ ◀── REST API (www-ssl)      │
 │   │ Wazuh mgr     │──┤  (WAN)        │     from soar only          │
 │   │ + Shuffle     │  │               │                             │
 │   └───────────────┘  │  raw drop     │                             │
 │                      │  src∈soar-    │                             │
 │ attacker 10.10.1.0/24│  blocklist    │                             │
 │   ┌───────────────┐  │               │                             │
 │   │ attacker .20  │─▶│ CHR ether2 .10│                             │
 │   │ prober/trigger│  │  (LAN)        │                             │
 │   └───────────────┘  └───┬───────────┘                             │
 │                          │                                         │
 │ protected 10.10.2.0/24 (private, no public IP)                     │
 │   ┌───────────────┐      │                                         │
 │   │ target .20    │◀─────┘  default route → CHR LAN                │
 │   │ sshd, Wazuh   │                                                │
 │   │ agent, UDP echo│                                               │
 │   └───────────────┘                                                │
 └────────────────────────────────────────────────────────────────────┘
```

### 経路設計（ターゲット VM の通信を必ず CHR 経由にする）

| サブネット | ルート | ターゲット | 目的 |
|---|---|---|---|
| public | 0.0.0.0/0 | IGW | 管理アクセス |
| public | 10.10.2.0/24 | CHR WAN private IP | soar → target（Wazuh agent 通信の戻り）を CHR 経由に |
| attacker | 0.0.0.0/0 | IGW | 管理アクセス |
| attacker | 10.10.2.0/24 | CHR WAN private IP | **攻撃トラフィックを CHR に強制** |
| protected | 0.0.0.0/0 | CHR LAN private IP | NAT による外向き通信 |
| protected | 10.10.0.0/24, 10.10.1.0/24 | CHR LAN private IP | VCN 暗黙ローカルルートより長いプレフィクスで上書き → 戻りも CHR 経由（対称経路） |

ポイント:
- OCI の **intra-VCN routing**（VCN CIDR 内宛先を Private IP に向けるルート）を利用。
- CHR の両 VNIC で `skip_source_dest_check = true`（転送パケットが落とされないため）。
- ルートテーブルは CHR の Private IP OCID を参照するため、サブネット作成 → CHR 作成 → `oci_core_route_table_attachment` で差し替え、という順序で依存循環を回避。
- 攻撃元/被害側ともに **private IP のみ** で実験が完結するため、生ログに実グローバル IP が残らない。

### リージョン

このテナンシのホームリージョンは **`us-phoenix-1`**。Always Free の A1.Flex / E2.1.Micro はホームリージョンでしか無料にならず、IAM・Budget の書き込みもホームリージョンで行うため、全スタックの `region` は `us-phoenix-1` にする。CHR カスタムイメージも Phoenix の Object Storage / Compute に取り込む。

### Always Free 枠の割当（デフォルト値）

| ノード | Shape | OCPU / RAM | 備考 |
|---|---|---|---|
| soar | A1.Flex (arm64) | 3 / 18 GB | Wazuh all-in-one + Shuffle（OpenSearch が 2 つ動くため最も重い） |
| chr | A1.Flex (arm64) | 1 / 6 GB | VNIC 2 枚が必要なため Micro 不可 |
| attacker | E2.1.Micro (x86) | 1/8 / 1 GB | |
| target | E2.1.Micro (x86) | 1/8 / 1 GB | Wazuh agent + sshd + UDP echo |

A1 合計 4 OCPU / 24 GB、ブートボリューム 50 GB × 4 = 200 GB でちょうど Always Free 上限。

### CHR の構成モード（`chr_mode`）

| | `dual-nic`（既定） | `single-nic`（フォールバック） |
|---|---|---|
| CHR | A1.Flex arm64、VNIC 2 枚（WAN/LAN） | E2.1.Micro x86_64、VNIC 1 枚（router-on-a-stick） |
| CHR の位置 | public 10.10.0.10 / protected 10.10.2.10 | **transit 10.10.3.0/24** の 10.10.3.10 |
| attacker | E2.1.Micro | **A1.Flex 1 OCPU / 6 GB**（Micro 2 台枠を CHR に譲る） |
| RouterOS 設定 | `routeros/bootstrap.rsc` | `routeros/bootstrap-single-nic.rsc` |
| CHR イメージ | arm64 | x86_64 |

single-nic で transit サブネットを分ける理由: CHR が public サブネットにいると、
CHR が転送したパケットにも public の「protected 宛は CHR へ」ルールが適用され、CHR に戻ってきてループする。
transit サブネットは VCN 既定ルート（0/0 → IGW のみ）なので、CHR から出たパケットは VCN ローカル経路で宛先に届く。

single-nic 固有の注意:
- RouterOS で `send-redirects=no` にする（ICMP redirect で端末が CHR を迂回するのを防ぐ）
- Micro は CPU バースト型のため、**CHR の転送・API 処理遅延が計測結果に混入しうる**。結果には必ず `chr_mode` を記録する
- Shuffle の接続先（`MIKROTIK_URL`、ワークフロー変数）を `https://10.10.3.10` に変更
- モード切替はインスタンスの作り直しになる。**切替は `terraform destroy` → `apply` で行う**（in-place 更新は想定しない）

```hcl
# terraform.tfvars
chr_mode       = "single-nic"
chr_image_ocid = "ocid1.image...<x86_64 CHR>"
```

## 前提: CHR カスタムイメージ

OCI Marketplace に CHR は無いため、カスタムイメージのインポートが必要。

1. MikroTik 公式から CHR の raw/qcow2 イメージを取得（dual-nic: **arm64** / single-nic: **x86_64**）
2. Object Storage にアップロード → Compute > Custom Images > Import（QCOW2, UEFI, Paravirtualized）
3. 作成された Image OCID を `terraform.tfvars` の `chr_image_ocid` に設定

上記は `chr-image/` スタックで自動化済み（[chr-image/README.md](chr-image/README.md)）。

> ⚠ A1 (Ampere) 上での CHR arm64 の起動可否・セカンダリ VNIC 認識は**要実機検証**（下記「未検証事項」）。

## デプロイ手順

```bash
cd infra/01-e2e-latency/terraform
cp terraform.tfvars.example terraform.tfvars   # 値を埋める（git-ignored）
terraform init
terraform plan -out tfplan
terraform apply tfplan
```

その後:
1. CHR を一度 `/system reboot`（ether2 認識のため）→ soar 経由で SSH し、`routeros/bootstrap.rsc` を適用
   （プレースホルダを置換した一時ファイルを scp → `/import` → CHR 上と手元の一時ファイルを削除）
2. target から `curl -I https://example.com` で CHR NAT 経由の外向き通信を確認
3. soar に Wazuh all-in-one → Shuffle の順でインストール（ポート競合の解消は `shuffle/COLOCATE_WITH_WAZUH.md`）
4. target に Wazuh agent をインストールし soar に登録
5. `wazuh/local_rules.xml` と `wazuh/ossec-integration.xml` を manager に反映
6. `shuffle/workflow.md` に従いワークフロー作成
7. `scripts/mikrotik_addrlist.py add 10.10.1.20 --timeout 30s` で手動ブロック → attacker から target に到達不能になることを確認

## ファイル

| パス | 内容 |
|---|---|
| `terraform/` | VCN / サブネット / ルート / 4 インスタンス（`chr_mode` で 2 構成） |
| `chr-image/` | CHR イメージのダウンロード・検証・QCOW2 変換と OCI 取り込み（別 state） |
| `terraform/tests/` | mock provider によるオフラインテスト（`terraform test`） |
| `routeros/bootstrap.rsc` | CHR 初期設定 dual-nic（NAT、raw drop、REST API、最小権限ユーザ） |
| `routeros/bootstrap-single-nic.rsc` | CHR 初期設定 single-nic |
| `shuffle/COLOCATE_WITH_WAZUH.md` | Wazuh と同居させる際のポート競合・メモリ配分手順 |
| `../guardrails/` | Budget / 夜間停止（別 state） |
| `scripts/mikrotik_addrlist.py` | REST API で Address List を add/remove/check/list（T2 計測兼用） |
| `wazuh/` | 実験トリガ用ルール、Shuffle integration 設定 |
| `shuffle/workflow.md` | ワークフロー仕様 |
| `AUTO_STOP.md` | 自動停止・コストガードレール設計メモ |
| `.env.example` | スクリプト用環境変数テンプレート |

## 実機で確認済み（2026-11-24, us-phoenix-1）

- CHR 7.25.1 arm64 が A1.Flex（1 OCPU / 6 GB）で UEFI ブートする
- セカンダリ VNIC（ether2）は起動後のアタッチなので、**初回は `/system reboot` が必要**（再起動後に認識）
- RouterOS 7.25.1 にユーザポリシー `rest-api` が存在する
- REST API の DELETE は `.id` の `*` をパーセントエンコードすると 400 になる（`mikrotik_addrlist.py` で対応済み）
- target → CHR（10.10.2.10）→ インターネットの NAT 経路が動作し、外部からは CHR のグローバル IP に見える
- **CHR 無償ライセンスは 1 Mbit/s 制限**（target の外向き実測 約 1 Mbit/s）。target への apt は遅いが、
  soar は IGW 直結なので影響なし。計測用プローブ（10 ms 間隔の小パケット）は制限より十分小さい
- RouterOS 7.25.1 には `reverse-proxy` サービス（443/tcp、接続元制限なし）が既定で有効
  → `bootstrap.rsc` で無効化（2026-11-24 に実機でも無効化済み。REST は www-ssl で引き続き動作）
- CHR の管理経路は soar 経由（`ssh -J`）のみ。admin_cidr から CHR のグローバル IP への 22/443 は
  TCP 接続自体は成立するが、RouterOS のサービス単位の接続元制限で即切断される


- A1.Flex 1 OCPU で VNIC 2 枚がアタッチ可能か（不可なら `chr_mode = "single-nic"` へ切替）
- single-nic: x86 CHR が E2.1.Micro（1 GB RAM）で安定稼働するか、ICMP redirect 抑止が効いているか
- E2.1.Micro の在庫がある AD（`ad_index`）
