# FL-014 — Boto3 requires AWS CRT for `aws login` profiles

- **Date:** 2026-10-01
- **Component:** Python AWS credential chain for Bedrock Runtime
- **Environment:** Python 3.13.5, boto3/botocore, AWS CLI `Decionis` login profile
- **Expected:** Create a boto3 `bedrock-runtime` client using the named profile created by `aws login`.
- **Observed:** Client creation fails before any Bedrock request because botocore's login-session credential provider needs its optional CRT dependency.
- **Error:** `MissingDependencyException: Using the login credential provider requires an additional dependency. You will need to pip install "botocore[crt]" before proceeding.`
- **Impact:** The real Bedrock orchestration cannot use the authenticated AWS profile from Python even though the AWS CLI works.
- **Investigation:** Read the installed AWS SDK Python credentials reference and confirmed login-session profiles explicitly require `botocore[crt]`.
- **Workaround:** Declare `botocore[crt]` as a project runtime dependency so boto3 can load and refresh the short-lived profile credentials.
- **Resolution:** Added the CRT extra to the Python dependency set and installed it in the local Python 3.10 and 3.13 environments. The live inference request has not been rerun after this fix.
- **Upstream/documentation gap:** `boto3` does not install CRT by default; the login-session provider's additional dependency is documented in botocore's credential guidance.
- **Status:** Dependency fix installed locally and covered by the passing Python test suites; live AWS inference remains unverified.
