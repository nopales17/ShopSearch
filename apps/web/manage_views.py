"""Minimal server-rendered pages for the read-only merchant shell (S6).

Branding comes from the store record; no item content is rendered for a request that
is not authenticated as that store's merchant.
"""

from __future__ import annotations

from html import escape
from typing import Sequence

from backend.catalog.store_repository import ManagedItem
from contracts.auth import MerchantIdentity
from contracts.store import Store

LOGIN_PATH = "/manage/login"
MANAGE_PATH = "/manage"
LOGOUT_PATH = "/manage/logout"
PUBLISH_PATH = "/manage/publish"

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


def login_page(store: Store, csrf_token: str) -> str:
    return page(
        store,
        "Sign in",
        f"""<h1>Sign in</h1><p class="note">Merchant access for {escape(store.display_name)}.</p>
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


def manage_page(
    store: Store,
    identity: MerchantIdentity,
    items: Sequence[ManagedItem],
    csrf_token: str,
    *,
    notice: str = "",
    error: str = "",
) -> str:
    unknown_price = store.presentation.price_unknown_label
    rows = "".join(
        "<tr><td>{title}<br><small><code>{item_id}</code></small></td><td>{category}</td>"
        "<td>{price}</td><td>{listing}</td><td>{index}</td></tr>".format(
            title=_item_link(store, item),
            item_id=escape(item.item_id),
            category=escape(item.category),
            price=escape(f"{item.price:.2f}" if item.price is not None else unknown_price),
            listing=escape(item.listing_state.value),
            index=escape(item.index_state.value),
        )
        for item in items
    )
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
        if not store.is_demo
        else '<p class="note">This storefront is an illustrative demo, so it has no publish form.</p>'
    )
    status = ""
    if notice:
        status = f'<p class="ok" role="status">{escape(notice)}</p>'
    return page(
        store,
        "Manage",
        f"""<h1>{escape(store.display_name)} inventory</h1>
<p class="note">Signed in as {escape(identity.username)}.</p>
<form method="post" action="{LOGOUT_PATH}"><input type="hidden" name="csrf_token" value="{escape(csrf_token)}"><button type="submit">Sign out</button></form>
{status}
<p class="note">{len(items)} items in this store's represented catalog.</p>
{publish_block}
<div class="table-wrap"><table><thead><tr><th>Item</th><th>Category</th><th>Price</th><th>Listing state</th><th>Index state</th></tr></thead><tbody>{rows}</tbody></table></div>""",
    )


def _item_link(store: Store, item: ManagedItem) -> str:
    title = escape(item.title)
    if item.listing_state.value != "published":
        return title
    return f'<a href="/items/{escape(item.item_id)}">{title}</a>'
