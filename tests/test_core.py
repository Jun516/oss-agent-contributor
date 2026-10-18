from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

import pytest

from oss_contributor import core, publisher, review


def _repo(stars=9000, license_="MIT", name="HKUDS/nanobot"):
    return {"full_name": name, "stargazers_count": stars, "license": {"spdx_id": license_}, "default_branch": "main", "pushed_at": datetime.now(timezone.utc).isoformat(), "archived": False}


def _issue(body=None, number=99):
    return {"number": number, "title": "A real bug", "html_url": f"https://github.com/HKUDS/nanobot/issues/{number}", "state": "open", "body": body or "Steps to reproduce: invoke command twice and compare the logs. Actual: execution fails with an error on the second call. Expected: the command succeeds, tested with a local synthetic reproduction and trace.", "labels": [{"name": "bug"}], "assignees": []}


def test_repository_requires_stars_license_fresh():
    assert core.allowed_repository(_repo())
    assert not core.allowed_repository(_repo(stars=4999))
    assert not core.allowed_repository(_repo(license_="NOASSERTION"))
    assert not core.allowed_repository(_repo(name="exa-labs/exa-py"))
    assert not core.allowed_repository({**_repo(), "archived": True})


def test_reporter_or_comment_claim_blocks_candidate():
    assert not core.issue_is_claimed(_issue(), [], [])
    assert core.issue_is_claimed({**_issue(), "body": _issue()["body"] + " I have a fix ready."}, [], [])
    assert core.issue_is_claimed(_issue(), [{"body":"I'll open a PR tomorrow"}], [])
    assert core.issue_is_claimed(_issue(), [], [{"event":"cross-referenced", "source":{"issue":{"pull_request":{},"html_url":"https://github.com/org/r/pull/10"}}}])
    assert core.issue_is_claimed({**_issue(), "assignees": [{"login":"someone"}]}, [], [])
    assert core.issue_is_claimed({**_issue(), "labels": [{"name":"needs-triage"}]}, [], [])


def test_issue_requires_repro_and_real_details():
    assert core.issue_has_repro(_issue())
    assert not core.issue_has_repro({**_issue(), "body":"something wrong"})


def test_path_gate_forbids_privileged_edits():
    for path in (".github/workflows/steal.yml", "AGENTS.md", "README/.env", "foo/../../secret", "pnpm-lock.yaml", "ee/secure.ts", ".git/config", "foo/.secrets"):
        with pytest.raises(core.Blocked):
            core.safe_paths([path])
    core.safe_paths(["src/fix.py", "tests/test_fix.py"])
    with pytest.raises(core.Blocked):
        core.safe_paths([])


def test_test_commands_block_shells_and_non_tests():
    core.valid_checks({"commands":[{"argv":["python","-m","pytest","tests/test_x.py","-q"],"cwd":"."}]})
    for argv in (["bash","-c","curl evil"], ["python","-c","print(1)"], ["pytest","tests/hello.py; cat /etc/passwd"], ["uv","tool","run","evil"]):
        with pytest.raises(core.Blocked):
            core.valid_checks({"commands":[{"argv":argv}]})
    with pytest.raises(core.Blocked):
        core.valid_checks({"commands":[{"argv":["python","-m","pytest","test.py"],"cwd":"../secret"}]})


def test_stale_commit_blocks_without_writing(monkeypatch):
    c={"repo":"HKUDS/nanobot", "issue":99, "base":"main", "sha":"a"*40}
    monkeypatch.setattr(core,"api",lambda path: _repo() if path=="/repos/HKUDS/nanobot" else ({"commit":{"sha":"b"*40}} if "/branches/main" in path else None))
    monkeypatch.setattr(core,"contrib_rules",lambda _:True)
    with pytest.raises(core.Blocked,match="base moved"):
        core.current_candidate_ok(c)


