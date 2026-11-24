# Shuffle を Wazuh と同一 VM（soar, A1 3 OCPU / 18 GB）に同居させる手順

オーナー判断（2026-11-23）: Always Free 枠内で 1 台同居。ポート競合は設定で解消する。

## 1. 何がぶつかるか

| 用途 | Wazuh all-in-one | Shuffle（docker compose 既定） | 対処 |
|---|---|---|---|
| OpenSearch REST | **9200**（wazuh-indexer） | **9200**（`shuffle-opensearch` をホストに公開） | **Shuffle 側のホスト公開をやめる** |
| OpenSearch transport | 9300（indexer、ローカル） | 9300（コンテナ内のみ） | 対処不要（Shuffle は公開しない） |
| Web UI | 443（dashboard） | 3001 / 3443（frontend） | 競合なし |
| API | 55000（wazuh API）, 1514/1515（agent） | 5001（backend） | 競合なし |
| メモリ | indexer JVM ヒープ | shuffle-opensearch JVM ヒープ | ヒープ上限を明示的に分ける（§4） |

Shuffle の backend はコンテナ間ネットワーク経由で `shuffle-opensearch:9200` に接続するため、
**ホストの 9200 に公開する必要はない**。ポート番号を変えるより「公開しない」方が衝突も攻撃面も小さい。

## 2. 作業順序

1. **Wazuh を先に**入れる（all-in-one インストーラ）。indexer が 9200 を確保した状態にする
2. `ss -ltnp | grep -E ':(9200|9300|443|3001|3443|5001)\b'` で現状を記録
3. Shuffle を clone し、起動**前**に §3 の変更を加える
4. `docker compose up -d`
5. §5 の確認

## 3. Shuffle の docker-compose.yml 変更

`opensearch` サービスの `ports:` を削除（またはループバック + 別ポートに限定）する。

```diff
   opensearch:
     image: opensearchproject/opensearch:<version>
     container_name: shuffle-opensearch
     ...
-    ports:
-      - 9200:9200
+    # Not published on the host: wazuh-indexer owns :9200.
+    # Backend reaches it over the compose network as shuffle-opensearch:9200.
+    # For debugging only, publish on loopback instead:
+    # ports:
+    #   - 127.0.0.1:9201:9200
```

`.env` の接続先がコンテナ名を指していることを確認（変数名は Shuffle のバージョンで異なるため clone したリポジトリの `.env` を正とする）:

```
SHUFFLE_OPENSEARCH_URL=https://shuffle-opensearch:9200
```

> ⚠ ここを `https://localhost:9200` 等にすると **Wazuh indexer に書き込みに行く**。必ずコンテナ名を使う。

## 4. メモリ配分（18 GB）

| コンポーネント | 目安 | 設定箇所 |
|---|---|---|
| wazuh-indexer | ヒープ 4 GB | `/etc/wazuh-indexer/jvm.options`（`-Xms4g -Xmx4g`） |
| shuffle-opensearch | ヒープ 2 GB | compose の `OPENSEARCH_JAVA_OPTS=-Xms2g -Xmx2g` |
| wazuh-manager / dashboard | 〜3 GB | — |
| Shuffle backend / frontend / orborus / workers | 〜3 GB | — |
| OS / page cache 余裕 | 残り | — |

共通のカーネル設定（両 OpenSearch に必要）:

```bash
echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-opensearch.conf
sudo sysctl --system
```

## 5. 確認

```bash
# 9200 を掴んでいるのが wazuh-indexer だけであること
sudo ss -ltnp | grep ':9200'
# Wazuh indexer が応答（認証情報はインストーラ出力を参照）
curl -sk -u admin:<pw> https://127.0.0.1:9200/_cluster/health | jq .status
# Shuffle 側 OpenSearch はコンテナ内から応答
docker exec shuffle-backend sh -c 'wget -qO- --no-check-certificate https://shuffle-opensearch:9200 || true'
# UI
curl -skI https://127.0.0.1:3443 | head -1
```

計測への影響を見るため、試験バッチ前に `free -m` と `docker stats --no-stream` を
`experiments/01-e2e-latency/raw/<batch>/` に保存しておく（C5 の負荷条件の比較基準になる）。

