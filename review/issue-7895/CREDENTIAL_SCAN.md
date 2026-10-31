# Credential scan

- Files scanned in the initial pass: 1,057
- Non-UTF-8 files skipped: 0
- Active OSS key, secret, session token, bucket, and endpoint values checked: yes
- Common cloud access-key, source-control token, agent-session URL, and API-key patterns checked: yes
- Generic credential assignments checked: yes
- Initial files with exact bucket or endpoint occurrences: 6
- Initial files with access-key, secret, session-token, credential-assignment, or token-pattern hits: 0
- Files redacted: 6
- Files in the final rescan, including this report and the checksum manifest: 1,059
- Remaining exact-value hits outside `/root/.lance-bench/oss.env`: 0
- Remaining credential-token or session-URL pattern hits: 0

The required literal path `/root/.lance-bench/oss.env` is exempt from the
bucket-token check because the harness must load that path itself. No
credential value, actual bucket value, endpoint value, source-control token,
or agent-session URL is retained in the evidence.
