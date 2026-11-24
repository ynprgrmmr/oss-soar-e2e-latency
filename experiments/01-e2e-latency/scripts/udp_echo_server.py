#!/usr/bin/env python3
"""Minimal UDP echo responder for the T3 prober. Runs on the target VM.

    python3 udp_echo_server.py --port 9999
"""
import argparse
import socket


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--bind", default="0.0.0.0")
    p.add_argument("--port", type=int, default=9999)
    args = p.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.bind, args.port))
    print(f"udp echo listening on {args.bind}:{args.port}", flush=True)
    while True:
        data, addr = sock.recvfrom(2048)
        sock.sendto(data, addr)


if __name__ == "__main__":
    main()
