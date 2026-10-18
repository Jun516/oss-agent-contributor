"""Credentialed unattended publication after verified independent replay.

This step never executes project code and does not share credentials with code/test jobs.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .core import Blocked, POLICY, api, checkout, current_candidate_ok, load_candidate, publication_plan, repo_path, run, safe_paths


def check_policy() -> None:
    """The owner has explicitly opted into unattended publication.

    Only this separately credentialed publish job may mutate GitHub.
    It never runs code from the upstream project.
    """
    if POLICY.get("publication_policy") != "preauthorized":
        raise Blocked("Autonomous publishing has not been authorized by controller policy")
    if POLICY.get("owner") != "Jun516":
        raise Blocked("Controller GitHub owner is not authorized")
    if not os.getenv("GH_TOKEN"):
        raise Blocked("OSS_BOT_TOKEN / GH_TOKEN is missing")
    if not shutil.which("gh"):
        raise Blocked("GitHub CLI unavailable in publishing job")
    who = run(["gh", "api", "user", "--jq", ".login"], Path.cwd(), 35).stdout.strip()
    if who.lower() != POLICY["owner"].lower():
        raise Blocked("Publishing token identity does not match Jun516")


def publication_rate_ok() -> None:
    """Rate-limit standing authorization to avoid PR floods."""
    import urllib.parse
    limit = POLICY.get("max_automatic_prs_per_24h", 0)
    if not isinstance(limit, int) or limit < 1 or limit > 4:
        raise Blocked("Invalid bounded automatic PR rate")
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = f'is:pr author:{POLICY["owner"]} created:>={since}'
    result = api("/search/issues?q=" + urllib.parse.quote(query, safe="") + "&per_page=1")
    if not result or not isinstance(result.get("total_count"), int):
        raise Blocked("Could not verify automatic PR rate limit")
    if result["total_count"] >= limit:
        raise Blocked("Automatic PR rate limit reached")


def publish(bundle: Path, verification: Path, review_path: Path) -> dict:
    check_policy()
    c = load_candidate(bundle / "candidate.json")
    report = json.loads(verification.read_text(encoding="utf-8"))
    if report.get("verified") is not True or report.get("repo") != c["repo"] or report.get("issue") != c["issue"]:
        raise Blocked("Independent focused-test verification is absent")
    current_candidate_ok(c)
    publication_rate_ok()
    manifest = json.loads((bundle/"manifest.json").read_text(encoding="utf-8"))
    safe_paths(manifest.get("paths", []))
    if (manifest.get("base_sha"),manifest.get("repo"),manifest.get("issue")) != (c["sha"],c["repo"],c["issue"]):
        raise Blocked("Inconsistent manifest")
    patch = (bundle/"patch.diff").read_bytes()
    if report.get("base_sha") != c["sha"] or any(
        report.get(key) != hashlib.sha256((bundle / filename).read_bytes()).hexdigest()
        for key, filename in (("patch_sha256", "patch.diff"),
                              ("checks_sha256", "checks.json"),
                              ("plan_sha256", "publication-plan.json"))
    ):
        raise Blocked("Verified patch, commands or publication plan differ from evidence")
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if (review.get("approved"), review.get("risk"), review.get("repo"), review.get("issue"), review.get("base_sha"),
        review.get("patch_sha256"), review.get("checks_sha256"), review.get("plan_sha256")) != (
        True, "low", c["repo"], c["issue"], c["sha"], report["patch_sha256"],
        report["checks_sha256"], report["plan_sha256"]):
        raise Blocked("Approved low-risk independent code review not verified")
    plan=json.loads((bundle/"publication-plan.json").read_text(encoding="utf-8"))
    if plan != publication_plan(c,manifest["paths"]):
        raise Blocked("Publication plan changed after review")
    actor = POLICY["owner"]
    target = c["repo"]
    issue = c["issue"]
    branch = f"ossbot/issue-{issue}-{c['sha'][:10]}"
    with tempfile.TemporaryDirectory(prefix="oss-publish-") as folder:
        workdir=Path(folder)/"source"
        checkout(c,workdir)
        if len(patch)>POLICY["max_patch_bytes"]:
            raise Blocked("Oversized patch")
        subprocess.run(["git","apply","--check","-"],input=patch,cwd=workdir,check=True,timeout=40)
        subprocess.run(["git","apply","-"],input=patch,cwd=workdir,check=True,timeout=40)
        from .core import changed_paths
        paths=changed_paths(workdir)
        if any((workdir/path).is_symlink() for path in paths):
            raise Blocked("Symlink change rejected")
        if sorted(paths)!=sorted(manifest["paths"]):
            raise Blocked("Patch changed out-of-scope paths")
        run(["git","diff","--check"],workdir,30)
        # Never run hooks, npm, pip, or other code from this untrusted repository.
        run(["git","switch","-c",branch],workdir,30)
        run(["git","add","--",*paths],workdir,30)
        env={**os.environ,"GIT_AUTHOR_NAME":"Jun516","GIT_AUTHOR_EMAIL":"174629376+Jun516@users.noreply.github.com","GIT_COMMITTER_NAME":"Jun516","GIT_COMMITTER_EMAIL":"174629376+Jun516@users.noreply.github.com"}
        run(["git","-c","core.hooksPath=/dev/null","commit","-m",f"fix: address {target} issue #{issue}"],workdir,45,env=env)
        # Forking and publication are authorized by the owner standing policy.
        fork_name = actor + "/" + target.split("/")[1]
        fork = api(repo_path(fork_name))
        if not fork:
            run(["gh","repo","fork",target,"--clone=false","--remote=false"],workdir,150)
            fork = api(repo_path(fork_name))
        # Confirm OWNED fork, never use a repository-controlled remote.
        if not fork or fork.get("owner",{}).get("login","").lower()!=actor.lower() or not fork.get("fork"):
            raise Blocked("Owned fork not verifiable")
        # If a previous partial attempt left a branch, do not overwrite it.
        # The upstream may also have acquired another PR after the initial scan.
        current_candidate_ok(c)
        existing_branch = api(repo_path(fork_name) + "/branches/" + branch.replace("/", "%2F"))
        if existing_branch:
            raise Blocked("Fork already has an automated branch for this issue/base")
        remote=f"https://github.com/{actor}/{target.split('/')[1]}.git"
        run(["git","remote","set-url","origin",remote],workdir,30)
        run(["gh","auth","setup-git"],workdir,30)
        run(["git","push","origin",f"HEAD:refs/heads/{branch}"],workdir,150)
        title = plan["title"]
        body = plan["body"]
        b=Path(folder)/"pr-body.md";b.write_text(body,encoding="utf-8")
        result=run(["gh","pr","create","--repo",target,"--head",f"{actor}:{branch}","--base",c["base"],"--title",title,"--body-file",str(b)],workdir,120)
        return {"status":"published","pr_url":result.stdout.strip(),"repo":target,"issue":issue,"branch":branch,"files":paths}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--bundle",required=True)
    p.add_argument("--verification",required=True)
    p.add_argument("--review",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    try:
        output=publish(Path(a.bundle),Path(a.verification),Path(a.review))
        Path(a.out).write_text(json.dumps(output,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(output))
    except Blocked as exc:
        Path(a.out).write_text(json.dumps({"status":"blocked","reason":str(exc)},indent=2)+"\n",encoding="utf-8")
        p.exit(2,"BLOCKED: "+str(exc)+"\n")

if __name__=="__main__":main()
