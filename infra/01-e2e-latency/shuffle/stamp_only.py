# Action 1 of the C3 two-step workflow (Shuffle Tools / execute_python).
# Only stamps T1_soar and extracts srcip/run_id; the CHR call is done by the
# stock HTTP app in action 2. Shuffle substitutes the exec placeholder before
# running, so no other dollar signs may appear in this file.
import json, re, time

t1_soar_ns = time.time_ns()
body = json.loads(r"""$exec""")
alert = body.get("all_fields", body)
srcip = (alert.get("data") or {}).get("srcip")
m = re.search(r"soar-probe-([0-9a-f]{8})", json.dumps(alert))
print(json.dumps({"soar_lab": True, "variant": "two-step", "run_id": m.group(1) if m else None,
                  "srcip": srcip, "wazuh_rule": (alert.get("rule") or {}).get("id"),
                  "t1_soar_ns": t1_soar_ns}))
