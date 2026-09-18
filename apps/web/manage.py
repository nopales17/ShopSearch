"""Merchant shell: sign in, sign out, `/manage` and photo+price publish (S6/S7).

The store is resolved from the hostname before this shell runs, and every session
lookup is scoped to that store, so a session from another store yields no identity.
State-changing requests carry a CSRF token; login failures are generic; publication
accepts no store or merchant identifier from the form.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import quote

from apps.web import manage_views as views
from backend.auth.service import (
    CSRF_BYTES,
    LOGIN_CSRF_COOKIE,
    MERCHANT_COOKIE,
    MerchantAuth,
    clear_cookie_header,
    csrf_matches,
    login_csrf_cookie_header,
    merchant_cookie_header,
)
from backend.catalog.publish import MerchantPublisher, PublishError
from backend.catalog.store_repository import CatalogError, CatalogRepository
from backend.media.uploads import UploadError
from backend.search.vector_source import EMBEDDING_DIMENSIONS
from contracts.auth import MerchantSession
from contracts.store import Store

HANDLED_PATHS = (
    views.MANAGE_PATH,
    views.LOGIN_PATH,
    views.LOGOUT_PATH,
    views.PUBLISH_PATH,
)

_ATTESTED_VALUES = frozenset({"yes", "on", "true", "1"})


@dataclass(frozen=True)
class UploadedPhoto:
    """One uploaded file, already bounded by the adapter."""

    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class ShellResponse:
    status: int
    body: str = ""
    content_type: str = "text/html; charset=utf-8"
    location: str | None = None
    cookies: tuple[str, ...] = ()
    headers: tuple[tuple[str, str], ...] = ()


class MerchantShell:
    """One store's login, logout, management and publish pages."""

    def __init__(
        self,
        store: Store,
        auth: MerchantAuth,
        catalog_repository: CatalogRepository,
        publisher: MerchantPublisher,
        *,
        model_id: str,
        model_revision: str,
        dimensions: int = EMBEDDING_DIMENSIONS,
    ) -> None:
        self._store = store
        self._auth = auth
        self._catalog = catalog_repository
        self._publisher = publisher
        self._model_id = model_id
        self._model_revision = model_revision
        self._dimensions = dimensions

    def handles(self, path: str) -> bool:
        return path in HANDLED_PATHS

    def handle(
        self,
        *,
        method: str,
        path: str,
        cookies: Mapping[str, str],
        form: Mapping[str, str],
        query: Mapping[str, str] | None = None,
        files: Mapping[str, UploadedPhoto] | None = None,
    ) -> ShellResponse:
        if path == views.MANAGE_PATH:
            if method != "GET":
                return _method_not_allowed()
            return self._manage(cookies, query or {})
        if path == views.LOGIN_PATH:
            if method == "GET":
                return self._login_form(cookies)
            if method == "POST":
                return self._login(cookies, form)
            return _method_not_allowed()
        if path == views.LOGOUT_PATH:
            if method != "POST":
                return _method_not_allowed()
            return self._logout(cookies, form)
        if path == views.PUBLISH_PATH:
            if method != "POST":
                return _method_not_allowed()
            return self._publish(cookies, form, files or {})
        return ShellResponse(404, "Not found", content_type="text/plain; charset=utf-8")

    # -- routes --------------------------------------------------------------

    def _manage(self, cookies: Mapping[str, str], query: Mapping[str, str]) -> ShellResponse:
        session = self._auth.identify(cookies.get(MERCHANT_COOKIE))
        if session is None:
            # Same response whether the cookie is absent, foreign, expired or revoked.
            return _redirect(views.LOGIN_PATH, cookies=(clear_cookie_header(MERCHANT_COOKIE),))
        notice = ""
        published = query.get("published")
        if isinstance(published, str) and published:
            state = self._catalog.item_state(self._store.scope, published)
            if state is not None:
                notice = (
                    f"Those bytes are already published as {state.item_id}. Nothing changed."
                    if query.get("duplicate")
                    else f"Published {state.item_id}."
                )
        return self._manage_page(session, notice=notice)

    def _manage_page(
        self, session: MerchantSession, *, notice: str = "", error: str = "", status: int = 200
    ) -> ShellResponse:
        items = self._catalog.managed_items(
            self._store.scope,
            model_id=self._model_id,
            model_revision=self._model_revision,
            dimensions=self._dimensions,
        )
        return ShellResponse(
            status,
            views.manage_page(
                self._store, session.identity, items, session.csrf_token, notice=notice, error=error
            ),
        )

    def _publish(
        self,
        cookies: Mapping[str, str],
        form: Mapping[str, str],
        files: Mapping[str, UploadedPhoto],
    ) -> ShellResponse:
        session = self._auth.identify(cookies.get(MERCHANT_COOKIE))
        if session is None:
            return _redirect(views.LOGIN_PATH, cookies=(clear_cookie_header(MERCHANT_COOKIE),))
        if not csrf_matches(form.get("csrf_token"), session.csrf_token):
            return ShellResponse(
                400,
                views.message_page(self._store, "Publish", "This request could not be verified."),
            )
        photo = files.get("photo")
        if photo is None or not photo.data:
            return self._manage_page(session, error="Choose a photo to upload.", status=400)
        try:
            outcome = self._publisher.publish(
                merchant_id=session.identity.merchant_id,
                photo=photo.data,
                declared_content_type=photo.content_type,
                price=form.get("price"),
                title=form.get("title"),
                category=form.get("category"),
                attested_capture=(
                    str(form.get("attested_capture", "")).strip().lower() in _ATTESTED_VALUES
                ),
            )
        except (PublishError, UploadError, CatalogError) as error:
            return self._manage_page(session, error=str(error), status=400)
        location = f"{views.MANAGE_PATH}?published={quote(outcome.item_id, safe='')}"
        if outcome.duplicate:
            location += "&duplicate=1"
        return _redirect(location)

    def _login_form(self, cookies: Mapping[str, str]) -> ShellResponse:
        if self._auth.identify(cookies.get(MERCHANT_COOKIE)) is not None:
            return _redirect(views.MANAGE_PATH)
        token = secrets.token_urlsafe(CSRF_BYTES)
        return ShellResponse(
            200,
            views.login_page(self._store, token),
            cookies=(login_csrf_cookie_header(token),),
        )

    def _login(self, cookies: Mapping[str, str], form: Mapping[str, str]) -> ShellResponse:
        if not csrf_matches(form.get("csrf_token"), cookies.get(LOGIN_CSRF_COOKIE)):
            return ShellResponse(
                400,
                views.message_page(
                    self._store, "Sign in", "This sign-in form expired. Please try again."
                ),
                cookies=(clear_cookie_header(LOGIN_CSRF_COOKIE),),
            )
        outcome = self._auth.authenticate(
            str(form.get("username", "")), str(form.get("password", ""))
        )
        if outcome.identity is None:
            # Identical body for unknown username, wrong password and throttling.
            return ShellResponse(
                429 if outcome.throttled else 401,
                views.message_page(self._store, "Sign in", "Invalid username or password."),
                cookies=(clear_cookie_header(LOGIN_CSRF_COOKIE),),
                headers=(("Retry-After", str(int(outcome.retry_after_seconds) + 1)),)
                if outcome.throttled
                else (),
            )
        issued = self._auth.start_session(outcome.identity)
        return _redirect(
            views.MANAGE_PATH,
            cookies=(
                merchant_cookie_header(issued.token),
                clear_cookie_header(LOGIN_CSRF_COOKIE),
            ),
        )

    def _logout(self, cookies: Mapping[str, str], form: Mapping[str, str]) -> ShellResponse:
        raw_token = cookies.get(MERCHANT_COOKIE)
        session = self._auth.identify(raw_token)
        if session is None:
            return _redirect(views.LOGIN_PATH, cookies=(clear_cookie_header(MERCHANT_COOKIE),))
        if not csrf_matches(form.get("csrf_token"), session.csrf_token):
            return ShellResponse(
                400,
                views.message_page(self._store, "Sign out", "This request could not be verified."),
            )
        self._auth.revoke(raw_token)
        return _redirect(views.LOGIN_PATH, cookies=(clear_cookie_header(MERCHANT_COOKIE),))


def _redirect(location: str, *, cookies: tuple[str, ...] = ()) -> ShellResponse:
    return ShellResponse(
        303, "", content_type="text/plain; charset=utf-8", location=location, cookies=cookies
    )


def _method_not_allowed() -> ShellResponse:
    return ShellResponse(
        405,
        "Method not allowed",
        content_type="text/plain; charset=utf-8",
        headers=(("Allow", "GET, POST"),),
    )
