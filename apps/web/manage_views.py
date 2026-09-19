"""Minimal server-rendered pages for the merchant shell and item controls.

Branding comes from the store record; no item content is rendered for a request that
is not authenticated as that store's merchant. The item page carries the S8
amend/hide/sold/replace controls. A demo store stays read-only unless the explicit
interactive local-demo capability is active, and even then only this merchant's own
uploaded items are editable: committed museum records are not.
"""

from __future__ import annotations

from html import escape
from typing import Sequence
from urllib.parse import quote

from backend.catalog.store_repository import ManagedItem
from contracts.auth import MerchantIdentity
from contracts.catalog import IndexState, ListingState
from contracts.store import Store

LOGIN_PATH = "/manage/login"
MANAGE_PATH = "/manage"
LOGOUT_PATH = "/manage/logout"
PUBLISH_PATH = "/manage/publish"
ITEM_PATH = "/manage/items"

# The explicit listing controls the item page offers, keyed by the item's state.
LISTING_CONTROLS: dict[ListingState, tuple[tuple[str, str], ...]] = {
    ListingState.PUBLISHED: (("hide", "Hide"), ("sold", "Mark sold")),
    ListingState.HIDDEN: (("unhide", "Unhide"),),
    ListingState.SOLD: (("relist", "Relist"),),
    ListingState.DRAFT: (),
}

NOTICE_MESSAGES = {
    "saved": "Saved changes.",
    "unchanged": "Nothing changed.",
    "hidden": "Item hidden.",
    "unhidden": "Item is visible again.",
    "sold": "Item marked sold.",
    "relisted": "Item relisted.",
    "replaced": "Photo replaced; the old description search entry is cleared.",
    "searchable": "This item is searchable by description now.",
}

INDEX_FAILED_NOTICE = (
    "The description index could not be built. The item stays published and browsable."
)

_STYLE = (
    "*,*::before,*::after{box-sizing:border-box}"
    "body{font-family:system-ui,sans-serif;margin:0;background:#faf7f2;color:#241f1a}"
    "header,main{max-width:56rem;margin:0 auto;padding:1rem}"
    "header{display:flex;justify-content:space-between;border-bottom:1px solid #e3dcd2}"
    "table{width:100%;border-collapse:collapse;margin:1rem 0}"
    "th,td{text-align:left;padding:.5rem;border-bottom:1px solid #e3dcd2;vertical-align:top}"
    "form{display:grid;gap:.75rem;max-width:22rem}"
    "label{display:grid;gap:.25rem}"
    "input,button,select{font:inherit;font-size:1rem;width:100%;max-width:100%;padding:.5rem}"
    "input[type=checkbox]{width:auto}"
    ".check{display:flex;align-items:flex-start;gap:.5rem;max-width:22rem}"
    ".note{color:#6b625a}code{word-break:break-all}"
    ".table-wrap{overflow-x:auto}.error{color:#8a2b2b;font-weight:600}"
    ".ok{color:#24602a;font-weight:600}"
)


