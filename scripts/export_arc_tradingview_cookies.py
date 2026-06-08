"""Export TradingView cookies from Arc's live Chromium profile."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


ARC_COOKIES_DB = Path.home() / "Library/Application Support/Arc/User Data/Default/Cookies"
OUTPUT_PATH = Path("secrets/tv_cookies.json")
WORK_DB_PATH = Path("/tmp/arc_tv_cookies.sqlite")


def _derive_arc_key() -> bytes:
    password = subprocess.check_output(
        ["security", "find-generic-password", "-s", "Arc Safe Storage", "-w"],
        text=True,
    ).strip().encode()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=16,
        salt=b"saltysalt",
        iterations=1003,
    )
    return kdf.derive(password)


def _decrypt_cookie_value(encrypted_value: bytes, host_key: str, key: bytes) -> str:
    if not encrypted_value:
        return ""

    if encrypted_value.startswith((b"v10", b"v11")):
        payload = encrypted_value[3:]
        cipher = Cipher(algorithms.AES(key), modes.CBC(b" " * 16))
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(payload) + decryptor.finalize()
        pad_len = decrypted[-1]
        decrypted = decrypted[:-pad_len]

        host_prefix = hashes.Hash(hashes.SHA256())
        host_prefix.update(host_key.encode("utf-8"))
        digest = host_prefix.finalize()
        if decrypted.startswith(digest):
            decrypted = decrypted[len(digest) :]

        return decrypted.decode("utf-8", errors="ignore")

    return encrypted_value.decode("utf-8", errors="ignore")


def _chrome_ts_to_iso(value: int | None) -> str | None:
    if not value:
        return None
    unix_us = value - 11644473600000000
    if unix_us <= 0:
        return None
    return (
        datetime.fromtimestamp(unix_us / 1_000_000, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def export_arc_tradingview_cookies() -> list[dict[str, object]]:
    shutil.copy2(ARC_COOKIES_DB, WORK_DB_PATH)
    key = _derive_arc_key()

    conn = sqlite3.connect(WORK_DB_PATH)
    cursor = conn.cursor()
    rows = cursor.execute(
        """
        select name, encrypted_value, host_key, path, is_secure, is_httponly, expires_utc, samesite
        from cookies
        where host_key like '%tradingview.com%'
        order by host_key, name
        """
    ).fetchall()
    conn.close()

    same_site_map = {-1: "None", 0: "None", 1: "Lax", 2: "Strict"}
    exported: list[dict[str, object]] = []
    for (
        name,
        encrypted_value,
        host_key,
        path,
        is_secure,
        is_httponly,
        expires_utc,
        samesite,
    ) in rows:
        exported.append(
            {
                "name": name,
                "value": _decrypt_cookie_value(encrypted_value, host_key, key),
                "domain": host_key,
                "path": path,
                "secure": bool(is_secure),
                "httpOnly": bool(is_httponly),
                "sameSite": same_site_map.get(samesite, "None"),
                "expirationDate": _chrome_ts_to_iso(expires_utc),
            }
        )

    OUTPUT_PATH.write_text(json.dumps(exported, indent=2))
    return exported


if __name__ == "__main__":
    cookies = export_arc_tradingview_cookies()
    print(
        json.dumps(
            {
                "written": str(OUTPUT_PATH),
                "cookie_count": len(cookies),
                "sessionid_present": any(
                    cookie["name"] == "sessionid" and cookie["value"] for cookie in cookies
                ),
            },
            indent=2,
        )
    )
