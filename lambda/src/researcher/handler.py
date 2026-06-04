"""SubnetResearcher Lambda — researches one subnet's GitHub repo per invocation.

Triggered by EventBridge Scheduler (self-perpetuating, 7-day cadence).
Fetches repo contents, applies multi-file scanning cascade, produces
a research profile stored in DynamoDB.

Scanning cascade (priority order):
1. min_compute.yml → structured hardware requirements
2. Dockerfile → GPU base images, runtime flags
3. docker-compose*.yml → GPU device mapping
4. requirements.txt / pyproject.toml → torch/cuda deps
5. README.md → keywords for model type, hardware mentions
"""

import json
import logging
import re
import urllib.request
import urllib.error
import base64
from datetime import datetime, timezone
from typing import Any, Optional

import boto3

from src.config import get_config, PipelineConfig
from src.state.state_manager import StateManager
from src.storage.storage_layer import StorageLayer
from src.instrumentation import instrument

logger = logging.getLogger("tao-pipeline")

# Module-level cold-start cache
_config: Optional[PipelineConfig] = None
_state_manager: Optional[StateManager] = None
_storage: Optional[StorageLayer] = None
_github_token: Optional[str] = None

# GPU detection keywords
GPU_DEP_KEYWORDS = {"torch", "cuda", "bitsandbytes", "triton", "vllm", "transformers",
                    "diffusers", "tensorflow-gpu", "jax[cuda]", "cupy"}
GPU_README_KEYWORDS = {"gpu", "a100", "h100", "rtx", "vram", "cuda", "nvidia"}
MODEL_TYPE_KEYWORDS = {
    "zero_knowledge": ["zero knowledge", "zkp", "zk-proof", "zk proof", "prover"],
    "prediction": ["price prediction", "forecasting subnet", "trading subnet", "oracle subnet", "time series prediction"],
    "storage": ["storage subnet", "proof of spacetime", "decentralized storage", "file storage"],
    "data": ["data scraping subnet", "data universe", "blockchain data subnet", "blockchain insights"],
    "audio": ["text-to-speech", "speech subnet", "tts subnet", "audio subnet", "whisper", "transcription subnet"],
    "image_generation": ["stable diffusion", "image generation subnet", "diffuser", "deepfake detection"],
    "compute": ["pre-training", "pretraining", "distributed training", "fine-tuning subnet", "compute subnet"],
    "llm_inference": ["llm inference", "language model inference", "vllm", "text generation", "prompting subnet", "inference subnet"],
    "code": ["code generation", "code completion", "coding subnet", "software development subnet"],
}


def _init_clients() -> None:
    """Initialize AWS clients and config on cold start."""
    global _config, _state_manager, _storage, _github_token
    if _config is not None:
        return
    _config = get_config()
    _state_manager = StateManager(_config)
    _storage = StorageLayer(_config)
    # Load GitHub token from Parameter Store
    if _config.is_aws:
        ssm = boto3.client("ssm", region_name=_config.region)
        try:
            resp = ssm.get_parameter(Name="/tao-pipeline/github-token", WithDecryption=True)
            _github_token = resp["Parameter"]["Value"]
        except Exception as e:
            logger.warning(f"Could not load GitHub token: {e}")
            _github_token = None


def handle(event: dict, context: Any) -> dict:
    """Lambda entry point. Researches a single subnet's GitHub repo."""
    _init_clients()

    netuid = event.get("netuid")
    if netuid is None:
        return {"status": "error", "error": "missing netuid"}

    netuid = int(netuid)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with instrument("researcher", "handle", netuid=netuid):
        # Look up repo URL
        repo = _get_repo_url(netuid)
        if not repo:
            profile = _empty_profile(netuid, reason="no_repo_mapping")
            _store_profile(netuid, date, profile)
            return {"status": "complete", "netuid": netuid, "confidence": "none"}

        # Validate URL is still accessible
        if not _validate_repo(repo):
            profile = _empty_profile(netuid, reason="repo_not_found")
            _store_profile(netuid, date, profile)
            return {"status": "complete", "netuid": netuid, "confidence": "none"}

        # Fetch and analyze
        analysis = _analyze_repo(repo)

        # Build research profile
        profile = _build_profile(netuid, repo, analysis)

        # Store
        _store_profile(netuid, date, profile)

        return {
            "status": "complete",
            "netuid": netuid,
            "difficulty": profile["difficulty"],
            "gpu_required": profile["gpu_required"],
            "confidence": profile["research_confidence"],
        }


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------


def _github_request(url: str) -> Optional[dict]:
    """Make authenticated GitHub API request."""
    headers = {"User-Agent": "tao-subnet-researcher"}
    if _github_token:
        headers["Authorization"] = f"token {_github_token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None


def _github_file(repo: str, path: str) -> Optional[str]:
    """Fetch a file's content from a GitHub repo."""
    data = _github_request(f"https://api.github.com/repos/{repo}/contents/{path}")
    if data and "content" in data:
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return None


