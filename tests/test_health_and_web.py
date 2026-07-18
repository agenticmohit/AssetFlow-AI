from sqlalchemy import select

from assetflow.db.models import Workspace


def test_health_checks(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["database"] == "connected"


def test_dashboard_and_asset_pages_render(client):
    landing = client.get("/")
    assert landing.status_code == 200
    assert "Creative work moves faster" in landing.text
    assert "The feedback loop is" in landing.text
    assert "Make It Pop" in landing.text
    assert "AssetFlow" not in landing.text
    assert "landing-menu-toggle" in landing.text
    assert "landing-mobile-menu" in landing.text
    assert "/static/make-it-pop-logo.png" in landing.text
    client.post(
        "/api/auth/signup",
        json={
            "email": "web@example.com",
            "name": "Web User",
            "password": "strong-password",
            "workspace_name": "Web Studio",
        },
    )
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Make It Pop" in dashboard.text
    assert "Review queue" in dashboard.text
    assert "Open approvals\">✓" not in dashboard.text
    assert "data-theme-toggle" in dashboard.text
    assert "preview-retention-note" in dashboard.text
    assert "sidebar-note" not in dashboard.text
    assert "sidebar-project-list" in dashboard.text
    assert "/static/make-it-pop-logo.png" in dashboard.text

    landing_css = client.get("/static/landing.css").text
    assert "grid-template-columns:minmax(0,.92fr) minmax(0,1.08fr)" in landing_css
    assert ".product-feedback{display:none}" not in landing_css
    app_js = client.get("/static/app.js").text
    assert "make-it-pop-pending-comments-v1" in app_js
    assert 'window.addEventListener("online"' in app_js
    assert 'document.addEventListener("htmx:beforeSwap"' in app_js


def test_dashboard_paginates_designs_and_preserves_queue_filter(client):
    signup = client.post(
        "/api/auth/signup",
        json={
            "email": "pagination@example.com",
            "name": "Pagination Designer",
            "password": "strong-password",
            "workspace_name": "Pagination Studio",
        },
    )
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    project = client.post(
        "/api/workspaces/1/projects", headers=headers, json={"name": "Large campaign"}
    ).json()
    for index in range(8):
        client.post(
            f"/api/projects/{project['id']}/assets",
            headers=headers,
            json={"title": f"Paginated design {index + 1}"},
        )

    first_page = client.get("/")
    second_page = client.get("/?page=2")
    filtered = client.get("/?page=2&queue=completed")

    assert first_page.status_code == 200
    assert first_page.text.count('class="creative-card ') == 6
    assert "Page <b>1</b> of 2" in first_page.text
    assert "Showing <b>1–6</b> of <b>8</b> designs" in first_page.text
    assert second_page.text.count('class="creative-card ') == 2
    assert "Page <b>2</b> of 2" in second_page.text
    assert 'href="/?page=1&queue=all"' in second_page.text
    assert filtered.status_code == 200
    assert "No designs match this view" in filtered.text
    assert 'class="active" aria-current="page">Completed</a>' in filtered.text


def test_theme_assets_are_available_on_public_and_auth_pages(client):
    for path in ("/", "/login", "/signup"):
        page = client.get(path)
        assert "/static/theme-init.js?v=1" in page.text
        assert "/static/theme.css?v=night-13" in page.text
        assert "/static/make-it-pop.css?v=brand-20" in page.text
        assert "data-theme-toggle" in page.text
        assert '<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32.png?v=2">' in page.text
        assert '<link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png?v=2">' in page.text

    logo = client.get("/static/make-it-pop-logo.png")
    assert logo.status_code == 200
    assert logo.headers["content-type"] == "image/png"
    stacked_logo = client.get("/static/make-it-pop-logo-stacked.png")
    assert stacked_logo.status_code == 200
    assert stacked_logo.headers["content-type"] == "image/png"
    dark_logo = client.get("/static/make-it-pop-logo-dark.png")
    assert dark_logo.status_code == 200
    assert dark_logo.headers["content-type"] == "image/png"
    dark_stacked_logo = client.get("/static/make-it-pop-logo-stacked-dark.png")
    assert dark_stacked_logo.status_code == 200
    assert dark_stacked_logo.headers["content-type"] == "image/png"
    for favicon in ("favicon-32.png", "favicon-64.png", "favicon-192.png", "apple-touch-icon.png"):
        response = client.get(f"/static/{favicon}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
    landing_html = client.get("/").text
    login_html = client.get("/login").text
    assert '/static/make-it-pop-logo.png?v=horizontal-2' in landing_html
    assert '/static/make-it-pop-logo-dark.png?v=horizontal-dark-1' in landing_html
    assert '/static/make-it-pop-logo.png?v=horizontal-2' in login_html
    assert '/static/make-it-pop-logo-dark.png?v=horizontal-dark-1' in login_html


def test_request_observability_headers(client):
    response = client.get("/health/live", headers={"x-request-id": "test-request"})
    assert response.headers["x-request-id"] == "test-request"
    assert float(response.headers["x-response-time-ms"]) >= 0


def test_web_authentication_flow(client):
    assert client.get("/login").status_code == 200
    assert client.get("/signup").status_code == 200
    failed = client.post(
        "/login", data={"email": "missing@example.com", "password": "incorrect"}, follow_redirects=False
    )
    assert failed.status_code == 303
    assert failed.headers["location"] == "/login?error=invalid"
    assert "does not match" in client.get(failed.headers["location"]).text
    missing = client.post("/login", data={}, follow_redirects=False)
    assert missing.status_code == 303
    assert missing.headers["location"] == "/login?error=missing"
    signup = client.post(
        "/signup",
        data={
            "email": "browser@example.com",
            "name": "Browser User",
            "password": "strong-password",
            "workspace_name": "Browser Studio",
        },
        follow_redirects=False,
    )
    assert signup.status_code == 303
    assert client.get("/").status_code == 200
    logout = client.post("/logout", follow_redirects=False)
    assert logout.status_code == 303
    assert logout.headers["location"] == "/"
    signed_out_home = client.get("/", follow_redirects=False)
    assert signed_out_home.status_code == 200
    assert "Start your first review" in signed_out_home.text
    direct_logout = client.get("/logout", follow_redirects=False)
    assert direct_logout.status_code == 303
    assert direct_logout.headers["location"] == "/"

    duplicate = client.post(
        "/signup",
        data={
            "email": "browser@example.com",
            "name": "Browser User",
            "password": "strong-password",
            "workspace_name": "Another Studio",
        },
        follow_redirects=False,
    )
    assert duplicate.status_code == 303
    assert duplicate.headers["location"] == "/signup?error=account_exists"
    duplicate_page = client.get(duplicate.headers["location"])
    assert duplicate_page.status_code == 200
    assert "already exists" in duplicate_page.text

    invalid_signup = client.post(
        "/signup",
        data={"email": "not-an-email", "name": "A", "password": "short"},
        follow_redirects=False,
    )
    assert invalid_signup.status_code == 303
    assert invalid_signup.headers["location"] == "/signup?error=invalid_details"
    assert "Check your details" in client.get(invalid_signup.headers["location"]).text


def test_web_signup_allows_an_unnamed_personal_workspace(client, db):
    page = client.get("/signup")
    assert page.status_code == 200
    assert "Workspace name <small>(optional)</small>" in page.text
    assert 'name="workspace_name"' in page.text
    workspace_input = page.text.split('name="workspace_name"', 1)[1].split(">", 1)[0]
    assert "required" not in workspace_input

    signup = client.post(
        "/signup",
        data={
            "email": "independent@example.com",
            "name": "Independent Designer",
            "password": "strong-password",
            "workspace_name": "",
        },
        follow_redirects=False,
    )

    assert signup.status_code == 303
    assert signup.headers["location"] == "/"
    workspace = db.scalar(select(Workspace))
    assert workspace.name == "Personal workspace"


def test_persisted_asset_page_and_comment(client):
    signup = client.post(
        "/api/auth/signup",
        json={
            "email": "asset@example.com",
            "name": "Asset User",
            "password": "strong-password",
            "workspace_name": "Asset Studio",
        },
    )
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    project = client.post(
        "/api/workspaces/1/projects", headers=headers, json={"name": "UI campaign"}
    )
    asset = client.post(
        f"/api/projects/{project.json()['id']}/assets",
        headers=headers,
        json={"title": "UI poster"},
    )
    page = client.get(f"/assets/{asset.json()['id']}")
    assert page.status_code == 200
    assert "UI poster" in page.text
    assert "data-resilient-comment" in page.text
    assert 'name="client_request_id"' in page.text
    assert "/static/app.js?v=release-13" in page.text
    comment = client.post(
        f"/assets/{asset.json()['id']}/comments", data={"text": "Polish the hierarchy"}
    )
    assert comment.status_code == 200
    assert "Polish the hierarchy" in comment.text
