"""Read-only GitHub Actions secret-name preflight; never reads secret values."""
import json
import subprocess
import sys

REPOSITORY = "emirhankaya985-cloud/auto-video-publisher"
REQUIRED = ("TOKEN_CHANNEL1_JSON", "TOKEN_CHANNEL2_JSON")
OPTIONAL_GROUPS = {
    # Used only by optional Drive-backed reports/audits/backup and disabled legacy routes.
    "drive_dependent_features": ("DRIVE_TOKEN_JSON",),
    "ntfy": ("NTFY_TOPIC_URL", "NTFY_TOPIC"),
}


def assess_names(names):
    available = {str(name).strip() for name in names if str(name).strip()}
    required = {name: name in available for name in REQUIRED}
    optional = {group: any(name in available for name in alternatives)
                for group, alternatives in OPTIONAL_GROUPS.items()}
    return {
        "repository": REPOSITORY,
        "required": required,
        "missing_required": [name for name, present in required.items() if not present],
        "optional": optional,
        "required_names_present": all(required.values()),
        "secret_values_read": False,
    }


def _run(args, runner=subprocess.run):
    result = runner(args, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def inspect_repository(runner=subprocess.run):
    login = _run(["gh", "api", "user", "--jq", ".login"], runner)
    if login != "emirhankaya985-cloud":
        raise RuntimeError("GitHub CLI must be authenticated as emirhankaya985-cloud")
    raw = _run(["gh", "secret", "list", "--repo", REPOSITORY,
                "--json", "name", "--jq", ".[].name"], runner)
    # gh versions differ in how they format a jq result; accept one name per line.
    names = [line.strip().strip('"') for line in raw.splitlines() if line.strip()]
    return assess_names(names)


def main():
    try:
        result = inspect_repository()
    except Exception as exc:
        # Do not print subprocess stderr: it may contain environmental details.
        print(json.dumps({"status": "unavailable", "error_type": type(exc).__name__,
                          "secret_values_read": False}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["required_names_present"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
