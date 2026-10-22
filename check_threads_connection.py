"""Read-only Threads profile check. Never creates a container or post."""
from threads_publisher import validate_threads_identity


def main():
    identity = validate_threads_identity()
    print(
        "Threads bağlantısı doğrulandı: "
        f"@{identity['username']} (user_id={identity['id']}); yayın oluşturulmadı.",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        suffix = f"; HTTP {status}" if status is not None else ""
        print(f"Threads bağlantı denetimi başarısız: {type(exc).__name__}{suffix}.", flush=True)
        raise SystemExit(1)
