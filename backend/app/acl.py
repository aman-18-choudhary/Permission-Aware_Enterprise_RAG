"""Access-control principals.

Every document carries an ACL: a list of principal strings. A user may see a
document iff the user's principal set intersects the document's ACL.

    user:<email>     a specific person
    group:<email>    a group (membership is admin-managed, see User.groups)
    domain:<domain>  everyone in a Google Workspace domain
    tenant:all       every signed-in user of this deployment
"""
from .models import User

TENANT_ALL = "tenant:all"


def user_principal(email: str) -> str:
    return f"user:{email.strip().lower()}"


def principals_for(user: User) -> list[str]:
    p = {user_principal(user.email), TENANT_ALL}
    if user.domain:
        p.add(f"domain:{user.domain.lower()}")
    for g in user.groups or []:
        p.add(f"group:{g.strip().lower()}")
    return sorted(p)


def drive_acl(permissions: list[dict] | None, owners: list[dict] | None, syncing_user_email: str) -> list[str]:
    """Translate a Drive file's sharing permissions into principals.

    Fails closed: if Drive did not return permissions (the syncing user can't
    see the sharing list), only the syncing user is allowed.
    """
    acl: set[str] = set()
    for o in owners or []:
        if o.get("emailAddress"):
            acl.add(user_principal(o["emailAddress"]))
    for perm in permissions or []:
        ptype = perm.get("type")
        if ptype == "user" and perm.get("emailAddress"):
            acl.add(user_principal(perm["emailAddress"]))
        elif ptype == "group" and perm.get("emailAddress"):
            acl.add(f"group:{perm['emailAddress'].strip().lower()}")
        elif ptype == "domain" and perm.get("domain"):
            acl.add(f"domain:{perm['domain'].strip().lower()}")
        elif ptype == "anyone" and perm.get("allowFileDiscovery"):
            acl.add(TENANT_ALL)
        # "anyone with the link" (not discoverable) is deliberately NOT indexed as public.
    if not permissions:
        acl.add(user_principal(syncing_user_email))
    return sorted(acl)