def _github_dir(repo: str, path: str = "") -> list[str]:
    """List files in a repo directory."""
    data = _github_request(f"https://api.github.com/repos/{repo}/contents/{path}")
    if isinstance(data, list):
        return [f["name"] for f in data]
    return []


def _get_repo_url(netuid: int) -> Optional[str]:
    """Look up repo for a subnet from config or DynamoDB."""
    # Try static mapping first
    import importlib.resources
    try:
        mapping_path = _config.project_root / "config" / "subnet_repos.json"
        if mapping_path.exists():
            with open(mapping_path) as f:
                mapping = json.load(f)
            entry = mapping.get(str(netuid))
            if entry:
                return entry["repo"]
    except Exception:
        pass
    return None


def _validate_repo(repo: str) -> bool:
    """HEAD-check that repo exists (handles renames via 301)."""
    data = _github_request(f"https://api.github.com/repos/{repo}")
    return data is not None


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def _analyze_repo(repo: str) -> dict:
    """Run multi-file scanning cascade on a repo."""
    result = {
        "gpu_required": False,
        "gpu_signals": [],
        "vram_gb_estimate": None,
        "model_type": "unknown",
        "has_miner": False,
        "miner_entrypoint": None,
        "language": None,
        "raw_files": {},
    }

    # Use repo description from GitHub as first model-type signal
    repo_info = _github_request(f"https://api.github.com/repos/{repo}")
    if repo_info:
        desc = (repo_info.get("description") or "").lower()
        name = (repo_info.get("name") or "").lower()
        combined = f"{name} {desc}"
        for mtype, keywords in MODEL_TYPE_KEYWORDS.items():
            if any(k in combined for k in keywords):
                result["model_type"] = mtype
                break

    root_files = _github_dir(repo)
    result["root_files"] = root_files

    # 1. min_compute.yml
    for fname in ["min_compute.yml", "min_compute.yaml"]:
        if fname in root_files:
            content = _github_file(repo, fname)
            if content:
                result["raw_files"]["min_compute"] = content
                _parse_min_compute(content, result)
                break

    # 2. Dockerfile
    if "Dockerfile" in root_files:
        content = _github_file(repo, "Dockerfile")
        if content:
            result["raw_files"]["dockerfile"] = content
            _parse_dockerfile(content, result)

    # 3. docker-compose
    for fname in root_files:
        if "docker-compose" in fname and fname.endswith((".yml", ".yaml")):
            content = _github_file(repo, fname)
            if content:
                result["raw_files"]["docker_compose"] = content
                _parse_docker_compose(content, result)
                break

    # 4. Dependencies (root + subdirs)
    _scan_dependencies(repo, root_files, result)

    # 5. README
    for fname in root_files:
        if fname.lower().startswith("readme"):
            content = _github_file(repo, fname)
            if content:
                result["raw_files"]["readme"] = content[:5000]  # cap storage
                _parse_readme(content, result)
            break

    # Detect miner entrypoint
    _detect_miner(repo, root_files, result)

    # Detect language
    _detect_language(root_files, result)

    return result


def _parse_min_compute(content: str, result: dict) -> None:
    """Parse min_compute.yml for hardware requirements (miner section)."""
    content_lower = content.lower()
    # Look specifically in the miner section for GPU requirements
    miner_section = content_lower.split("validator:")[0] if "validator:" in content_lower else content_lower
    if "miner:" in miner_section:
        miner_section = miner_section.split("miner:")[1]

    if "gpu" in miner_section:
        # Check required field explicitly
        req_match = re.search(r"required:\s*(true|false)", miner_section)
        if req_match and req_match.group(1) == "true":
            result["gpu_required"] = True
            result["gpu_signals"].append("min_compute.yml:gpu.required=true")
        # Extract VRAM regardless (useful even if GPU is optional)
        vram_match = re.search(r"min_vram:\s*(\d+)", miner_section)
        if vram_match:
            result["vram_gb_estimate"] = int(vram_match.group(1))


def _parse_dockerfile(content: str, result: dict) -> None:
    """Parse Dockerfile for GPU signals."""
    content_lower = content.lower()
    if "nvidia/cuda" in content_lower or "pytorch" in content_lower:
        result["gpu_required"] = True
        result["gpu_signals"].append("Dockerfile:nvidia/cuda base image")
    if "vllm" in content_lower:
        result["gpu_required"] = True
        result["gpu_signals"].append("Dockerfile:vllm")


def _parse_docker_compose(content: str, result: dict) -> None:
    """Parse docker-compose for GPU device reservations."""
    if "nvidia" in content.lower() or "gpu" in content.lower():
        result["gpu_required"] = True
        result["gpu_signals"].append("docker-compose:GPU device")


