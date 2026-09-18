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

_STYLE = (
    "body{font-family:system-ui,sans-serif;margin:0;background:#faf7f2;color:#241f1a}"
    "header,main{max-width:56rem;margin:0 auto;padding:1rem}"
    "header{display:flex;justify-content:space-between;border-bottom:1px solid #e3dcd2}"
    "table{width:100%;border-collapse:collapse;margin:1rem 0}"
    "th,td{text-align:left;padding:.5rem;border-bottom:1px solid #e3dcd2;vertical-align:top}"
    "form{display:grid;gap:.75rem;max-width:22rem}"
    "label{display:grid;gap:.25rem}input,button{padding:.5rem;font:inherit}"
    ".note{color:#6b625a}code{word-break:break-all}"
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
    store: Store, identity: MerchantIdentity, items: Sequence[ManagedItem], csrf_token: str
) -> str:
    unknown_price = store.presentation.price_unknown_label
    rows = "".join(
        "<tr><td>{title}<br><small><code>{item_id}</code></small></td><td>{category}</td>"
        "<td>{price}</td><td>{listing}</td><td>{index}</td></tr>".format(
            title=escape(item.title),
            item_id=escape(item.item_id),
            category=escape(item.category),
            price=escape(f"{item.price:.2f}" if item.price is not None else unknown_price),
            listing=escape(item.listing_state.value),
            index=escape(item.index_state.value),
        )
        for item in items
    )
    return page(
        store,
        "Manage",
        f"""<h1>{escape(store.display_name)} inventory</h1>
<p class="note">Signed in as {escape(identity.username)}. This shell is read-only for now.</p>
<form method="post" action="{LOGOUT_PATH}"><input type="hidden" name="csrf_token" value="{escape(csrf_token)}"><button type="submit">Sign out</button></form>
<p class="note">{len(items)} items in this store's represented catalog.</p>
<table><thead><tr><th>Item</th><th>Category</th><th>Price</th><th>Listing state</th><th>Index state</th></tr></thead><tbody>{rows}</tbody></table>""",
    )
