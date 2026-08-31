#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RESPONSE_FILE=""
ASKPASS_DIR=""

usage() {
  cat <<'EOF'
Usage: ./github-setup.sh

Interactively create or verify the public GitHub install repository and push
only the local main branch. The GitHub token is read without echo and is not
stored in Git configuration, files, or credential helpers.

This command does not create a tag, release, or stable APT publication.
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if [[ -n "$RESPONSE_FILE" && -e "$RESPONSE_FILE" ]]; then
    unlink "$RESPONSE_FILE"
  fi
  if [[ -n "$ASKPASS_DIR" ]]; then
    if [[ -e "$ASKPASS_DIR/askpass.sh" ]]; then
      unlink "$ASKPASS_DIR/askpass.sh"
    fi
    if [[ -d "$ASKPASS_DIR" ]]; then
      rmdir "$ASKPASS_DIR"
    fi
  fi
  unset GITHUB_TOKEN
}

show_api_error() {
  python3 - "$RESPONSE_FILE" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        payload = json.load(handle)
except Exception:
    print("GitHub API request failed without a readable JSON response", file=sys.stderr)
else:
    print(f"GitHub API error: {payload.get('message', 'unknown error')}", file=sys.stderr)
PY
}

github_api() {
  local method="$1"
  local path="$2"
  local data="${3:-}"
  local -a args=(
    --silent
    --show-error
    --request "$method"
    --url "https://api.github.com${path}"
    --header "Accept: application/vnd.github+json"
    --header "X-GitHub-Api-Version: 2022-11-28"
    --output "$RESPONSE_FILE"
    --write-out '%{http_code}'
  )

  if [[ -n "$data" ]]; then
    args+=(--header "Content-Type: application/json" --data "$data")
  fi

  printf 'Authorization: Bearer %s\n' "$GITHUB_TOKEN" \
    | curl "${args[@]}" --header @-
}

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
  usage
  exit 0
fi
[[ $# -eq 0 ]] || die "this script accepts no account or token arguments; run it interactively"

for command in curl git python3; do
  command -v "$command" >/dev/null 2>&1 || die "required command is missing: $command"
done

cd "$ROOT_DIR"
[[ "$(git rev-parse --show-toplevel)" == "$ROOT_DIR" ]] \
  || die "run this script from the medge-release Git repository"
[[ "$(git branch --show-current)" == "main" ]] \
  || die "the local branch must be main"
[[ -z "$(git status --porcelain)" ]] \
  || die "the working tree must be clean before publishing main"

read -r -p "GitHub account or organization [motebus]: " GITHUB_OWNER
GITHUB_OWNER="${GITHUB_OWNER:-motebus}"
read -r -p "Repository name [download]: " GITHUB_REPOSITORY
GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-download}"

[[ "$GITHUB_OWNER" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ ]] \
  || die "invalid GitHub account or organization name"
[[ "$GITHUB_OWNER" != *- ]] \
  || die "GitHub account or organization name must not end with a hyphen"
[[ "$GITHUB_REPOSITORY" =~ ^[A-Za-z0-9._-]{1,100}$ ]] \
  || die "invalid GitHub repository name"

printf '\nTarget: https://github.com/%s/%s\n' "$GITHUB_OWNER" "$GITHUB_REPOSITORY"
printf 'Action: create/verify a public repository and push local main only.\n'
read -r -p "Continue [y/N]? " CONFIRM
[[ "$CONFIRM" == "y" || "$CONFIRM" == "Y" ]] || die "cancelled"

if [[ -z ${GITHUB_TOKEN:-} ]]; then
  read -r -s -p "GitHub token (input hidden): " GITHUB_TOKEN
  printf '\n'
fi
[[ -n "$GITHUB_TOKEN" ]] || die "GitHub token is required"
[[ ! "$GITHUB_TOKEN" =~ [[:space:]] ]] || die "GitHub token must not contain whitespace"

RESPONSE_FILE="$(mktemp)"
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM

HTTP_STATUS="$(github_api GET /user)"
if [[ "$HTTP_STATUS" != "200" ]]; then
  show_api_error
  die "GitHub authentication failed (HTTP $HTTP_STATUS)"
fi
AUTHENTICATED_LOGIN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["login"])' "$RESPONSE_FILE")"

