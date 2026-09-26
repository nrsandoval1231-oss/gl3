# GL3-001 Compose bootstrap repair

Controller final gate on candidate b83694456209865b89c5ff33c56760460695c9d081cedce365649250d67b27d8 found that an unquoted generated bcrypt value is interpreted as Compose variable substitutions. `config --quiet` exits zero but emits interpolation warnings and corrupts authentication configuration; zero exit alone is not acceptance.

One Luna owns scripts/setup_compose.py and a focused test only if needed. Encode generated secrets literally in dotenv syntax. The Compose credentials were freshly generated for local configuration proof and never deployed; regeneration of only those files is authorized. Preserve native .env and local-auth.txt unchanged. Do not log config, hash, password, or secret fragments.

Validate rendered Compose configuration in memory and compare its API password hash against the generated Compose password using bcrypt. Output booleans and exit status only. Preserve the failure and repair result in the completion handoff, release files, and require controller refreeze. No deployment/container-start/paid action. Retry budget two materially different approaches; no unrelated changes.