def page(store: Store, title: str, body: str) -> str:
    presentation = store.presentation
    wordmark = (
        f"{escape(presentation.wordmark_primary)} "
        f"{escape(presentation.wordmark_accent)} "
        f"{escape(presentation.wordmark_suffix)}"
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} · {escape(store.display_name)}</title><style>{_STYLE}</style></head><body><header><strong>{wordmark}</strong><span>{escape(store.display_name)}</span></header><main>{body}</main></body></html>"""


def login_page(
    store: Store, csrf_token: str, *, demo_credentials: tuple[str, str] | None = None
) -> str:
    """Sign-in page; the local demo credential appears only under the demo capability."""

    demo_note = (
        '<p class="note">Local demonstration credential: '
        f"<code>{escape(demo_credentials[0])}</code> / "
        f"<code>{escape(demo_credentials[1])}</code></p>"
        if demo_credentials is not None
        else ""
    )
    return page(
        store,
        "Sign in",
        f"""<h1>Sign in</h1><p class="note">Merchant access for {escape(store.display_name)}.</p>
{demo_note}
<form method="post" action="{LOGIN_PATH}"><input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
<label>Username <input name="username" autocomplete="username" maxlength="64" required></label>
<label>Password <input type="password" name="password" autocomplete="current-password" required></label>
<button type="submit">Sign in</button></form>""",
    )


def message_page(store: Store, title: str, message: str) -> str:
    return page(
        store,
        title,
        f'<h1>{escape(title)}</h1><p>{escape(message)}</p><p><a href="{LOGIN_PATH}">Back to sign in</a></p>',
    )


def not_found_page(store: Store, message: str) -> str:
    """A non-disclosing page for an unknown or foreign item."""

    return page(
        store,
        "Not found",
        f'<h1>Not found</h1><p>{escape(message)}</p><p><a href="{MANAGE_PATH}">Back to inventory</a></p>',
    )


def manage_page(
    store: Store,
    identity: MerchantIdentity,
    items: Sequence[ManagedItem],
    csrf_token: str,
    *,
    notice: str = "",
    error: str = "",
    interactive_demo: bool = False,
    published_item_id: str | None = None,
) -> str:
    unknown_price = store.presentation.price_unknown_label
    editable = interactive_demo or not store.is_demo
    rows = "".join(
        "<tr><td>{title}<br><small><code>{item_id}</code></small></td><td>{category}</td>"
        "<td>{price}</td><td>{listing}</td><td>{index}</td>{origin}{actions}</tr>".format(
            title=_item_link(store, item),
            item_id=escape(item.item_id),
            category=escape(item.category),
            price=escape(f"{item.price:.2f}" if item.price is not None else unknown_price),
            listing=escape(item.listing_state.value),
            index=escape(item.index_state.value),
            origin=f"<td>{escape(_origin_label(item))}</td>" if interactive_demo else "",
            actions=(
                f'<td><a href="{item_path(item.item_id)}">Edit</a></td>'
                if _item_is_manageable(item, editable=editable, interactive_demo=interactive_demo)
                else ""
            ),
        )
        for item in items
    )
    actions_head = "<th>Manage</th>" if editable else ""
    origin_head = "<th>Origin</th>" if interactive_demo else ""
    publish_block = (
        f"""<section><h2>Add an item</h2>
{"<p class='error' role='alert'>" + escape(error) + "</p>" if error else ""}
<form method="post" action="{PUBLISH_PATH}" enctype="multipart/form-data">
<input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
<label>Photo <input type="file" name="photo" accept="image/*" capture="environment" required></label>
<label>Price (optional) <input name="price" inputmode="decimal" autocomplete="off" placeholder="24.00"></label>
<label>Title (optional) <input name="title" maxlength="120"></label>
<label>Category (optional) <input name="category" maxlength="60"></label>
<label class="check"><input type="checkbox" name="attested_capture" value="yes"> I just took this photo</label>
<button type="submit">Publish</button></form></section>"""
        if interactive_demo or not store.is_demo
        else '<p class="note">This storefront is an illustrative demo, so it has no publish form.</p>'
    )
    status = ""
    if notice:
        status = f'<p class="ok" role="status">{escape(notice)}</p>'
    if interactive_demo and published_item_id:
        status += _published_notice(published_item_id, csrf_token)
    return page(
        store,
        "Manage",
        f"""<h1>{escape(store.display_name)} inventory</h1>
<p class="note">Signed in as {escape(identity.username)}.</p>
<form method="post" action="{LOGOUT_PATH}"><input type="hidden" name="csrf_token" value="{escape(csrf_token)}"><button type="submit">Sign out</button></form>
{status}
<p class="note">{len(items)} items in this store's represented catalog.</p>
{publish_block}
<div class="table-wrap"><table><thead><tr><th>Item</th><th>Category</th><th>Price</th><th>Listing state</th><th>Index state</th>{origin_head}{actions_head}</tr></thead><tbody>{rows}</tbody></table></div>""",
    )


def _published_notice(item_id: str, csrf_token: str) -> str:
    """Post-publication confirmation: open the storefront item or index on demand."""

    target = item_path(item_id)
    return f"""<section class="published"><h2>Published</h2>
<p>It is in the storefront now. It appears in description search only after it is indexed.</p>
<p><a href="/items/{escape(item_id)}">View in storefront</a></p>
<form method="post" action="{target}/index"><input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
<button type="submit">Make searchable now</button></form></section>"""


def _item_is_manageable(item: ManagedItem, *, editable: bool, interactive_demo: bool) -> bool:
    """Only a merchant's own uploaded item is editable inside the interactive demo."""

    if not editable:
        return False
    return item.merchant_upload if interactive_demo else True