def _scan_dependencies(repo: str, root_files: list[str], result: dict) -> None:
    """Scan dependency files at root and in subdirs."""
    dep_files = ["requirements.txt", "pyproject.toml", "setup.py", "Pipfile"]
    dirs_to_check = [""] + [d for d in ["neurons", "miner", "src"] if d in root_files]

    for directory in dirs_to_check:
        for dep_file in dep_files:
            path = f"{directory}/{dep_file}" if directory else dep_file
            content = _github_file(repo, path)
            if content:
                content_lower = content.lower()
                found = GPU_DEP_KEYWORDS & set(re.findall(r"[\w\[\]]+", content_lower))
                if found:
                    result["gpu_required"] = True
                    result["gpu_signals"].append(f"{path}:{','.join(found)}")
                return  # Found deps, stop searching


def _parse_readme(content: str, result: dict) -> None:
    """Parse README for model type and GPU keywords."""
    content_lower = content.lower()

    # Model type detection (only if not already detected from repo description)
    if result["model_type"] == "unknown":
        for mtype, keywords in MODEL_TYPE_KEYWORDS.items():
            if any(k in content_lower for k in keywords):
                result["model_type"] = mtype
                break

    # GPU from README (weakest signal — only if not already detected)
    if not result["gpu_required"]:
        matches = GPU_README_KEYWORDS & set(re.findall(r"\w+", content_lower))
        if len(matches) >= 2:
            result["gpu_required"] = True
            result["gpu_signals"].append(f"README:{','.join(matches)}")


def _detect_miner(repo: str, root_files: list[str], result: dict) -> None:
    """Detect if an open-source miner exists."""
    # Check common miner locations
    if "neurons" in root_files:
        sub_files = _github_dir(repo, "neurons")
        if "miner.py" in sub_files:
            result["has_miner"] = True
            result["miner_entrypoint"] = "neurons/miner.py"
            return
        if "miners" in sub_files:
            result["has_miner"] = True
            result["miner_entrypoint"] = "neurons/miners/"
            return
    if "miner" in root_files:
        result["has_miner"] = True
        result["miner_entrypoint"] = "miner/"
        # Check if Go-based (go.mod in miner dir)
        sub_files = _github_dir(repo, "miner")
        if "go.mod" in sub_files:
            result["language"] = "go"
        return
    if "src" in root_files:
        sub_files = _github_dir(repo, "src")
        if "miner" in sub_files or "miner.py" in sub_files or "miners" in sub_files:
            result["has_miner"] = True
            result["miner_entrypoint"] = "src/miner"
            return
    if "miner.py" in root_files:
        result["has_miner"] = True
        result["miner_entrypoint"] = "miner.py"


def _detect_language(root_files: list[str], result: dict) -> None:
    """Detect primary language from file extensions."""
    if any(f.endswith(".py") for f in root_files) or "pyproject.toml" in root_files:
        result["language"] = "python"
    elif "go.mod" in root_files:
        result["language"] = "go"
    elif "Cargo.toml" in root_files:
        result["language"] = "rust"
    elif "package.json" in root_files:
        result["language"] = "javascript"


# ---------------------------------------------------------------------------
# Profile building and storage
# ---------------------------------------------------------------------------


def _build_profile(netuid: int, repo: str, analysis: dict) -> dict:
    """Build research profile from analysis results."""
    has_miner = analysis["has_miner"]
    has_docs = bool(analysis["raw_files"].get("readme", ""))
    has_min_compute = bool(analysis["raw_files"].get("min_compute"))

    if has_miner and (has_docs or has_min_compute):
        difficulty = "trivial"
    elif has_miner:
        difficulty = "medium"
    else:
        difficulty = "hard"

    # Confidence based on signal strength
    signal_count = len(analysis["gpu_signals"])
    if has_min_compute:
        confidence = "high"
    elif signal_count >= 2:
        confidence = "medium"
    elif signal_count >= 1:
        confidence = "low"
    else:
        confidence = "low"

    return {
        "netuid": netuid,
        "repo": repo,
        "repo_url": f"https://github.com/{repo}",
        "model_type": analysis["model_type"],
        "gpu_required": analysis["gpu_required"],
        "vram_gb_estimate": analysis["vram_gb_estimate"],
        "gpu_signals": analysis["gpu_signals"],
        "open_source_miner": has_miner,
        "miner_entrypoint": analysis["miner_entrypoint"],
        "language": analysis["language"],
        "difficulty": difficulty,
        "research_confidence": confidence,
        "last_researched": datetime.now(timezone.utc).isoformat(),
    }


def _empty_profile(netuid: int, reason: str) -> dict:
    """Create a profile when repo is unavailable."""
    return {
        "netuid": netuid,
        "repo": None,
        "repo_url": None,
        "model_type": "unknown",
        "gpu_required": None,
        "vram_gb_estimate": None,
        "gpu_signals": [],
        "open_source_miner": False,
        "miner_entrypoint": None,
        "language": None,
        "difficulty": "unknown",
        "research_confidence": "none",
        "last_researched": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
    }


def _store_profile(netuid: int, date: str, profile: dict) -> None:
    """Store research profile to DynamoDB and raw artifacts to S3."""
    # DynamoDB
    _state_manager.store_research_profile(netuid, profile)

    # S3 (raw artifacts for audit)
    _storage.store_snapshot(
        f"raw/research/{date}/{netuid}.json",
        profile,
    )