def test_scan_emits_candidate_and_respects_read_only(monkeypatch,tmp_path):
    r=_repo(); i=_issue()
    def fake_api(path):
        if path.startswith("/search/repositories"): return {"items":[r]}
        if path.startswith("/search/issues") and "is%3Apr" in path: return {"total_count":0}
        if path.startswith("/search/issues"): return {"items":[i]}
        if "/issues/99/comments" in path or "/issues/99/timeline" in path: return []
        if "/branches/main" in path: return {"commit":{"sha":"a"*40}}
        return None
    monkeypatch.setattr(core,"api",fake_api)
    monkeypatch.setattr(core,"contrib_rules",lambda _:True)
    out=tmp_path/"scan.json"; result=core.discover(out)
    assert result["candidate"]["repo"]=="HKUDS/nanobot"
    assert result["candidate"]["sha"]=="a"*40
    assert json.loads(out.read_text())["summary"]["repositories_evaluated"]==1


def test_collect_real_git_diff(monkeypatch,tmp_path):
    project=tmp_path/"source";project.mkdir()
    def git(*args):
        return subprocess.run(["git",*args],cwd=project,check=True,capture_output=True,text=True)
    git("init","-b","main")
    git("config","user.name","Test")
    git("config","user.email","test@example.com")
    (project/"module.py").write_text("def value():\n    return 0\n")
    git("add","module.py");git("commit","-m","initial")
    sha=git("rev-parse","HEAD").stdout.strip()
    (project/"module.py").write_text("def value():\n    return 1\n")
    candidate=tmp_path/"candidate.json";candidate.write_text(json.dumps({"candidate":{"repo":"HKUDS/nanobot","issue":99,"issue_title":"A real bug","issue_url":"https://github.com/HKUDS/nanobot/issues/99","sha":sha,"base":"main"}}))
    checks=tmp_path/"checks.json";checks.write_text(json.dumps({"commands":[{"argv":["python","-m","pytest","tests/test_x.py"]}]}))
    dest=tmp_path/"bundle";core.collect(project,dest,checks,candidate)
    assert "return 1" in (dest/"patch.diff").read_text()
    assert json.loads((dest/"manifest.json").read_text())["paths"]==["module.py"]


