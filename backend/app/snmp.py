import socket
import struct
import time


# ── BER/ASN.1 helpers ────────────────────────────────────────────────────────

def _encode_length(n):
    if n < 0x80:
        return bytes([n])
    b = []
    while n:
        b.append(n & 0xFF)
        n >>= 8
    b.reverse()
    return bytes([0x80 | len(b)] + b)


def _encode_tlv(tag, value):
    return bytes([tag]) + _encode_length(len(value)) + value


def _encode_int(n):
    if n == 0:
        return _encode_tlv(0x02, b'\x00')
    b = []
    while n:
        b.append(n & 0xFF)
        n >>= 8
    b.reverse()
    if b[0] & 0x80:
        b.insert(0, 0x00)
    return _encode_tlv(0x02, bytes(b))


def _encode_string(s):
    if isinstance(s, str):
        s = s.encode()
    return _encode_tlv(0x04, s)


def _encode_oid(oid_str):
    parts = [int(x) for x in oid_str.strip('.').split('.')]
    first = parts[0] * 40 + parts[1]
    encoded = []
    for p in [first] + parts[2:]:
        if p == 0:
            encoded.append(0)
        else:
            buf = []
            while p:
                buf.append(p & 0x7F)
                p >>= 7
            buf.reverse()
            for i, b in enumerate(buf):
                encoded.append(b | (0x80 if i < len(buf) - 1 else 0))
    return _encode_tlv(0x06, bytes(encoded))


def _decode_length(data, pos):
    if data[pos] < 0x80:
        return data[pos], pos + 1
    n_bytes = data[pos] & 0x7F
    length = 0
    for i in range(n_bytes):
        length = (length << 8) | data[pos + 1 + i]
    return length, pos + 1 + n_bytes


def _decode_value(data, pos):
    tag = data[pos]
    length, pos = _decode_length(data, pos + 1)
    value = data[pos:pos + length]
    return tag, value, pos + length


def _decode_oid(value):
    parts = []
    first = value[0]
    parts.append(first // 40)
    parts.append(first % 40)
    i = 1
    while i < len(value):
        n = 0
        while True:
            b = value[i]; i += 1
            n = (n << 7) | (b & 0x7F)
            if not (b & 0x80):
                break
        parts.append(n)
    return '.' + '.'.join(str(p) for p in parts)


def _build_get_request(community, oids, request_id=1):
    # VarBindList
    var_binds = b''
    for oid in oids:
        vb = _encode_oid(oid) + _encode_tlv(0x05, b'')  # OID + Null
        var_binds += _encode_tlv(0x30, vb)
    var_bind_list = _encode_tlv(0x30, var_binds)

    # PDU: GetRequest (0xA0)
    pdu = (_encode_int(request_id) +
           _encode_int(0) +   # error-status
           _encode_int(0) +   # error-index
           var_bind_list)
    get_pdu = _encode_tlv(0xA0, pdu)

    # Message
    msg = (_encode_int(1) +            # version = 2c (1)
           _encode_string(community) +
           get_pdu)
    return _encode_tlv(0x30, msg)


def _parse_response(data, oids):
    try:
        result = {}
        # skip outer sequence
        pos = 2
        if data[1] & 0x80:
            pos = 2 + (data[1] & 0x7F)
        # skip version
        tag, val, pos = _decode_value(data, pos)
        # skip community
        tag, val, pos = _decode_value(data, pos)
        # GetResponse PDU (0xA2)
        pdu_len, pos = _decode_length(data, pos + 1)
        # skip request-id, error-status, error-index
        tag, val, pos = _decode_value(data, pos)
        tag, val, pos = _decode_value(data, pos)
        tag, val, pos = _decode_value(data, pos)
        # VarBindList sequence
        tag, vbl_val, pos2 = _decode_value(data, pos)
        # parse each varbind
        vb_pos = 0
        idx = 0
        while vb_pos < len(vbl_val) and idx < len(oids):
            tag, vb, vb_pos = _decode_value(vbl_val, vb_pos)
            # oid + value inside varbind
            inner_pos = 0
            oid_tag, oid_val, inner_pos = _decode_value(vb, inner_pos)
            val_tag, val_val, inner_pos = _decode_value(vb, inner_pos)
            # decode value based on tag
            if val_tag in (0x02,):  # INTEGER
                n = int.from_bytes(val_val, 'big', signed=True)
                result[oids[idx]] = n
            elif val_tag in (0x04, 0x40, 0x44):  # OCTET STRING / IpAddress / Timeticks raw
                try:
                    result[oids[idx]] = val_val.decode('latin-1').strip('\x00')
                except Exception:
                    result[oids[idx]] = val_val.hex()
            elif val_tag == 0x43:  # TimeTicks
                result[oids[idx]] = int.from_bytes(val_val, 'big')
            elif val_tag == 0x41:  # Counter32
                result[oids[idx]] = int.from_bytes(val_val, 'big')
            elif val_tag == 0x42:  # Gauge32
                result[oids[idx]] = int.from_bytes(val_val, 'big')
            elif val_tag == 0x46:  # Counter64
                result[oids[idx]] = int.from_bytes(val_val, 'big')
            else:
                result[oids[idx]] = val_val
            idx += 1
        return result
    except Exception:
        return {oid: None for oid in oids}


# ── Public API ────────────────────────────────────────────────────────────────

def get_snmp_values(ip, community, oids, timeout=2, retries=0):
    if not oids:
        return {}
    try:
        packet = _build_get_request(community, oids)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(packet, (ip, 161))
        data, _ = sock.recvfrom(4096)
        sock.close()
        return _parse_response(data, oids)
    except Exception:
        return {oid: None for oid in oids}


def get_snmp_value(ip, community, oid, timeout=2, retries=0):
    vals = get_snmp_values(ip, community, [oid], timeout=timeout, retries=retries)
    return vals.get(oid) if vals else None


def get_snmp_walk(ip, community, oid_prefix='1.3.6.1.2.1', max_rows=1000, timeout=2, retries=0):
    # Walk no es crítico para el dashboard, retorna lista vacía si falla
    rows = []
    try:
        import subprocess, sys
        result = subprocess.run(
            ['snmpwalk', '-v2c', '-c', community, ip, oid_prefix],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            parts = line.split(' = ', 1)
            if len(parts) == 2:
                rows.append((parts[0].strip(), parts[1].strip()))
                if len(rows) >= max_rows:
                    break
    except Exception:
        pass
    return rows