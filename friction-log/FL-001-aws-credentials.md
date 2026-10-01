# FL-001 — AWS profile setup and Bedrock access

- **Date:** 2026-10-01
- **Component:** Amazon Bedrock / local environment
- **Environment:** macOS development shell, AWS CLI profile `Decionis`, region `us-east-1`
- **Expected:** Use the developer's AWS profile to call Bedrock Converse with a tool-use capable model.
- **Observed:** The original HomeBound shell lacked credentials. AWS CLI 2.30.6 did not support `aws login`; Homebrew CLI 2.37.7 then failed to load its bundled Python XML symbol on this macOS runtime. A side-by-side AWS-bundled CLI 2.37.8 was installed and `aws login` completed. Boto3 can create a client but cannot use the login profile until its optional AWS CRT dependency is installed.
- **Error:** Initial profile verification had no credentials; Homebrew CLI reported a missing `_XML_SetAllocTrackerActivationThreshold` symbol; boto3 reported that the login credential provider requires `botocore[crt]`.
- **Impact:** The AWS profile and model availability are verified, but the live Bedrock inference path cannot yet read the profile from Python.
- **Investigation:** Checked the official AWS CLI installer, retained Homebrew CLI alongside the AWS-bundled CLI, and verified the selected profile without logging identifiers.
- **Workaround:** Use `/Users/bonus/.local/bin/aws` (AWS-bundled CLI 2.37.8) and set `AWS_PROFILE=Decionis` for boto3.
- **Resolution:** `aws sts get-caller-identity` succeeded. Bedrock's read-only catalog and availability APIs report the Amazon Nova Lite model/inference profile as authorized and available in `us-east-1`. Anthropic Sonnet 4.6 reports its usage agreement unavailable, so the project default is Nova Lite. The project now declares `botocore[crt]` for the `aws login` credential provider.
- **Upstream/documentation gap:** The Homebrew CLI's embedded Python runtime failed against the system XML library; the AWS bundled CLI worked as the side-by-side installation.
- **Status:** CLI credentials and model availability verified; `botocore[crt]` is now declared and installed in local Python environments. The live Bedrock smoke request has not been rerun after the dependency fix.
