"""Render an explicit owned-local-only GoBGP policy without opening ingress."""
import re
import tomllib


def owned_local_config(text, owner, enable_peers=False):
    config=tomllib.loads(text)
    if any(c['large-community-set-name']=='HEMLOCK-OWNED' for c in config.get('defined-sets',{}).get('bgp-defined-sets',{}).get('large-community-sets',[])):
        raise ValueError('Owned policy already exists; inspect rather than duplicate it')
    marker=':'.join(map(str,owner))
    # A quoted literal community matches the dedicated ownership namespace.
    policy=f'''
[[defined-sets.bgp-defined-sets.large-community-sets]]
large-community-set-name = "HEMLOCK-OWNED"
large-community-list = ["{marker}"]
[[policy-definitions]]
name = "HEMLOCK-OWNED-LOCAL"
[[policy-definitions.statements]]
[policy-definitions.statements.conditions.bgp-conditions]
route-type = "local"
[policy-definitions.statements.conditions.bgp-conditions.match-large-community-set]
large-community-set = "HEMLOCK-OWNED"
match-set-options = "any"
[policy-definitions.statements.actions]
route-disposition = "accept-route"
'''
    text=text.replace('export-policy-list = ["HEMLOCK-DENY-ALL"]','export-policy-list = ["HEMLOCK-OWNED-LOCAL"]')
    # Global import also processes AddPath; allow local owned paths there only.
    text,count=re.subn(r'(\[global.apply-policy.config\]\s*\n)import-policy-list = \["HEMLOCK-DENY-ALL"\]',r'\1import-policy-list = ["HEMLOCK-OWNED-LOCAL"]',text)
    if count != 1:
        raise ValueError('Expected the explicit global deny policy')
    if enable_peers:
        text=text.replace('admin-down = true','admin-down = false')
    text+='\n'+policy
    parsed=tomllib.loads(text)
    assert parsed['global']['apply-policy']['config']['default-import-policy']=='reject-route'
    assert parsed['global']['apply-policy']['config']['default-export-policy']=='reject-route'
    return text
