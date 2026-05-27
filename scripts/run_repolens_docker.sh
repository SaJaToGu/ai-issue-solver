#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Run RepoLens in a constrained Docker sandbox.

Usage:
  scripts/run_repolens_docker.sh [options] [-- extra repolens args]

Options:
  --project-dir PATH   Repository to analyze (default: current directory)
  --report-dir PATH    Writable report directory (default: PROJECT/reports/repolens)
  --image NAME         Docker image to run (default: repolens)
  --domain NAME        RepoLens domain/lens (default: security)
  --network MODE       Docker network mode (default: none)
  --cpus VALUE         Optional Docker CPU limit, e.g. 2
  --memory VALUE       Optional Docker memory limit, e.g. 4g
  -h, --help           Show this help

The project is mounted read-only at /project. The report directory is mounted
writable at /reports. No .env file or GitHub write token is passed through.
USAGE
}

project_dir="$(pwd)"
report_dir=""
image="${REPOLENS_IMAGE:-repolens}"
domain="${REPOLENS_DOMAIN:-security}"
network="${REPOLENS_NETWORK:-none}"
cpus="${REPOLENS_CPUS:-}"
memory="${REPOLENS_MEMORY:-}"
extra_args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)
      project_dir="$2"
      shift 2
      ;;
    --report-dir)
      report_dir="$2"
      shift 2
      ;;
    --image)
      image="$2"
      shift 2
      ;;
    --domain)
      domain="$2"
      shift 2
      ;;
    --network)
      network="$2"
      shift 2
      ;;
    --cpus)
      cpus="$2"
      shift 2
      ;;
    --memory)
      memory="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      extra_args=("$@")
      break
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

project_dir="$(cd "$project_dir" && pwd)"
if [[ -z "$report_dir" ]]; then
  report_dir="$project_dir/reports/repolens"
fi
mkdir -p "$report_dir"
report_dir="$(cd "$report_dir" && pwd)"

docker_args=(
  run
  --rm
  --user "$(id -u):$(id -g)"
  --network "$network"
  -v "$project_dir:/project:ro"
  -v "$report_dir:/reports"
  -w /project
)

if [[ -n "$cpus" ]]; then
  docker_args+=(--cpus "$cpus")
fi
if [[ -n "$memory" ]]; then
  docker_args+=(--memory "$memory")
fi

repolens_args=(./repolens.sh --project /project --domain "$domain" --local --output /reports)
if [[ ${#extra_args[@]} -gt 0 ]]; then
  repolens_args+=("${extra_args[@]}")
fi

echo "RepoLens sandbox:"
echo "  project: $project_dir -> /project:ro"
echo "  reports: $report_dir -> /reports"
echo "  network: $network"
echo "  image:   $image"

exec docker "${docker_args[@]}" "$image" "${repolens_args[@]}"
