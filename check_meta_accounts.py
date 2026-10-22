import os
import requests


def main():
    token = os.environ.get("META_ACCESS_TOKEN", "").strip()
    if not token:
        raise SystemExit("META_ACCESS_TOKEN secret tanımlı değil.")
    response = requests.get(
        "https://graph.facebook.com/v24.0/me/accounts",
        params={
            "fields": "id,name,instagram_business_account{id,username}",
            "access_token": token,
        },
        timeout=30,
    )
    payload = response.json()
    if not response.ok or payload.get("error"):
        error = payload.get("error") or {}
        # Token or URL is deliberately never printed.
        print(f"Meta token kontrolü başarısız: {error.get('message', f'HTTP {response.status_code}')}")
        raise SystemExit(1)
    accounts = payload.get("data", [])
    print(f"Token geçerli; erişilebilen sayfa sayısı: {len(accounts)}")
    for page in accounts:
        instagram = page.get("instagram_business_account") or {}
        print(
            f"Facebook: {page.get('name')} (ID {page.get('id')}) | "
            f"Instagram: {instagram.get('username') or 'bağlı değil'}"
        )
    if payload.get("paging", {}).get("next"):
        print("Not: Meta yanıtında devam sayfası var; liste kısmi olabilir.")


if __name__ == "__main__":
    main()
