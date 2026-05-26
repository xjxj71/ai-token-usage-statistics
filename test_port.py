import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind(("127.0.0.1", 8000))
    print("OK: port 8000 available")
except OSError as e:
    print(f"FAIL: {e}")
finally:
    s.close()
