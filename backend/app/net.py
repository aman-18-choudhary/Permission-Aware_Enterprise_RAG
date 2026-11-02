import socket

_original = socket.getaddrinfo


def prefer_ipv4() -> None:
    """Resolve hostnames to IPv4 only (falling back to all results if there are none).

    Some networks advertise IPv6 but don't route it; clients then wait for the
    IPv6 connect to time out (15-40s) before trying IPv4. This affects every
    outbound call (Google OAuth, Gemini, Drive, GitHub). Opt-in via FORCE_IPV4.
    """

    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        results = _original(host, port, family, type, proto, flags)
        return [r for r in results if r[0] == socket.AF_INET] or results

    socket.getaddrinfo = getaddrinfo