def _origin_label(item: ManagedItem) -> str:
    return "Your local upload" if item.merchant_upload else "Museum collection (read-only)"


def item_page(
    store: Store,
    identity: MerchantIdentity,
    item: ManagedItem,
    csrf_token: str,
    *,
    notice: str = "",
    error: str = "",
    interactive_demo: bool = False,
) -> str:
    """One item's S8 controls: amend, hide/unhide, sold/relist, replace photo.

    Inside the interactive local demo these exist only for the merchant's own uploaded
    items. A committed museum record renders a read-only page there, exactly as a demo
    store does in every other composition.
    """

    unknown_price = store.presentation.price_unknown_label
    price_value = "" if item.price is None else f"{item.price:.2f}"
    status = ""
    if notice:
        status = f'<p class="ok" role="status">{escape(notice)}</p>'
    if error:
        status += f'<p class="error" role="alert">{escape(error)}</p>'
    base = item_path(item.item_id)
    summary = (
        f"<p class='note'><code>{escape(item.item_id)}</code> · "
        f"{escape(item.listing_state.value)} · index {escape(item.index_state.value)} · "
        f"{escape(unknown_price if item.price is None else price_value)}</p>"
    )
    if store.is_demo and not (interactive_demo and item.merchant_upload):
        note = (
            "This committed museum object is part of the read-only demo collection."
            if interactive_demo
            else "This storefront is an illustrative demo and cannot be edited."
        )
        return page(
            store,
            "Item",
            f"<h1>{escape(item.title)}</h1>{summary}"
            f'<p class="note">{escape(note)}</p>'
            f'<p><a href="{MANAGE_PATH}">Back to inventory</a></p>',
        )
    controls = "".join(
        f'<button type="submit" name="action" value="{escape(action)}">{escape(label)}</button>'
        for action, label in LISTING_CONTROLS[item.listing_state]
    )
    listing_block = (
        f"""<section><h2>Listing</h2>
<form method="post" action="{base}/listing">
<input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
{controls}</form></section>"""
        if controls
        else ""
    )
    index_block = _index_block(item, base, csrf_token) if interactive_demo else ""
    return page(
        store,
        item.title,
        f"""<h1>{escape(item.title)}</h1>
{summary}
{status}
<p class="note">Signed in as {escape(identity.username)}.</p>
{index_block}
<section><h2>Edit details</h2>
<form method="post" action="{base}/edit">
<input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
<label>Title <input name="title" maxlength="120" value="{escape(item.title)}"></label>
<label>Category <input name="category" maxlength="60" value="{escape(item.category)}"></label>
<label>Price <input name="price" inputmode="decimal" autocomplete="off" value="{escape(price_value)}" placeholder="Leave blank if unknown"></label>
<button type="submit">Save changes</button></form></section>
{listing_block}
<section><h2>Replace photo</h2>
<form method="post" action="{base}/replace" enctype="multipart/form-data">
<input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
<label>New photo <input type="file" name="photo" accept="image/*" capture="environment" required></label>
<label class="check"><input type="checkbox" name="attested_capture" value="yes"> I just took this photo</label>
<button type="submit">Replace photo</button></form></section>
<p><a href="{MANAGE_PATH}">Back to inventory</a></p>""",
    )


def _index_block(item: ManagedItem, base: str, csrf_token: str) -> str:
    """The interactive demo's explicit, separate indexing action."""

    if item.index_state is IndexState.READY:
        detail = "This item already has a valid description embedding."
    elif item.index_state is IndexState.FAILED:
        detail = (
            "The last indexing attempt failed, so the item is not searchable by "
            f"description. It stays published and browsable. {item.index_error or ''}"
        )
    else:
        detail = (
            "Uploaded items are browsable immediately, but description search uses a "
            "separate embedding step."
        )
    return f"""<section><h2>Description search</h2>
<p class="note">Index state: {escape(item.index_state.value)}. {escape(detail.strip())}</p>
<form method="post" action="{base}/index"><input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
<button type="submit">Make searchable now</button></form></section>"""


def item_path(item_id: str) -> str:
    return f"{ITEM_PATH}/{quote(item_id, safe='')}"


def _item_link(store: Store, item: ManagedItem) -> str:
    title = escape(item.title)
    if item.listing_state.value != "published":
        return title
    return f'<a href="/items/{escape(item.item_id)}">{title}</a>'
