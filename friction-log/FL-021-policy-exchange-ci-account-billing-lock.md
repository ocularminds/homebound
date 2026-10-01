# FL-021: Policy Exchange CI did not start because of account billing lock

- **Date:** 2026-10-02
- **Component:** Decionis Policy Exchange GitHub Actions
- **Environment:** Public `decionis/policy-exchange` PR #11
- **Expected:** The repository's pack validation workflow runs on the pull request and reports whether the catalog file passes.
- **Observed:** GitHub reports the validation job as failed before start and annotates: "The job was not started because your account is locked due to a billing issue."
- **Error:** No runner was allocated; the validator did not execute.
- **Impact:** The check provides no evidence for or against the pack's validity. It must not be described as a content-validation failure.
- **Investigation:** Inspected the workflow job annotation in GitHub Actions. The failure is account-level and precedes repository code execution.
- **Workaround:** Validated the pack locally with HomeBound's YAML shape and outcome tests. The PR description identifies the CI limitation. Re-running the workflow would not address an account billing lock.
- **Resolution:** Await account billing status to be resolved, then allow the repository validation workflow to run.
- **Upstream/documentation gap:** GitHub's workflow UI reports an account lock but does not provide a repository-level remediation path in the job output.
- **Status:** External blocker; no upstream CI validation result.
