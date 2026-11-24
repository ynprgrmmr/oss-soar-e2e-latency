# Code for the Shuffle Tools "execute_python" action of workflow e2e-block-src.
# Shuffle substitutes the exec placeholder (webhook body) and workflow variables BEFORE
# running this, so do not use a dollar sign anywhere else in this file.
import base64, json, re, ssl, tempfile, time, urllib.request

t1_soar_ns = time.time_ns()  # T1_soar: first user code executed in Shuffle

body = json.loads(r"""$exec""")
alert = body.get("all_fields", body)  # Wazuh shuffle integration wraps the alert
srcip = (alert.get("data") or {}).get("srcip")
m = re.search(r"soar-probe-([0-9a-f]{8})", json.dumps(alert))
run_id = m.group(1) if m else None

with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
    f.write(r"""$mikrotik_ca_pem""")
    ca_path = f.name
ctx = ssl.create_default_context(cafile=ca_path)
ctx.check_hostname = False  # cert CN/SAN is the CHR IP; chain is still verified

req = urllib.request.Request(
    "$mikrotik_url/rest/ip/firewall/address-list",
    data=json.dumps({"list": "soar-blocklist", "address": srcip,
                     "timeout": "$block_timeout", "comment": "run=" + str(run_id)}).encode(),
    method="PUT",
    headers={"Content-Type": "application/json",
             "Authorization": "Basic " + base64.b64encode(b"$mikrotik_user:$mikrotik_password").decode()},
)

status, err = None, None
t2_req_ns = time.time_ns()
try:
    with urllib.request.urlopen(req, timeout=5, context=ctx) as r:
        status = r.status
        r.read()
except Exception as e:  # report, never raise: the timestamps are still useful
    err = str(e)[:200]
t2_resp_ns = time.time_ns()

print(json.dumps({"soar_lab": True, "run_id": run_id, "srcip": srcip, "status": status, "error": err,
                  "wazuh_rule": (alert.get("rule") or {}).get("id"),
                  "t1_soar_ns": t1_soar_ns, "t2_req_ns": t2_req_ns, "t2_resp_ns": t2_resp_ns}))
