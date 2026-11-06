# Task 5: Subnetting and Network Access Control

Address block: `10.20.0.0/16` (65,536 addresses). Usable hosts = 2^(32 - prefix) - 2.

## 1. Working

Allocation order is largest requirement first, each subnet placed right after the previous one,
using the smallest prefix whose usable host count covers the requirement.

| Subnet     | Hosts needed | Host bits h (need 2^h - 2 >= hosts) | Prefix = 32 - h | Block size |
|------------|-------------:|-------------------------------------|----------------:|-----------:|
| app        | 1,000        | 2^9 - 2 = 510 (too small); 2^10 - 2 = 1,022 (fits) | /22 | 1,024 |
| public     | 250          | 2^7 - 2 = 126 (too small); 2^8 - 2 = 254 (fits)    | /24 | 256   |
| data       | 100          | 2^6 - 2 = 62 (too small); 2^7 - 2 = 126 (fits)     | /25 | 128   |
| management | 20           | 2^4 - 2 = 14 (too small); 2^5 - 2 = 30 (fits)      | /27 | 32    |

Placement (offsets from 10.20.0.0):

1. app starts at 10.20.0.0. A /22 is 1,024 addresses = 4 x 256, so it covers 10.20.0.0 - 10.20.3.255.
2. public starts at the next address, 10.20.4.0. A /24 is 256 addresses, so it covers 10.20.4.0 - 10.20.4.255.
3. data starts at 10.20.5.0. A /25 is 128 addresses, so it covers 10.20.5.0 - 10.20.5.127.
4. management starts at 10.20.5.128. A /27 is 32 addresses, so it covers 10.20.5.128 - 10.20.5.159.

Alignment check: each network address is a multiple of its block size (0 of 1024, 4.0 of 256, 5.0 of 128, 5.128 of 32).
Network address is the first address of the block, broadcast is the last, usable hosts are everything between.

## 2. Result

| Subnet     | Network address | Prefix | Usable host range            | Broadcast address | Usable hosts |
|------------|-----------------|--------|------------------------------|-------------------|-------------:|
| app        | 10.20.0.0       | /22    | 10.20.0.1 - 10.20.3.254      | 10.20.3.255       | 1,022 |
| public     | 10.20.4.0       | /24    | 10.20.4.1 - 10.20.4.254      | 10.20.4.255       | 254   |
| data       | 10.20.5.0       | /25    | 10.20.5.1 - 10.20.5.126      | 10.20.5.127       | 126   |
| management | 10.20.5.128     | /27    | 10.20.5.129 - 10.20.5.158    | 10.20.5.159       | 30    |

(`tests/test_network.py` recomputes this table with Python's `ipaddress` module and compares it with this file.)

## 3. NACL for the public subnet (`network/nacl.json`)

The load balancer lives in the public subnet. Rules are evaluated from the lowest number up, first match wins,
no match means deny, and nothing is remembered between packets (stateless).

Inbound (rule matches the packet's SOURCE address, port is the destination port):

| Rule | Protocol | Port        | Source           | Action | Purpose |
|-----:|----------|-------------|------------------|--------|---------|
| 100  | all      | all         | 198.51.100.0/24  | deny   | known abusive range, must beat the web allow rules |
| 110  | tcp      | 80          | 0.0.0.0/0        | allow  | HTTP |
| 120  | tcp      | 443         | 0.0.0.0/0        | allow  | HTTPS |
| 130  | tcp      | 22          | 10.20.5.128/27   | allow  | SSH from the management subnet only |
| 140  | tcp      | 1024-65535  | 10.20.0.0/22     | allow  | replies coming back from the app subnet (the load balancer's ephemeral ports) |
| *    | all      | all         | 0.0.0.0/0        | deny   | implicit default |

Outbound (rule matches the packet's DESTINATION address):

| Rule | Protocol | Port        | Destination      | Action | Purpose |
|-----:|----------|-------------|------------------|--------|---------|
| 100  | tcp      | 8000        | 10.20.0.0/22     | allow  | load balancer to the service in the app subnet |
| 110  | tcp      | 1024-65535  | 0.0.0.0/0        | allow  | replies going back to clients (ephemeral ports) anywhere |
| *    | all      | all         | 0.0.0.0/0        | deny   | implicit default |

Check: `python tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check`

## 4. Explanation

A stateless NACL keeps no connection table. When a client opens a connection to port 443, the NACL allows the
request packet in, but the reply is a separate packet in the opposite direction, with the client's ephemeral port
as its destination. The NACL judges that reply on its own, so it needs its own rule: outbound TCP 1024-65535 for
replies to clients, and inbound TCP 1024-65535 from the app subnet for replies to the load balancer's own requests
to port 8000. Without those rules the replies hit the default deny and every connection hangs.

Rule order matters because the first match wins. The deny for 198.51.100.0/24 has number 100, lower than the
allow rules for ports 80 and 443 (110, 120). A packet from 198.51.100.9 to port 443 matches rule 100 first and is
dropped. If the deny had a higher number than 110 or 120, the allow rule would match first and the abusive range
would get through on web ports.
