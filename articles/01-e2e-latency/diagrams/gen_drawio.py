#!/usr/bin/env python3
"""Generate the draw.io diagrams for article 01 (stdlib only).

    python3 gen_drawio.py      # writes oci-topology.drawio, e2e-sequence.drawio

Only private addresses and role names appear: no public IPs, OCIDs or secrets.
"""
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent


class Diagram:
    def __init__(self, name: str, width: int, height: int) -> None:
        self.name, self.w, self.h = name, width, height
        self.cells: list[str] = []
        self.n = 2

    def _id(self) -> str:
        self.n += 1
        return f"c{self.n}"

    def box(self, x, y, w, h, label, style="rounded=1;whiteSpace=wrap;html=1;", parent="1") -> str:
        cid = self._id()
        self.cells.append(
            f'<mxCell id="{cid}" value="{escape(label, {chr(34): "&quot;"})}" style="{style}" vertex="1" parent="{parent}">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return cid

    def edge(self, src, dst, label="", style="endArrow=classic;html=1;", points=None) -> str:
        cid = self._id()
        pts = ""
        if points:
            pts = '<Array as="points">' + "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in points) + "</Array>"
        self.cells.append(
            f'<mxCell id="{cid}" value="{escape(label, {chr(34): "&quot;"})}" style="{style}" edge="1" parent="1" source="{src}" target="{dst}">'
            f'<mxGeometry relative="1" as="geometry">{pts}</mxGeometry></mxCell>')
        return cid

    def line(self, x1, y1, x2, y2, label="", style="endArrow=classic;html=1;") -> str:
        cid = self._id()
        self.cells.append(
            f'<mxCell id="{cid}" value="{escape(label, {chr(34): "&quot;"})}" style="{style}" edge="1" parent="1">'
            f'<mxGeometry relative="1" as="geometry"><mxPoint x="{x1}" y="{y1}" as="sourcePoint"/>'
            f'<mxPoint x="{x2}" y="{y2}" as="targetPoint"/></mxGeometry></mxCell>')
        return cid

    def xml(self) -> str:
        body = "".join(self.cells)
        return (
            '<mxfile host="soar-net-lab" type="device">'
            f'<diagram id="{self.name}" name="{self.name}">'
            f'<mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" '
            f'fold="1" page="1" pageScale="1" pageWidth="{self.w}" pageHeight="{self.h}" math="0" shadow="0">'
            f'<root><mxCell id="0"/><mxCell id="1" parent="0"/>{body}</root></mxGraphModel></diagram></mxfile>\n')


CONTAINER = "rounded=1;whiteSpace=wrap;html=1;verticalAlign=top;align=left;spacingLeft=8;fontStyle=1;"
NODE = "rounded=1;whiteSpace=wrap;html=1;"
ATTACK = "endArrow=classic;html=1;strokeColor=#C62828;strokeWidth=2;fontColor=#C62828;"
CONTROL = "endArrow=classic;html=1;strokeColor=#1565C0;strokeWidth=2;fontColor=#1565C0;"
EVENT = "endArrow=classic;html=1;dashed=1;strokeColor=#6A1B9A;fontColor=#6A1B9A;"
MGMT = "endArrow=classic;html=1;dashed=1;strokeColor=#757575;fontColor=#757575;"


def topology() -> Diagram:
    d = Diagram("oci-topology", 1300, 900)
    internet = d.box(560, 20, 180, 50, "Internet", NODE + "fillColor=#F5F5F5;")
    operator = d.box(860, 20, 260, 50, "Operator (Linux / Control Host)<br>admin_cidr /32 only", NODE + "fillColor=#F5F5F5;")
    d.box(40, 100, 1220, 770, "OCI us-phoenix-1 (home region) / AD-3", CONTAINER + "fillColor=#FAFAFA;dashed=1;")
    d.box(70, 140, 1160, 710, "VCN 10.10.0.0/16", CONTAINER + "fillColor=#FFFFFF;")
    igw = d.box(580, 150, 140, 40, "Internet Gateway", NODE + "fillColor=#ECEFF1;")

    d.box(100, 220, 520, 260, "public 10.10.0.0/24<br><span style=\"font-weight:normal\">rt: 0/0→IGW, 10.10.2.0/24→CHR WAN</span>", CONTAINER + "fillColor=#E3F2FD;")
    soar = d.box(130, 290, 230, 160, "<b>soar</b> 10.10.0.20<br>A1.Flex 3 OCPU / 18 GB<br>Wazuh 4.14.10 (manager, indexer, dashboard)<br>Shuffle 2.3.0 (Docker)", NODE + "fillColor=#BBDEFB;")

    d.box(700, 220, 500, 260, "attacker 10.10.1.0/24<br><span style=\"font-weight:normal\">rt: 0/0→IGW, 10.10.2.0/24→CHR WAN</span>", CONTAINER + "fillColor=#FFEBEE;")
    atk = d.box(830, 300, 240, 110, "<b>attacker</b> 10.10.1.20<br>E2.1.Micro<br>run_trial.py (T0, T3)<br>UDP prober + SSH trigger", NODE + "fillColor=#FFCDD2;")

    chr_ = d.box(470, 520, 360, 110, "<b>MikroTik CHR 7.25.1</b> (A1.Flex 1 OCPU)<br>ether1 10.10.0.10 (WAN) / ether2 10.10.2.10 (LAN)<br>raw prerouting: drop src ∈ soar-blocklist<br>REST (www-ssl) from 10.10.0.0/24 only", NODE + "fillColor=#FFF3E0;strokeColor=#E65100;strokeWidth=2;")

    d.box(100, 670, 1100, 160, "protected 10.10.2.0/24 (private, no public IP)<br><span style=\"font-weight:normal\">rt: 0/0, 10.10.0.0/24, 10.10.1.0/24 → CHR LAN (symmetric path)</span>", CONTAINER + "fillColor=#E8F5E9;")
    tgt = d.box(520, 730, 260, 80, "<b>target</b> 10.10.2.20<br>E2.1.Micro<br>sshd, Wazuh agent, UDP echo :9999", NODE + "fillColor=#C8E6C9;")

    d.edge(internet, igw, "", MGMT)
    d.edge(operator, igw, "SSH / UI (443, 3443)", MGMT)
    d.edge(atk, chr_, "① SSH as soar-probe-&lt;run_id&gt;<br>+ UDP probes (10 ms)", ATTACK, points=[(950, 575)])
    d.edge(chr_, tgt, "", ATTACK)
    d.edge(tgt, soar, "② agent events (1514) via CHR", EVENT, points=[(245, 770)])
    d.edge(soar, chr_, "③ PUT /rest/ip/firewall/address-list", CONTROL, points=[(245, 575)])
    d.box(130, 455, 230, 50, "Wazuh integratord → Shuffle webhook<br>(loopback 127.0.0.1:5001)", "text;html=1;fontSize=10;fontColor=#1565C0;")
    return d


def sequence() -> Diagram:
    d = Diagram("e2e-sequence", 1200, 820)
    names = ["attacker", "CHR", "target", "Wazuh manager", "Shuffle", ]
    xs = [120, 340, 560, 780, 1000]
    for name, x in zip(names, xs):
        d.box(x - 80, 30, 160, 44, f"<b>{name}</b>", NODE + "fillColor=#ECEFF1;")
        d.line(x, 74, x, 780, "", "endArrow=none;html=1;dashed=1;strokeColor=#9E9E9E;")

    def msg(y, a, b, label, style=ATTACK):
        d.line(xs[a], y, xs[b], y, label, style)

    def stamp(y, x, label):
        d.box(x - 95, y - 14, 190, 28, label, "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFF59D;strokeColor=#F9A825;fontStyle=1;")

    msg(110, 0, 2, "UDP probes every 10 ms (echo replies)", "endArrow=classic;html=1;strokeColor=#616161;")
    stamp(160, xs[0], "T0  attacker clock")
    msg(200, 0, 1, "ssh soar-probe-&lt;run_id&gt;")
    msg(230, 1, 2, "forwarded")
    msg(290, 2, 3, "sshd 'Invalid user' → agent → manager", EVENT)
    stamp(340, xs[3], "T1_detect  alerts.json")
    msg(390, 3, 4, "integratord → webhook (rule 100510)", CONTROL)
    stamp(440, xs[4], "T1_soar  python action")
    msg(490, 4, 1, "PUT address-list {srcip, timeout 60s}", CONTROL)
    msg(530, 1, 4, "201 Created", CONTROL)
    stamp(575, xs[4], "T2  API response")
    msg(630, 0, 1, "UDP probe → dropped (raw prerouting)", ATTACK)
    stamp(680, xs[0], "T3  first unanswered probe")
    d.box(240, 720, 720, 50,
          "D_detect = T1_detect − T0 · D_dispatch = T1_soar − T1_detect · D_api = T2 − T1_soar · "
          "D_enforce = T3 − T2 · <b>D_e2e = T3 − T0</b> (T0 and T3 on the same clock)",
          "rounded=0;whiteSpace=wrap;html=1;fillColor=#FAFAFA;fontSize=11;")
    return d


if __name__ == "__main__":
    for diag in (topology(), sequence()):
        (HERE / f"{diag.name}.drawio").write_text(diag.xml())
        print("wrote", diag.name + ".drawio")
