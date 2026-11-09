#!/usr/bin/env bash
# Get out/models/v1 and out/models/v2: use local ones if present, otherwise download the GitHub Release assets
# (tag "models", assets model-v1.tar.gz, model-v2.tar.gz and model-vN.sha256) and verify their checksums.
# Works for public and PRIVATE repositories: with the gh CLI (uses GH_TOKEN / GITHUB_TOKEN, or `gh auth login` locally);
# without gh it falls back to curl, which only works for public repositories.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="${GITHUB_REPOSITORY:-$(git config --get remote.origin.url 2>/dev/null | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')}"
TAG="${RELEASE_TAG:-models}"
export GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
for v in v1 v2; do
  [ -f "out/models/$v/model.safetensors" ] && { echo "using local out/models/$v"; continue; }
  [ -n "$REPO" ] || { echo "cannot work out the GitHub repo; set GITHUB_REPOSITORY" >&2; continue; }
  mkdir -p out/release out/models
  ok=0
  if command -v gh >/dev/null 2>&1 && { [ -n "$GH_TOKEN" ] || gh auth status >/dev/null 2>&1; }; then
    gh release download "$TAG" --repo "$REPO" -p "model-$v.tar.gz" -p "model-$v.sha256" -D out/release --clobber && ok=1
  else
    base="https://github.com/${REPO}/releases/download/${TAG}"
    curl -fsSL -o "out/release/model-$v.tar.gz" "$base/model-$v.tar.gz" &&
      curl -fsSL -o "out/release/model-$v.sha256" "$base/model-$v.sha256" && ok=1
  fi
  if [ "$ok" = 1 ]; then
    (cd out/release && sha256sum -c "model-$v.sha256")
    tar -xzf "out/release/model-$v.tar.gz" -C out/models
    cp "out/release/model-$v.sha256" "out/models/$v/model.sha256"
    echo "downloaded model $v from ${REPO} release ${TAG}"
  else
    echo "WARNING: could not download model-$v from release ${TAG} of ${REPO} (private repo? set GH_TOKEN or run gh auth login)" >&2
  fi
done
