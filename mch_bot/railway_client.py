from __future__ import annotations

import os
import logging
from typing import Optional, Dict, Any
import requests


log = logging.getLogger(__name__)


def update_env_variable(service_id: str, token: str, variables: Dict[str, Any]) -> bool:
    """Update Railway service variables via REST API.

    This uses a simplified endpoint contract; Railway may use GraphQL in some plans.
    """
    try:
        url = f"https://backboard.railway.app/v1/services/{service_id}/variables"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"variables": variables}
        resp = requests.patch(url, json=payload, headers=headers, timeout=15)
        if resp.status_code // 100 == 2:
            return True
        log.warning(f"Railway env update failed: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        log.warning(f"Railway env update error: {e}")
        return False

