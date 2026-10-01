# FL-001 — AWS credentials are not available to the local process

- **Date:** 2026-10-01
- **Component:** Amazon Bedrock / local environment
- **Environment:** macOS development shell, Python 3.13.5
- **Expected:** Use the developer's Amazon account to call Bedrock Converse after selecting a model.
- **Observed:** `aws sts get-caller-identity` reported that credentials were unavailable to the current process.
- **Error:** No AWS credentials were found in the active AWS credential chain.
- **Impact:** The Bedrock code can be tested with an injected runtime client, but a live model request cannot yet be verified from this shell.
- **Investigation:** The application uses `boto3`'s standard credential chain and does not copy or persist AWS secrets.
- **Workaround:** Configure an AWS profile or IAM Identity Center SSO session with Bedrock Runtime access; set `AWS_PROFILE` and `AWS_REGION` as needed.
- **Resolution:** Open. Live Bedrock verification is a setup dependency for the next run.
- **Upstream/documentation gap:** None found; AWS CLI and SDK credential-chain configuration is documented by AWS.
- **Status:** Open
