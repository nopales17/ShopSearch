"""Merchant shell: sign in, sign out, `/manage` and merchant catalog mutations.

The store is resolved from the hostname before this shell runs, and every session
lookup is scoped to that store, so a session from another store yields no identity.
State-changing requests carry a CSRF token; login failures are generic; publication
and the S8 amendments accept no store or merchant identifier from the form.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Callable, Mapping
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
from backend.catalog.store_repository import (
    CatalogError,
    CatalogNotFoundError,
    CatalogRepository,
    ManagedItem,
)
from backend.media.uploads import UploadError
from backend.search.indexer import IndexRunReport
from backend.search.vector_source import EMBEDDING_DIMENSIONS
from contracts.auth import MerchantSession
from contracts.catalog import IndexState
from contracts.store import Store, StoreScope

HANDLED_PATHS = (
    views.MANAGE_PATH,
    views.LOGIN_PATH,
    views.LOGOUT_PATH,
    views.PUBLISH_PATH,
)

_ATTESTED_VALUES = frozenset({"yes", "on", "true", "1"})
_ITEM_ACTIONS = frozenset({"edit", "listing", "replace"})
_INDEX_ACTION = "index"
_LISTING_NOTICES = {
    "hide": "hidden",
    "unhide": "unhidden",
    "sold": "sold",
    "relist": "relisted",
}


@dataclass(frozen=True)
class InteractiveDemo:
    """The explicit local-demo capability: sign-in credential and in-memory mutation.

    Constructed only by `apps.web.demo` and passed only into this process's merchant
    composition. It is never persisted, never carried on the store record, never
    enabled by an environment variable, and never derived from `Store.is_demo`,
    hostname, database contents or the existence of a merchant account. Generic
    composition passes nothing, so Form & Field is read-only there.
    """

    username: str
    password: str

    @property
    def credentials(self) -> tuple[str, str]:
        return self.username, self.password


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
        interactive_demo: InteractiveDemo | None = None,
        index_store: Callable[[StoreScope], IndexRunReport] | None = None,
    ) -> None:
        self._store = store
        self._auth = auth
        self._catalog = catalog_repository
        self._publisher = publisher
        self._model_id = model_id
        self._model_revision = model_revision
        self._dimensions = dimensions
        self._interactive_demo = interactive_demo
        self._index_store = index_store

    def handles(self, path: str) -> bool:
        return path in HANDLED_PATHS or path.startswith(f"{views.ITEM_PATH}/")

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
        if path.startswith(f"{views.ITEM_PATH}/"):
            return self._item_route(method, path, cookies, form, files or {}, query or {})
        return ShellResponse(404, "Not found", content_type="text/plain; charset=utf-8")

    # -- routes --------------------------------------------------------------

    def _manage(self, cookies: Mapping[str, str], query: Mapping[str, str]) -> ShellResponse:
        session = self._auth.identify(cookies.get(MERCHANT_COOKIE))
        if session is None:
            # Same response whether the cookie is absent, foreign, expired or revoked.
            return _redirect(views.LOGIN_PATH, cookies=(clear_cookie_header(MERCHANT_COOKIE),))
        notice = ""
        published_item_id: str | None = None
        published = query.get("published")
        if isinstance(published, str) and published:
            state = self._catalog.item_state(self._store.scope, published)
            if state is not None:
                published_item_id = state.item_id
                notice = (
                    f"Those bytes are already published as {state.item_id}. Nothing changed."
                    if query.get("duplicate")
                    else f"Published {state.item_id}."
                )
        return self._manage_page(session, notice=notice, published_item_id=published_item_id)

    def _manage_page(
        self,
        session: MerchantSession,
        *,
        notice: str = "",
        error: str = "",
        status: int = 200,
        published_item_id: str | None = None,
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
                self._store,
                session.identity,
                items,
                session.csrf_token,
                notice=notice,
                error=error,
                interactive_demo=self._interactive_demo is not None,
                published_item_id=published_item_id,
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

    # -- S8 item management --------------------------------------------------

    def _item_route(
        self,
        method: str,
        path: str,
        cookies: Mapping[str, str],
        form: Mapping[str, str],
        files: Mapping[str, UploadedPhoto],
        query: Mapping[str, str],
    ) -> ShellResponse:
        remainder = path[len(views.ITEM_PATH) + 1 :]
        parts = remainder.split("/")
        if len(parts) == 1 and parts[0]:
            item_id, action = parts[0], "view"
        elif (
            len(parts) == 2
            and parts[0]
            and (parts[1] in _ITEM_ACTIONS or parts[1] == _INDEX_ACTION)
        ):
            item_id, action = parts[0], parts[1]
        else:
            return ShellResponse(404, "Not found", content_type="text/plain; charset=utf-8")
        session = self._auth.identify(cookies.get(MERCHANT_COOKIE))
        if session is None:
            return _redirect(views.LOGIN_PATH, cookies=(clear_cookie_header(MERCHANT_COOKIE),))
        item = self._catalog.managed_item(
            self._store.scope,
            item_id,
            model_id=self._model_id,
            model_revision=self._model_revision,
            dimensions=self._dimensions,
        )
        if action == "view":
            if method != "GET":
                return _method_not_allowed()
            if item is None:
                return self._item_not_found()
            notice = views.NOTICE_MESSAGES.get(str(query.get("updated", "")), "")
            return self._item_page(session, item, notice=notice)
        if method != "POST":
            return _method_not_allowed()
        # A foreign or unknown item gets the same non-disclosing response as a
        # missing one, whatever the CSRF state, and mutates nothing.
        if item is None:
            return self._item_not_found()
        if not csrf_matches(form.get("csrf_token"), session.csrf_token):
            return ShellResponse(
                400,
                views.message_page(self._store, "Item", "This request could not be verified."),
            )
        if action == _INDEX_ACTION:
            return self._index_item(session, item)
        return self._item_mutation(session, item, action, form, files)

    def _index_item(self, session: MerchantSession, item: ManagedItem) -> ShellResponse:
        """Interactive-demo-only explicit indexing; never part of generic composition.

        The action is deliberately separate from publication so the demo shows the real
        contract: publish is immediately browsable, and description search begins only
        after a valid embedding exists. A failure changes no listing state and never
        rolls the publication back.
        """

        if self._interactive_demo is None or self._index_store is None or not item.merchant_upload:
            return ShellResponse(404, "Not found", content_type="text/plain; charset=utf-8")
        try:
            self._index_store(self._store.scope)
        except Exception as error:  # An indexing failure is reported, never raised on.
            return self._item_page(
                session,
                item,
                error=f"{views.INDEX_FAILED_NOTICE} ({type(error).__name__})",
            )
        refreshed = self._managed_item(item.item_id) or item
        if refreshed.index_state is IndexState.READY:
            return _redirect(
                f"{views.item_path(item.item_id)}?updated={quote('searchable', safe='')}"
            )
        return self._item_page(session, refreshed, error=views.INDEX_FAILED_NOTICE)

    def _managed_item(self, item_id: str) -> ManagedItem | None:
        return self._catalog.managed_item(
            self._store.scope,
            item_id,
            model_id=self._model_id,
            model_revision=self._model_revision,
            dimensions=self._dimensions,
        )

    def _item_mutation(
        self,
        session: MerchantSession,
        item: ManagedItem,
        action: str,
        form: Mapping[str, str],
        files: Mapping[str, UploadedPhoto],
    ) -> ShellResponse:
        merchant_id = session.identity.merchant_id
        try:
            if action == "edit":
                outcome = self._publisher.edit_item(
                    merchant_id=merchant_id,
                    item_id=item.item_id,
                    title=form.get("title"),
                    category=form.get("category"),
                    price=form.get("price"),
                )
                notice = "saved" if outcome.changed else "unchanged"
            elif action == "listing":
                action_name = str(form.get("action", ""))
                outcome = self._publisher.transition_listing(
                    merchant_id=merchant_id, item_id=item.item_id, action=action_name
                )
                notice = (
                    _LISTING_NOTICES.get(action_name, "unchanged")
                    if outcome.changed
                    else "unchanged"
                )
            else:
                photo = files.get("photo")
                if photo is None or not photo.data:
                    return self._item_page(
                        session, item, error="Choose a photo to upload.", status=400
                    )
                replacement = self._publisher.replace_image(
                    merchant_id=merchant_id,
                    item_id=item.item_id,
                    photo=photo.data,
                    declared_content_type=photo.content_type,
                    attested_capture=(
                        str(form.get("attested_capture", "")).strip().lower() in _ATTESTED_VALUES
                    ),
                )
                notice = "replaced" if replacement.changed else "unchanged"
        except CatalogNotFoundError:
            return self._item_not_found()
        except (PublishError, UploadError, CatalogError) as error:
            return self._item_page(session, item, error=str(error), status=400)
        return _redirect(f"{views.item_path(item.item_id)}?updated={quote(notice, safe='')}")

    def _item_page(
        self,
        session: MerchantSession,
        item: ManagedItem,
        *,
        notice: str = "",
        error: str = "",
        status: int = 200,
    ) -> ShellResponse:
        return ShellResponse(
            status,
            views.item_page(
                self._store,
                session.identity,
                item,
                session.csrf_token,
                notice=notice,
                error=error,
                interactive_demo=self._interactive_demo is not None,
            ),
        )

    def _item_not_found(self) -> ShellResponse:
        """One response for an unknown item and for another store's item."""

        return ShellResponse(
            404,
            views.not_found_page(self._store, "That item is not in this store."),
        )

    def _login_form(self, cookies: Mapping[str, str]) -> ShellResponse:
        if self._auth.identify(cookies.get(MERCHANT_COOKIE)) is not None:
            return _redirect(views.MANAGE_PATH)
        token = secrets.token_urlsafe(CSRF_BYTES)
        return ShellResponse(
            200,
            views.login_page(
                self._store,
                token,
                demo_credentials=(
                    self._interactive_demo.credentials
                    if self._interactive_demo is not None
                    else None
                ),
            ),
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