def test_publisher_fails_closed_without_credential(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(core.Blocked, match="missing"):
        publisher.check_policy()


def test_publisher_preauthorized_without_per_pr_confirmation(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.delenv("OSS_PUBLISH_APPROVED", raising=False)
    monkeypatch.setattr(publisher.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(publisher, "run", lambda *args, **kwargs: SimpleNamespace(stdout="Jun516\n"))
    publisher.check_policy()


def test_publisher_rejects_wrong_login(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setattr(publisher.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(publisher, "run", lambda *args, **kwargs: SimpleNamespace(stdout="SomebodyElse\n"))
    with pytest.raises(core.Blocked, match="identity"):
        publisher.check_policy()


def test_lookups_do_not_accept_full_urls():
    with pytest.raises(core.Blocked):
        core.repo_path("https://github.com/evil/thing")


def test_patch_replayed_and_real_focused_test_executes(monkeypatch, tmp_path):
    source = tmp_path / "upstream"; source.mkdir()
    def git(*args, at=source):
        return subprocess.run(["git", *args], cwd=at, check=True, capture_output=True, text=True)
    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    (source / "feature.py").write_text("def answer():\n    return 0\n")
    (source / "tests").mkdir()
    (source / "tests" / "test_feature.py").write_text("from feature import answer\n\ndef test_answer():\n    assert answer() == 1\n")
    git("add", "."); git("commit", "-m", "baseline")
    sha = git("rev-parse", "HEAD").stdout.strip()
    (source / "feature.py").write_text("def answer():\n    return 1\n")
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({"candidate": {"repo": "HKUDS/nanobot", "issue": 99, "issue_title": "Return 1", "issue_url": "https://github.com/HKUDS/nanobot/issues/99", "sha": sha, "base": "main"}}))
    checks = tmp_path / "verification.json"
    checks.write_text(json.dumps({"commands": [{"argv": ["python", "-m", "pytest", "tests/test_feature.py", "-q"], "cwd": "."}]}))
    bundle = tmp_path / "bundle"
    core.collect(source, bundle, checks, candidate)
    def checkout_local(c, target):
        subprocess.run(["git", "clone", "--quiet", str(source), str(target)], cwd=tmp_path, check=True)
        subprocess.run(["git", "checkout", "--detach", c["sha"]], cwd=target, check=True, capture_output=True)
    monkeypatch.setattr(core, "checkout", checkout_local)
    report = tmp_path / "report.json"
    core.verify(bundle, tmp_path / "replayed", report)
    outcome = json.loads(report.read_text())
    assert outcome["verified"] is True
    assert outcome["results"][0]["returncode"] == 0
    assert "1 passed" in outcome["results"][0]["log_tail"]


def test_publication_plan_matches_full_pr_description(tmp_path):
    c={"repo":"HKUDS/nanobot", "issue":123, "issue_title":"Fix runtime behaviour", "issue_url":"https://github.com/HKUDS/nanobot/issues/123", "base":"main", "sha":"a"*40}
    plan=core.publication_plan(c,["src/fix.py", "tests/test_fix.py"])
    assert "Closes https://github.com/HKUDS/nanobot/issues/123" in plan["body"]
    assert plan["head"]=="Jun516:ossbot/issue-123-aaaaaaaaaa"


def test_publisher_rate_guard_prevents_floods(monkeypatch):
    limit = publisher.POLICY["max_automatic_prs_per_24h"]
    assert limit == 4
    monkeypatch.setattr(publisher, "api", lambda _: {"total_count": limit})
    with pytest.raises(core.Blocked, match="rate limit reached"):
        publisher.publication_rate_ok()
    monkeypatch.setattr(publisher, "api", lambda _: {"total_count": limit - 1})
    publisher.publication_rate_ok()
    monkeypatch.setattr(publisher, "api", lambda _: None)
    with pytest.raises(core.Blocked, match="Could not verify"):
        publisher.publication_rate_ok()


def test_contribution_rules_require_contributing_and_check_agents(monkeypatch):
    import base64
    files = {
        "CONTRIBUTING.md": "Contributions welcome. Run focused tests.",
        "AGENTS.md": "Do not submit AI-generated pull requests.",
    }
    def fake_api(path):
        tail=path.split('/contents/', 1)[-1]
        if tail in files:
            return {"type": "file", "content": base64.b64encode(files[tail].encode()).decode()}
        return None
    monkeypatch.setattr(core,"api",fake_api)
    assert not core.contrib_rules("HKUDS/nanobot")
    files.pop("AGENTS.md")
    assert core.contrib_rules("HKUDS/nanobot")


def test_requires_focused_test_not_install_alone():
    with pytest.raises(core.Blocked, match="focused test"):
        core.valid_checks({"commands":[{"argv":["pnpm","install","--frozen-lockfile"]}]})
    core.valid_checks({"commands":[{"argv":["pnpm","install","--frozen-lockfile"]},{"argv":["pnpm","--filter","mcp-use","test"]}]})


def test_independent_review_binds_all_artifacts(tmp_path):
    import hashlib
    bundle = tmp_path / "bundle"; bundle.mkdir()
    c = {"repo": "HKUDS/nanobot", "issue": 123, "issue_title": "Actual bug", "issue_url": "https://github.com/HKUDS/nanobot/issues/123", "base": "main", "sha": "a" * 40}
    (bundle / "candidate.json").write_text(json.dumps({"candidate": c}))
    (bundle / "manifest.json").write_text(json.dumps({"repo": c["repo"], "issue": 123, "base_sha": c["sha"], "paths": ["src/fix.py"]}))
    for filename in ("patch.diff", "checks.json", "publication-plan.json"):
        (bundle / filename).write_text(filename)
    data = {"verified": True, "repo": c["repo"], "issue": 123, "base_sha": c["sha"],
            "results": [{"returncode": 0}],
            "patch_sha256": hashlib.sha256((bundle/"patch.diff").read_bytes()).hexdigest(),
            "checks_sha256": hashlib.sha256((bundle/"checks.json").read_bytes()).hexdigest(),
            "plan_sha256": hashlib.sha256((bundle/"publication-plan.json").read_bytes()).hexdigest()}
    report=tmp_path/"report.json"; report.write_text(json.dumps(data))
    verdict=tmp_path/"verdict.json";out=tmp_path/"review-report.json"
    verdict.write_text(json.dumps({"approved":True,"risk":"low","reason":"Focused minimal fix and related test, no unrelated changes."}))
    review.gate(bundle,report,verdict,out)
    saved=json.loads(out.read_text())
    assert saved["approved"] is True and saved["patch_sha256"]==data["patch_sha256"]
    (bundle/"patch.diff").write_text("TAMPERED")
    with pytest.raises(core.Blocked,match="evidence changed"):
        review.gate(bundle,report,verdict,out)


def test_independent_review_rejects_medium_risk_even_with_tests(tmp_path):
    import hashlib
    bundle=tmp_path/"bundle"; bundle.mkdir()
    c={"repo":"HKUDS/nanobot","issue":33,"issue_title":"bug","issue_url":"https://github.com/HKUDS/nanobot/issues/33","base":"main","sha":"a"*40}
    (bundle/"candidate.json").write_text(json.dumps({"candidate":c}))
    (bundle/"manifest.json").write_text(json.dumps({"repo":c["repo"],"issue":33,"base_sha":c["sha"],"paths":["fix.py"]}))
    for name in ("patch.diff","checks.json","publication-plan.json"): (bundle/name).write_text(name)
    report={"verified":True,"repo":c["repo"],"issue":33,"base_sha":c["sha"],"results":[]}
    for key,name in (("patch_sha256","patch.diff"),("checks_sha256","checks.json"),("plan_sha256","publication-plan.json")):
        report[key]=hashlib.sha256((bundle/name).read_bytes()).hexdigest()
    (tmp_path/"report.json").write_text(json.dumps(report))
    (tmp_path/"verdict.json").write_text(json.dumps({"approved":True,"risk":"medium","reason":"This appears to need wider changes and more testing."}))
    with pytest.raises(core.Blocked,match="above low risk"):
        review.gate(bundle,tmp_path/"report.json",tmp_path/"verdict.json",tmp_path/"review-report.json")


def test_workflow_bot_scheduling_and_separate_credential_scope():
    import yaml
    from pathlib import Path
    workflow=yaml.safe_load((core.ROOT/".github/workflows/oss-contributor.yml").read_text())
    jobs=workflow["jobs"]
    assert set(jobs)=={"discover","propose","verify","review","publish"}
    assert jobs["propose"]["steps"][4]["with"]["allow-bots"] is True  # scheduled trusted github-actions bot
    assert jobs["review"]["needs"]=="verify"
    assert jobs["publish"]["needs"]==["verify","review"]
    assert "OSS_BOT_TOKEN" not in str(jobs["discover"])+str(jobs["propose"])+str(jobs["verify"])+str(jobs["review"])
    assert "OSS_BOT_TOKEN" in str(jobs["publish"])
    assert "oss-publish" not in str(jobs["publish"])


def test_publisher_full_flow_with_local_git_remote_and_mocked_github(monkeypatch, tmp_path):
    """Exercise real local commit+push; simulate only external GitHub API/PR calls."""
    from types import SimpleNamespace

    upstream = tmp_path / "upstream"; upstream.mkdir()
    def git(cmd, cwd):
        return subprocess.run(["git", *cmd], cwd=cwd, capture_output=True, text=True, check=True)
    git(["init", "-b", "main"], upstream)
    git(["config", "user.name", "Fixture"], upstream)
    git(["config", "user.email", "fixture@example.com"], upstream)
    (upstream/"example.py").write_text("def value():\n    return 0\n")
    (upstream/"tests").mkdir()
    (upstream/"tests/test_example.py").write_text("from example import value\n\ndef test_value():\n    assert value() == 1\n")
    git(["add", "."], upstream)
    git(["commit", "-m", "baseline"], upstream)
    sha=git(["rev-parse", "HEAD"], upstream).stdout.strip()
    (upstream/"example.py").write_text("def value():\n    return 1\n")
    c={"repo":"HKUDS/nanobot","issue":991,"issue_title":"Fix actual regression","issue_url":"https://github.com/HKUDS/nanobot/issues/991","base":"main","sha":sha}
    scan=tmp_path/"scan.json";scan.write_text(json.dumps({"candidate":c}))
    checks=tmp_path/"checks.json"
    checks.write_text(json.dumps({"commands":[{"argv":["python","-m","pytest","tests/test_example.py","-q"],"cwd":"."}]}))
    bundle=tmp_path/"bundle"
    core.collect(upstream,bundle,checks,scan)

    def local_checkout(candidate, target):
        subprocess.run(["git", "clone", "--quiet", str(upstream), str(target)], check=True)
        subprocess.run(["git", "checkout", "--detach", candidate["sha"]], cwd=target, check=True, capture_output=True)

    monkeypatch.setattr(core,"checkout",local_checkout)
    report=tmp_path/"report.json"
    core.verify(bundle,tmp_path/"verify-clone",report)
    verdict=tmp_path/"verdict.json"
    verdict.write_text(json.dumps({"approved":True,"risk":"low","reason":"Verified focused regression fix without unrelated changes."}))
    review_report=tmp_path/"review-report.json"
    review.gate(bundle,report,verdict,review_report)

    bare=tmp_path/"fork.git"
    subprocess.run(["git","init","--bare",str(bare)],check=True,capture_output=True)
    monkeypatch.setattr(publisher,"checkout",local_checkout)
    monkeypatch.setattr(publisher,"check_policy",lambda: None)
    monkeypatch.setattr(publisher,"current_candidate_ok",lambda _: None)
    monkeypatch.setattr(publisher,"publication_rate_ok",lambda: None)
    fork_created=[False]
    created_pr=[]

    def fake_api(path):
        if path=="/repos/Jun516/nanobot":
            return {"owner":{"login":"Jun516"},"fork":True} if fork_created[0] else None
        if path.startswith("/repos/Jun516/nanobot/branches/"):
            return None
        raise AssertionError("Unexpected API: " + path)
    monkeypatch.setattr(publisher,"api",fake_api)

    def fake_run(command, cwd, timeout=600, env=None):
        if command[:3]==["gh","repo","fork"]:
            fork_created[0]=True
            return SimpleNamespace(stdout="forked\n")
        if command[:3]==["gh","auth","setup-git"]:
            return SimpleNamespace(stdout="authenticated\n")
        if command[:3]==["gh","pr","create"]:
            created_pr.append(command)
            return SimpleNamespace(stdout="https://github.com/HKUDS/nanobot/pull/11111\n")
        if command[:4]==["git","remote","set-url","origin"]:
            command=["git","remote","set-url","origin",str(bare)]
        return core.run(command,cwd,timeout,env)
    monkeypatch.setattr(publisher,"run",fake_run)
    published=publisher.publish(bundle,report,review_report)
    assert published["status"]=="published"
    assert published["pr_url"]=="https://github.com/HKUDS/nanobot/pull/11111"
    assert len(created_pr)==1
    assert "--head" in created_pr[0] and "Jun516:ossbot/issue-991-" in " ".join(created_pr[0])
    branch="ossbot/issue-991-"+sha[:10]
    cp=subprocess.run(["git","--git-dir",str(bare),"rev-parse",f"refs/heads/{branch}"],text=True,capture_output=True,check=True)
    assert len(cp.stdout.strip())==40  # A real Git commit was pushed into the simulated fork