REPO_PATH="/repos/${GITHUB_OWNER}/${GITHUB_REPOSITORY}"
HTTP_STATUS="$(github_api GET "$REPO_PATH")"
if [[ "$HTTP_STATUS" == "404" ]]; then
  CREATE_PAYLOAD="$(python3 -c 'import json,sys; print(json.dumps({"name": sys.argv[1], "description": "Binary-only MEdge APT distribution", "private": False, "has_issues": False, "has_projects": False, "has_wiki": False, "auto_init": False}))' "$GITHUB_REPOSITORY")"
  if [[ "${GITHUB_OWNER,,}" == "${AUTHENTICATED_LOGIN,,}" ]]; then
    CREATE_PATH="/user/repos"
  else
    CREATE_PATH="/orgs/${GITHUB_OWNER}/repos"
  fi
  HTTP_STATUS="$(github_api POST "$CREATE_PATH" "$CREATE_PAYLOAD")"
  if [[ "$HTTP_STATUS" != "201" ]]; then
    show_api_error
    die "could not create the public repository (HTTP $HTTP_STATUS); verify account permissions"
  fi
  printf 'Created public repository %s/%s.\n' "$GITHUB_OWNER" "$GITHUB_REPOSITORY"
elif [[ "$HTTP_STATUS" == "200" ]]; then
  IS_PRIVATE="$(python3 -c 'import json,sys; print(str(json.load(open(sys.argv[1], encoding="utf-8"))["private"]).lower())' "$RESPONSE_FILE")"
  [[ "$IS_PRIVATE" == "false" ]] || die "the existing repository is private; refusing to change its visibility"
  printf 'Verified existing public repository %s/%s.\n' "$GITHUB_OWNER" "$GITHUB_REPOSITORY"
else
  show_api_error
  die "could not inspect the target repository (HTTP $HTTP_STATUS)"
fi

REMOTE_URL="https://github.com/${GITHUB_OWNER}/${GITHUB_REPOSITORY}.git"
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

ASKPASS_DIR="$(mktemp -d)"
cat >"$ASKPASS_DIR/askpass.sh" <<'EOF'
#!/bin/sh
case "$1" in
  *Username*) printf '%s\n' "$GITHUB_LOGIN" ;;
  *Password*) printf '%s\n' "$GITHUB_TOKEN" ;;
  *) exit 1 ;;
esac
EOF
chmod 0700 "$ASKPASS_DIR/askpass.sh"

GIT_ASKPASS="$ASKPASS_DIR/askpass.sh" \
GIT_TERMINAL_PROMPT=0 \
GITHUB_LOGIN="$AUTHENTICATED_LOGIN" \
GITHUB_TOKEN="$GITHUB_TOKEN" \
  git -c credential.helper= push --set-upstream origin refs/heads/main:refs/heads/main

HTTP_STATUS="$(github_api PATCH "$REPO_PATH" '{"default_branch":"main"}')"
if [[ "$HTTP_STATUS" != "200" ]]; then
  show_api_error
  die "main was pushed, but setting it as the default branch failed (HTTP $HTTP_STATUS)"
fi

HTTP_STATUS="$(github_api GET "$REPO_PATH")"
[[ "$HTTP_STATUS" == "200" ]] || die "could not verify the repository after push"
DEFAULT_BRANCH="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["default_branch"])' "$RESPONSE_FILE")"
[[ "$DEFAULT_BRANCH" == "main" ]] || die "GitHub default branch is not main"

printf '\nGitHub setup complete:\n'
printf '  repository: https://github.com/%s/%s\n' "$GITHUB_OWNER" "$GITHUB_REPOSITORY"
printf '  branch:     main\n'
printf '  release:    not created\n'
