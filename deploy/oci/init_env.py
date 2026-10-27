"""Generate deployment secrets on the OCI VM; never overwrite existing secrets."""

import argparse
import ipaddress
import os
import re
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("domain", help="Public DNS hostname pointing to the VM, without https://")
    args = parser.parse_args()
    domain = args.domain.lower().rstrip(".")
    if len(domain) > 253 or not re.fullmatch(
        r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
        r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?",
        domain,
    ):
        parser.error("Use a public DNS hostname, such as api.example.com (no URL, port, or wildcard).")
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        parser.error("Use a DNS hostname for HTTPS, not an IP address.")
    path = Path(__file__).with_name(".env")
    contents = (
        f"APP_DOMAIN={domain}\nPOSTGRES_PASSWORD={secrets.token_hex(32)}\nDJANGO_SECRET_KEY={secrets.token_hex(50)}\n"
    )
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        parser.error(f"{path} already exists; keep its database password and Django key for redeployments.")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
        output.write(contents)
    print(f"Created {path}. Keep this file private and backed up; secrets were not printed.")


if __name__ == "__main__":
    main()
