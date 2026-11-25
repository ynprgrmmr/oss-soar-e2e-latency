# OSS SOAR × programmable network: end-to-end block latency on OCI

How long does it take from an attack event until the attacker's packets **actually stop**?
This repository measures it for an open-source stack — **Wazuh** (detection) → **Shuffle** (SOAR) →
**MikroTik CHR** (REST-controlled router) — on Oracle Cloud Infrastructure Always Free, and publishes the
infrastructure code, measurement scripts, raw data and a bilingual write-up.

## Key results (n = 30 per condition)

| Condition | E2E median | E2E p95 |
|---|---|---|
| C1 baseline: Wazuh → Shuffle (1 action) → CHR, raw drop | 5.30 s | 7.75 s |
| C2 drop in filter/forward instead of raw | 5.06 s | 6.38 s |
| C3 Shuffle with 2 actions | 6.54 s | 8.40 s |
| C4 Wazuh Active Response → CHR directly (no SOAR) | **1.66 s** | 2.42 s |
| C5 baseline + 20 unrelated alerts/s | 4.64 s | 6.00 s |

- About 70% of the baseline is the SOAR hand-off (Wazuh → Shuffle → first action); the router itself adds ~0.12 s
- Each extra Shuffle action adds ~1.1 s of scheduling wait
- Test start times must be randomized: a fixed cadence phase-locked onto the Wazuh agent's 2 s read loop and biased the first C4 run

Read the article: [English](articles/01-e2e-latency/en.md) · [日本語](articles/01-e2e-latency/ja.md)

## Repository layout

| Path | Contents |
|---|---|
| `infra/guardrails/` | Terraform: budget alerts and nightly stop of the lab compartment (separate state) |
| `infra/01-e2e-latency/terraform/` | Terraform: VCN, subnets, routing through CHR, four VMs (`chr_mode` dual-nic / single-nic) |
| `infra/01-e2e-latency/chr-image/` | Download, verify and import the MikroTik CHR image as an OCI custom image |
| `infra/01-e2e-latency/routeros/` | RouterOS bootstrap (NAT, raw/filter drop, REST over TLS, least-privilege API user) |
| `infra/01-e2e-latency/wazuh/`, `shuffle/` | Detection rule, integration, Active Response, Shuffle workflow and colocation notes |
| `infra/IAM.md` | Which steps need tenancy admin vs. a least-privilege deploy account |
| `experiments/01-e2e-latency/` | Measurement design, scripts, raw data (`raw/`), summaries (`results/`) |
| `articles/01-e2e-latency/` | Article (EN/JA), diagrams (Mermaid, draw.io), figures (SVG) |
| `tools/` | Pre-publication scan and public export script |

## Reproducing

Prerequisites: an OCI tenancy (Always Free is enough), Terraform ≥ 1.7, `qemu-img`, Python 3 (scripts use the standard library only).

1. **Guardrails** — `infra/guardrails/`: copy `terraform.tfvars.example`, then `terraform init && terraform plan` and apply
2. **CHR image** — `infra/01-e2e-latency/chr-image/`: `./prepare_image.sh 7.25.1 arm64`, fill `terraform.tfvars`, plan and apply
3. **Lab** — `infra/01-e2e-latency/terraform/`: set `chr_image_ocid`, `admin_cidr` (your IP /32), `ad_index`; plan and apply
4. **Configure** — CHR: reboot once, then import `routeros/bootstrap.rsc` (replace the password placeholders);
   soar: Wazuh all-in-one, then Shuffle per `shuffle/COLOCATE_WITH_WAZUH.md`; target: Wazuh agent;
   Wazuh rule `wazuh/local_rules.xml`; Shuffle workflow via `shuffle/create_workflow.py`
5. **Measure** — on the attacker: `experiments/01-e2e-latency/scripts/run_batch.sh C1 30`; then
   `collect_wazuh.py`, `collect_shuffle.py`, `summarize.py`, `plot_results.py`
6. **Tear down** — `terraform destroy` in the lab stack (the guardrails stay)

Details: [`infra/01-e2e-latency/README.md`](infra/01-e2e-latency/README.md) and
[`experiments/01-e2e-latency/DESIGN.md`](experiments/01-e2e-latency/DESIGN.md).
Most design notes are written in Japanese; the article is available in both languages.

## Safety

- No secrets, keys, real public IPs or tenancy identifiers are committed; use the `*.example` templates.
  `tools/scan-sensitive.sh` checks the working tree and git history before publishing.
- Addresses in the data are private (`10.10.0.0/16`) or documentation ranges (`192.0.2.0/24`, `203.0.113.0/24`).
- The attack used is a single failed SSH login to a lab VM you own. Do not point the scripts at systems you are not authorized to test.

## Optional: turnkey starter kit

Everything in this repository — infrastructure code, measurement scripts, raw data and the article — stays open and
free under the licenses below. You can reproduce the whole study from it.

If you would rather not assemble a production-style deployment from scratch, a separate turnkey deployment kit is
available as an optional paid package:

**[Wazuh × Shuffle × MikroTik CHR SOAR Starter Kit on OCI (v1.0.0)](https://buy.polar.sh/polar_cl_C3ZRDnWa40mKHDSjUpn2WszNtHRLFRabBDee80SzjBO)** — $29, via Polar.sh

59 files, with a commercial license:

- Terraform IaC modules for OCI (VCN, subnets, security lists, compute)
- A custom MikroTik CHR connector: Python scripts that take blocking requests from the Shuffle SOAR webhook or Wazuh
  Active Response and add the source IP to a dynamic address list through the RouterOS REST API (with an allowlist)
- Wazuh and Shuffle configuration: detection rule, Active Response settings, and the blocking workflow with a script
  that creates it through the Shuffle API
- Step-by-step guides for deployment, validation and cleanup

The kit contains no third-party binaries; Wazuh, Shuffle, MikroTik CHR and OCI are used under their own terms.
It is not required to use or reproduce anything in this repository.

## License

- Code, Terraform and configuration: [MIT](LICENSE)
- Article, diagrams, figures and measurement data (`articles/`, `experiments/*/raw/`, `experiments/*/results/`):
  [CC BY 4.0](LICENSE-CONTENT.md)
