"""One-time aggregate-only read of 214 historic records lacking an official URL.

No source address, name, company, domain or payload ever leaves runner memory.
Deletes after grounded results. No mutation and no messaging.
"""
import collections
import ipaddress
import json
import os
import re
import sys
import requests
from dedupe_preflight import normalize_domain, normalize_company, normalize_email

LIST_ID = "24deb187-59e0-43b5-86b8-fe37a7b21e2a"
URL = "https://api.instantly.ai/api/v2/leads/list"
FREE = {
    "gmail.com","googlemail.com","outlook.com","outlook.nl","hotmail.com",
    "hotmail.nl","live.com","live.nl","msn.com","msn.nl","yahoo.com",
    "yahoo.co.uk","yahoo.nl","ymail.com","aol.com","icloud.com","me.com",
    "mac.com","proton.me","protonmail.com","pm.me","tuta.com","tutanota.com",
    "gmx.com","gmx.de","mail.com","fastmail.com","fastmail.fm","yandex.com",
    "mail.ru","qq.com","163.com","ziggo.nl","upcmail.nl","chello.nl",
    "casema.nl","kpnmail.nl","kpnplanet.nl","hetnet.nl","planet.nl","xs4all.nl",
    "home.nl","tele2.nl","online.nl","freeler.nl","wanadoo.nl","orange.nl",
    "wixsite.com","wordpress.com","myshopify.com","weebly.com","sendgrid.net",
    "mailchimp.com","mailgun.org","amazonaws.com","brevo.com",
}
UUID = re.compile(r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")
HOST = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")


def official(item):
    p=item.get("payload")
    if not isinstance(p,dict):
        p=item.get("custom_variables")
    if not isinstance(p,dict):
        return ""
    for prefix in ("leadscanner_site_refresh_","leadscanner_site_candidate_"):
        if str(p.get(prefix+"source_type") or "") != "official_site":
            continue
        domain=normalize_domain(p.get(prefix+"official_domain"))
        evidence=normalize_domain(p.get(prefix+"evidence_url"))
        if domain and evidence==domain and "." in domain and domain not in {"com","org","nl"}:
            return domain
    return ""


def source():
    api=os.getenv("INSTANTLY_API_KEY","").strip()
    if not api:
        raise RuntimeError("source_credentials_missing")
    records=[];ids=set();emails=set();cursors=set();cursor=""
    with requests.Session() as sess:
        for _ in range(25):
            params={"list_id":LIST_ID,"limit":100}
            if cursor:params["starting_after"]=cursor
            r=sess.post(URL,json=params,headers={"Authorization":"Bearer "+api,"Accept":"application/json"},timeout=30)
            if r.status_code!=200:raise RuntimeError("source_read_failed")
            res=r.json()
            if not isinstance(res,dict) or not isinstance(res.get("items"),list):
                raise RuntimeError("source_page_invalid")
            for item in res["items"]:
                if not isinstance(item,dict) or item.get("list_id")!=LIST_ID:
                    raise RuntimeError("source_identity_invalid")
                identity=str(item.get("id") or "").lower().strip()
                email=normalize_email(item.get("email"))
                if not UUID.fullmatch(identity) or email.count("@")!=1 or identity in ids or email in emails:
                    raise RuntimeError("source_duplicate_or_invalid")
                ids.add(identity);emails.add(email);records.append(item)
            next_cursor=str(res.get("next_starting_after") or "").strip()
            if not next_cursor:break
            if next_cursor in cursors or next_cursor==cursor or not res["items"]:
                raise RuntimeError("source_pagination_invalid")
            cursor=next_cursor;cursors.add(cursor)
        else:raise RuntimeError("source_unbounded")
    if len(records)!=1128:raise RuntimeError("source_count_changed")
    return records


def candidate_domain(email):
    domain=normalize_domain(email.split("@",1)[-1])
    if not domain or not HOST.fullmatch(domain) or "." not in domain:
        return ""
    try: ipaddress.ip_address(domain);return ""
    except ValueError: pass
    if domain in FREE or any(domain.endswith("."+shared) for shared in FREE):
        return ""
    if len(domain)>253 or any(not part or len(part)>63 for part in domain.split(".")):
        return ""
    return domain


def run():
    records=source()
    missing=[v for v in records if not official(v)]
    if len(missing)!=214:raise RuntimeError("official_domain_baseline_changed")
    counts=collections.Counter()
    group=collections.defaultdict(set)
    examples={}
    for item in missing:
        email=normalize_email(item.get("email"))
        domain=candidate_domain(email)
        company=normalize_company(item.get("companyName") or item.get("company") or "")
        payload=item.get("payload") if isinstance(item.get("payload"),dict) else {}
        if domain:
            counts["nonshared_email_domain"]+=1
            group[domain].add(company or "-unknown-")
            examples.setdefault(domain,[]).append(item)
        else:
            counts["consumer_or_unverified_mail_provider"]+=1
        counts["top_level_company_present"]+=bool(company)
        counts["top_level_website_present"]+=bool(str(item.get("website") or "").strip())
        counts["top_level_company_site_pair"]+=bool(company and str(item.get("website") or "").strip())
        counts["source_payload_with_any_candidate_site"]+=any(
            str(payload.get(k) or "").strip() for k in (
                "leadscanner_site_candidate_official_domain",
                "leadscanner_site_refresh_official_domain",
                "leadscanner_site_candidate_evidence_url",
                "leadscanner_site_refresh_evidence_url",
            )
        )
    ambiguous={d for d,companies in group.items() if len({n for n in companies if n!="-unknown-"})>1}
    counts["ambiguous_custom_domains"]=sum(len(examples[d]) for d in ambiguous)
    counts["custom_domains_not_shared_by_different_named_companies"]=sum(
        len(examples[d]) for d in group if d not in ambiguous
    )
    return {
        "source_total":len(records),
        "official_domain_verified":len(records)-len(missing),
        "missing_official_domain":len(missing),
        "nonshared_custom_mail_domain_candidates":counts["nonshared_email_domain"],
        "consumer_or_unverified_mail_provider":counts["consumer_or_unverified_mail_provider"],
        "ambiguous_custom_mail_domain_records":counts["ambiguous_custom_domains"],
        "eligible_conservative_email_domain_records":counts["custom_domains_not_shared_by_different_named_companies"],
        "top_level_company_present":counts["top_level_company_present"],
        "top_level_website_present":counts["top_level_website_present"],
        "top_level_company_site_pair":counts["top_level_company_site_pair"],
        "source_payload_with_any_candidate_site":counts["source_payload_with_any_candidate_site"],
        "emails_sent":0,
        "provider_mutation":False,
        "registry_mutation":False,
        "raw_identity_output":False,
    }


if __name__=="__main__":
    try: result=run()
    except Exception:
        print("MISSING_DOMAIN_PROFILE=failed private_source_details_suppressed")
        sys.exit(1)
    print("MISSING_DOMAIN_PROFILE=green "+json.dumps(result,sort_keys=True))
