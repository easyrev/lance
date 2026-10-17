# Keep the repository build entrypoint while using its required benchmark profile.
build:
	$(UV_RUN) maturin develop --uv --profile release-with-debug --locked
