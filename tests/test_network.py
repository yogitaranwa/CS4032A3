import ipaddress
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEEDS = [("app", 1000), ("public", 250), ("data", 100), ("management", 20)]


def allocate():
    base = int(ipaddress.ip_address("10.20.0.0"))
    out = {}
    for name, hosts in NEEDS:
        prefix = 32
        while 2 ** (32 - prefix) - 2 < hosts:
            prefix -= 1
        net = ipaddress.ip_network((base, prefix))
        out[name] = net
        base = int(net.broadcast_address) + 1
    return out


def test_subnets_md_matches_computation():
    text = (ROOT / "network" / "subnets.md").read_text()
    for name, net in allocate().items():
        hosts = net.num_addresses - 2
        for token in (str(net.network_address), f"/{net.prefixlen}", str(net[1]), str(net[-2]),
                      str(net.broadcast_address), f"{hosts:,}"):
            assert token in text, (name, token)
        row = [ln for ln in text.splitlines() if re.match(rf"\|\s*{name}\s*\|\s*{re.escape(str(net.network_address))}", ln)]
        assert row, name


def test_nacl_passes_sample_packets():
    res = subprocess.run([sys.executable, str(ROOT / "tools" / "nacl_sim.py"), str(ROOT / "network" / "nacl.json"),
                          str(ROOT / "network" / "packets_sample.jsonl"), "--check"],
                         capture_output=True, text=True, check=True)
    assert "6 / 6" in res.stdout


def decide(rules, direction, proto, port, addr):
    sys.path.insert(0, str(ROOT / "tools"))
    import nacl_sim
    loaded = nacl_sim.load_rules(str(ROOT / "network" / "nacl.json"))
    return nacl_sim.decide(loaded, {"direction": direction, "protocol": proto, "port": port, "address": addr})[0]


def test_nacl_extra_cases():
    cases = [
        ("inbound", "tcp", 80, "203.0.113.5", "allow"),
        ("inbound", "tcp", 80, "198.51.100.200", "deny"),
        ("inbound", "tcp", 22, "10.20.5.130", "allow"),
        ("inbound", "tcp", 22, "10.20.5.20", "deny"),
        ("inbound", "udp", 443, "203.0.113.5", "deny"),
        ("inbound", "tcp", 40000, "10.20.2.9", "allow"),
        ("inbound", "tcp", 40000, "203.0.113.5", "deny"),
        ("inbound", "tcp", 500, "10.20.2.9", "deny"),
        ("outbound", "tcp", 8000, "10.20.3.254", "allow"),
        ("outbound", "tcp", 443, "203.0.113.5", "deny"),
        ("outbound", "tcp", 1024, "203.0.113.5", "allow"),
        ("outbound", "tcp", 1023, "203.0.113.5", "deny"),
    ]
    for d, p, port, addr, want in cases:
        assert decide(None, d, p, port, addr) == want, (d, p, port, addr)


def test_nacl_rule_numbers_unique_and_deny_first():
    data = json.loads((ROOT / "network" / "nacl.json").read_text())
    inbound = sorted(data["inbound"], key=lambda r: r["rule"])
    assert inbound[0]["action"] == "deny" and inbound[0]["cidr"] == "198.51.100.0/24"
