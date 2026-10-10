"""Create the project alert budget and Cloud Run spend cap if missing."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ALERT_NAME = "POC Dev Fest 2026 - alerta R$5"
CAP_NAME = "POC Dev Fest 2026 - spend cap Cloud Run R$5"
CLOUD_RUN_SERVICE_ID = "152E-C115-5142"


def main() -> int:
    if len(sys.argv) != 3:
        print("Uso: ensure_cloud_budgets.py PROJECT_ID BILLING_ACCOUNT_ID", file=sys.stderr)
        return 2
    project_id, billing_account_id = sys.argv[1:]
    token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
    base_url = (
        f"https://billingbudgets.googleapis.com/v1/billingAccounts/{billing_account_id}/budgets"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": project_id,
    }
    existing_budgets: dict[str, dict[str, object]] = {}
    page_token = ""
    while True:
        query = "?pageSize=100"
        if page_token:
            query += f"&pageToken={page_token}"
        existing = get_json(f"{base_url}{query}", headers)
        budgets_value = existing.get("budgets", [])
        if isinstance(budgets_value, list):
            for item in budgets_value:
                if isinstance(item, dict):
                    existing_budgets[str(item.get("displayName", ""))] = item
        page_token = str(existing.get("nextPageToken", ""))
        if not page_token:
            break

    alert_budget = {
        "displayName": ALERT_NAME,
        "budgetFilter": {
            "projects": [f"projects/{project_id}"],
            "calendarPeriod": "MONTH",
        },
        "amount": {"specifiedAmount": {"currencyCode": "BRL", "units": "5"}},
        "thresholdRules": [
            {"thresholdPercent": percent, "spendBasis": "CURRENT_SPEND"}
            for percent in (0.5, 0.8, 1.0)
        ],
    }
    spend_cap = {
        "displayName": CAP_NAME,
        "budgetFilter": {
            "projects": [f"projects/{project_id}"],
            "services": [f"services/{CLOUD_RUN_SERVICE_ID}"],
            "creditTypesTreatment": "EXCLUDE_ALL_CREDITS",
            "calendarPeriod": "MONTH",
        },
        "amount": {"specifiedAmount": {"currencyCode": "BRL", "units": "5"}},
        "thresholdRules": [
            {"thresholdPercent": percent, "spendBasis": "CURRENT_SPEND"}
            for percent in (0.5, 0.8, 1.0)
        ],
        "notificationsRule": {"enableProjectLevelRecipients": True},
        "spendCap": {"inputState": "CONFIGURED"},
    }

    budget_specs = (
        (ALERT_NAME, (ALERT_NAME, "POC Dev Fest 2026 - alerta R$1"), alert_budget),
        (
            CAP_NAME,
            (CAP_NAME, "POC Dev Fest 2026 - spend cap Cloud Run R$1"),
            spend_cap,
        ),
    )
    for _name, aliases, payload in budget_specs:
        existing_name = next((alias for alias in aliases if alias in existing_budgets), None)
        if existing_name:
            budget = existing_budgets[existing_name]
            amount_value = budget.get("amount", {})
            amount = (
                amount_value.get("specifiedAmount", {}) if isinstance(amount_value, dict) else {}
            )
            if amount.get("currencyCode") == "BRL" and str(amount.get("units")) == "5":
                print(f"Budget já está em R$ 5: {existing_name}")
            else:
                raise RuntimeError(
                    f"Budget existente {existing_name} precisa ser ajustado manualmente para R$ 5."
                )
        else:
            created = request_json("POST", base_url, headers, cast(dict[str, object], payload))
            print(f"Budget criado: {created.get('displayName')} ({created.get('name')})")
    return 0


def get_json(url: str, headers: dict[str, str]) -> dict[str, object]:
    return request_json("GET", url, headers)


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as response:
            value = json.load(response)
            if not isinstance(value, dict):
                raise RuntimeError("Cloud Billing Budget API retornou JSON incompatível.")
            return value
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Cloud Billing Budget API respondeu HTTP {exc.code}: {detail}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
