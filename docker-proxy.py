#!/usr/bin/env python3
"""Forward TCP localhost:2375 to unix:///var/run/docker.sock for Testcontainers."""
import socket, threading, os, sys

SOCK = os.environ.get("DOCKER_PROXY_SOCK", "/var/run/docker.sock")
PORT = int(os.environ.get("DOCKER_PROXY_PORT", "2375"))

def handle(client, addr):
    try:
        u = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        u.connect(SOCK)
        def r(src, dst):
            try:
                while True:
                    data = src.recv(8192)
                    if not data: break
                    dst.sendall(data)
            except Exception:
                pass
            finally:
                try: src.close()
                except Exception: pass
                try: dst.close()
                except Exception: pass
        threading.Thread(target=r, args=(client, u), daemon=True).start()
        threading.Thread(target=r, args=(u, client), daemon=True).start()
    except Exception as e:
        sys.stderr.write(f"connect {SOCK} failed: {e}\n")
        sys.stderr.flush()
        client.close()

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", PORT))
s.listen(64)
sys.stdout.write(f"docker-proxy listening on 127.0.0.1:{PORT} -> {SOCK}\n")
sys.stdout.flush()
while True:
    c, a = s.accept()
    threading.Thread(target=handle, args=(c, a), daemon=True).start()