## 6. 要実機確認

- Shuffle の各イメージ（frontend / backend / orborus / worker / app）が **arm64** で提供されているか。
  未提供のものがあれば soar を arm64 のまま使えないため、オーナー判断が必要
- Shuffle の compose で OpenSearch のセキュリティプラグイン設定（http/https）がバージョンでどう変わっているか

## 7. 実機での導入結果（2026-11-24, Wazuh 4.14.10 / Shuffle v2.3.0, Ubuntu 24.04 aarch64）

### 想定と違った点

- **OCI の Ubuntu イメージはホストの iptables で SSH 以外を REJECT する**。agent 用の 1514/1515（VCN 内から）と
  UI 用の 443/3443（admin_cidr から）を INPUT に追加し、`netfilter-persistent save` で永続化した
- **Docker が公開したポートは INPUT を通らない**（PREROUTING で DNAT され FORWARD に行く）。
  `docker-user-rules.sh` で DOCKER-USER に 3443 の接続元制限を入れ、systemd の oneshot ユニット
  `soar-docker-user.service` で Docker 起動後に毎回適用する
- Shuffle v2.3.0 の compose は全イメージ `:latest`。`shuffle-security` は **amd64 専用で 2.3.0 タグも無い**ため無効化した
- compose の変更は upstream のファイルを直接編集せず `docker-compose.override.yml` に集約（このディレクトリにある）
  - 2.3.0 にピン留め / OpenSearch のホスト公開をやめる（`ports: !reset []`）/ ヒープ 2 GB
  - 3001（HTTP）と 5001（backend）は 127.0.0.1 のみ
- `.env` の `SHUFFLE_OPENSEARCH_PASSWORD` は既定値が公開されているため、ランダム値に差し替えた（soar とローカルのみに保存）
- 初回の管理者は UI ではなく API（`POST /api/v1/register`）で作成した（UI を開く前に乗っ取られないように）

### 確認できた状態

| 確認項目 | 結果 |
|---|---|
| ホストの :9200 | wazuh-indexer（127.0.0.1）のみ |
| Wazuh サービス | indexer / manager / dashboard / filebeat すべて active |
| agent | target（ID 001）が Active |
| 検知 | attacker → CHR → target の SSH 不正ユーザ → rule 5710、srcip = 10.10.1.20 |
| Shuffle | frontend 3443 = 200、ログイン OK、ワークフロー作成 OK |
| メモリ | 使用 約 6.4 GB / 18 GB |

### Docker 29 の containerd image store（解決済み）

Shuffle のヘルスチェック用ワークフローの実行が失敗していた。orborus が動的生成アプリイメージを
読み込めない（`unrecognized image format`）。Docker 29 の既定である containerd image store を無効化して解決した。

```bash
# Shuffle を止めてから（データは shuffle-database の bind mount に残る）
cd ~/Shuffle && sudo docker compose down
echo '{"features": {"containerd-snapshotter": false}}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker            # storage-driver が overlay2 になる
sudo systemctl restart soar-docker-user  # DOCKER-USER ルールを再適用
sudo docker compose up -d                # イメージは再取得される
```

結果: `GET /api/v1/health?force=true` → `success: true`、run_status `FINISHED`（初回はコールドスタート込みで約 27 秒）。
初回の実行はイメージ取得と重なってタイムアウトすることがあるので、もう一度実行する。

### DOCKER-USER ルールとインターフェース名

外側の NIC 名は Shape で違う（A1.Flex: `enp0s6`、E2.1.Micro: `ens3`）。最初に `ens3` を決め打ちして
ルールが効かず、attacker から Shuffle（3443）に届いていた。`docker-user-rules.sh` は既定ルートの
インターフェースを自動検出し、再実行しても重複しないようにした。

| 接続元 → soar:3443 | 結果 |
|---|---|
| attacker（10.10.1.20） | 遮断（タイムアウト） |
| admin_cidr | 200 |
| soar 自身（Wazuh → Shuffle の Webhook 経路） | 200 |
