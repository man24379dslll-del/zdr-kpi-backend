"""Генератор внешнего API-ключа. В базу НЕ пишет: печатает ключ (показывается
один раз — сохраните сразу) и готовый INSERT с его SHA-256 хэшем, который
выполняется вручную в Supabase SQL Editor.

Использование:
    python scripts/create_api_key.py "Force affiliate" [--ip 1.2.3.4 --ip 10.0.0.0/24]
"""
import argparse
import ipaddress
import sys
import uuid

sys.path.insert(0, ".")

from app.services.api_keys import SCOPE_OPERATORS_READ, generate_key, hash_key


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--ip", action="append", default=[], help="разрешённый адрес/подсеть (можно несколько)")
    args = parser.parse_args()

    for entry in args.ip:
        ipaddress.ip_network(entry, strict=False)  # ValueError на мусоре

    key = generate_key()
    allowed = "array[" + ", ".join(f"'{e}'" for e in args.ip) + "]::text[]" if args.ip else "null"
    name = args.name.replace("'", "''")
    print("API-КЛЮЧ (показывается один раз, в базе его не будет):")
    print(key)
    print("\nSQL для Supabase SQL Editor:")
    print(
        "insert into api_keys (id, name, key_hash, scope, allowed_ips) values "
        f"('{uuid.uuid4()}', '{name}', '{hash_key(key)}', '{SCOPE_OPERATORS_READ}', {allowed});"
    )


main()
