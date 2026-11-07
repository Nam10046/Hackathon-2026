"""Small client for the Grafana HTTP API, used to set up customers. Owner: backend person."""
import os

import httpx


class GrafanaError(RuntimeError):
    pass


class Grafana:
    def __init__(self):
        self.url = os.getenv("GRAFANA_URL", "http://grafana:3000").rstrip("/")
        self.auth = (os.getenv("GRAFANA_ADMIN_USER", "admin"), os.getenv("GRAFANA_ADMIN_PASSWORD", ""))

    def _call(self, method, path, org=None, ok=(200,), **kw):
        headers = {"X-Grafana-Org-Id": str(org)} if org else {}
        r = httpx.request(method, self.url + path, auth=self.auth, headers=headers, timeout=20, **kw)
        if r.status_code not in ok:   # the body can echo what we sent, so it never goes into the error text
            raise GrafanaError(f"{method} {path} -> {r.status_code}")
        return r

    def anonymous_is_off(self) -> bool:
        return httpx.get(self.url + "/api/org", timeout=10).status_code == 401

    def create_org(self, name) -> int:
        return self._call("POST", "/api/orgs", json={"name": name}).json()["orgId"]

    def delete_org(self, org_id):
        self._call("DELETE", f"/api/orgs/{org_id}", ok=(200, 404))

    def upsert_datasource(self, org, body):
        r = self._call("GET", f"/api/datasources/uid/{body['uid']}", org=org, ok=(200, 404))
        if r.status_code == 404:
            self._call("POST", "/api/datasources", org=org, json=body)
        else:
            self._call("PUT", f"/api/datasources/uid/{body['uid']}", org=org, json=body)

    def ensure_folder(self, org, uid, title):
        if self._call("GET", f"/api/folders/{uid}", org=org, ok=(200, 404)).status_code == 404:
            self._call("POST", "/api/folders", org=org, json={"uid": uid, "title": title})
        # replaces the defaults: inside a customer org everyone may only look
        self._call("POST", f"/api/folders/{uid}/permissions", org=org, json={"items": [
            {"role": "Viewer", "permission": 1}, {"role": "Editor", "permission": 1}]})

    def save_dashboard(self, org, dashboard, folder_uid):
        self._call("POST", "/api/dashboards/db", org=org,
                   json={"dashboard": dashboard, "folderUid": folder_uid, "overwrite": True})

    def set_home(self, org, dashboard_uid):
        self._call("PATCH", "/api/org/preferences", org=org, json={"homeDashboardUID": dashboard_uid})

    def find_user(self, email) -> dict | None:
        r = self._call("GET", "/api/users/lookup", params={"loginOrEmail": email}, ok=(200, 404))
        return r.json() if r.status_code == 200 else None

    def create_user(self, email, password, org_id) -> int:
        return self._call("POST", "/api/admin/users", json={
            "name": email, "email": email, "login": email, "password": password, "OrgId": org_id}).json()["id"]

    def only_in_org(self, user_id, email, org_id):
        """Viewer in the customer's org and nothing else: never left in org 1, which holds the admin data."""
        self._call("POST", f"/api/orgs/{org_id}/users", json={"loginOrEmail": email, "role": "Viewer"}, ok=(200, 409))
        self._call("PATCH", f"/api/orgs/{org_id}/users/{user_id}", json={"role": "Viewer"})
        self._call("POST", f"/api/users/{user_id}/using/{org_id}")
        for o in self._call("GET", f"/api/users/{user_id}/orgs").json():
            if o["orgId"] != org_id:
                self._call("DELETE", f"/api/orgs/{o['orgId']}/users/{user_id}")

    def set_disabled(self, user_id, disabled: bool):
        self._call("POST", f"/api/admin/users/{user_id}/{'disable' if disabled else 'enable'}")
        if disabled:
            self._call("POST", f"/api/admin/users/{user_id}/logout", ok=(200, 400, 404))


def client() -> Grafana:
    return Grafana()
