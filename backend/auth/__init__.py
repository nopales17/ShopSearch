"""Founder-provisioned merchant authentication for the store-scoped platform.

`MerchantRepository` owns the SQL for `merchants`/`merchant_sessions`; `MerchantAuth`
is the per-store service used by the founder CLI and the management shell. Session
tokens and passwords are never stored in the clear (ADR-0005 §4).
"""
