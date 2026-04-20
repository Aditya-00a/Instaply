"""Instaply Agent setup wizard.

Detects the user's hardware, installs Ollama if missing, and recommends
the right local model for their machine. Writes the chosen settings to
agent/config/.env so the rest of the agent picks them up.

Run from the agent directory:

    python setup.py

Or pass --yes to skip every confirmation prompt:

    python setup.py --yes

This script never sends data anywhere. Everything it does is on the
user's own machine.
"""
from __future__ import annotations

import sys as _sys
if _sys.platform == "win32":
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / "config" / ".env"
ENV_EXAMPLE = ROOT / "config" / ".env.example"

# ─────────────────────────────────────────────────────────────────────
#  ANSI helpers (colour only when stdout is a TTY)
# ─────────────────────────────────────────────────────────────────────
_USE_COLOUR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

def _wrap(s: str, code: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _USE_COLOUR else s

def bold(s: str) -> str:    return _wrap(s, "1")
def green(s: str) -> str:   return _wrap(s, "32")
def yellow(s: str) -> str:  return _wrap(s, "33")
def red(s: str) -> str:     return _wrap(s, "31")
def cyan(s: str) -> str:    return _wrap(s, "36")
def dim(s: str) -> str:     return _wrap(s, "2")


# ─────────────────────────────────────────────────────────────────────
#  Hardware detection
# ─────────────────────────────────────────────────────────────────────
@dataclass
class Hardware:
    os_name: str          # "Darwin" | "Windows" | "Linux"
    os_version: str
    arch: str             # "x86_64" | "arm64" | "aarch64"
    cpu_brand: str
    cpu_cores: int
    ram_gb: float
    gpu_brand: Optional[str]   # "NVIDIA" | "Apple" | "AMD" | None
    gpu_name: Optional[str]
    vram_gb: Optional[float]   # None when GPU has no dedicated VRAM (or unknown)
    apple_silicon: bool        # True for M1/M2/M3/M4

    @property
    def usable_memory_gb(self) -> float:
        """The biggest memory pool we can use for the LLM.

        - Apple Silicon: system RAM is unified memory, use it directly.
        - NVIDIA + plenty of system RAM: Ollama partial-offloads layers
          to RAM, so a model up to ~VRAM + half of system-RAM is workable
          (slower than pure-VRAM, faster than pure-CPU).
        - CPU-only: just the system RAM, expect slow inference.
        """
        if self.apple_silicon:
            return self.ram_gb
        if self.vram_gb:
            # Hybrid budget: full VRAM + half of system RAM (Ollama spills
            # the rest to CPU; tolerable but slower past pure-GPU limits).
            return self.vram_gb + (self.ram_gb / 2)
        return self.ram_gb


def _ram_gb() -> float:
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except ImportError:
        pass
    # Fallback per-OS
    sysname = platform.system()
    if sysname == "Linux":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return round(kb / (1024 ** 2), 1)
        except OSError:
            pass
    if sysname == "Darwin":
        try:
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True)
            return round(int(out.strip()) / (1024 ** 3), 1)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    if sysname == "Windows":
        try:
            out = subprocess.check_output(
                ["wmic", "computersystem", "get", "TotalPhysicalMemory", "/value"],
                text=True, stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                if line.startswith("TotalPhysicalMemory="):
                    return round(int(line.split("=", 1)[1].strip()) / (1024 ** 3), 1)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    return 0.0


def _cpu_brand() -> str:
    sysname = platform.system()
    if sysname == "Darwin":
        try:
            return subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    if sysname == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    if sysname == "Windows":
        try:
            out = subprocess.check_output(
                ["wmic", "cpu", "get", "Name", "/value"],
                text=True, stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                if line.startswith("Name="):
                    return line.split("=", 1)[1].strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    return platform.processor() or "unknown"


def _detect_gpu() -> tuple[Optional[str], Optional[str], Optional[float]]:
    """Return (brand, name, vram_gb) or (None, None, None)."""
    # NVIDIA via nvidia-smi (works on Linux + Windows)
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                text=True, stderr=subprocess.DEVNULL, timeout=4,
            )
            line = out.strip().splitlines()[0]
            name, vram_mb = [x.strip() for x in line.split(",")]
            return ("NVIDIA", name, round(int(vram_mb) / 1024, 1))
        except (subprocess.CalledProcessError, FileNotFoundError, ValueError, subprocess.TimeoutExpired):
            pass

    # Apple Silicon — unified memory, no separate VRAM
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        try:
            out = subprocess.check_output(
                ["system_profiler", "SPDisplaysDataType"],
                text=True, stderr=subprocess.DEVNULL, timeout=4,
            )
            for line in out.splitlines():
                if "Chipset Model" in line:
                    return ("Apple", line.split(":", 1)[1].strip(), None)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return ("Apple", "Apple Silicon", None)

    # AMD on Linux via rocm-smi (best effort)
    if shutil.which("rocm-smi"):
        try:
            out = subprocess.check_output(
                ["rocm-smi", "--showproductname"], text=True,
                stderr=subprocess.DEVNULL, timeout=4,
            )
            for line in out.splitlines():
                if "Card" in line and ":" in line:
                    return ("AMD", line.split(":", 1)[1].strip(), None)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return (None, None, None)


def detect_hardware() -> Hardware:
    sysname = platform.system()
    arch = platform.machine()
    apple_silicon = sysname == "Darwin" and arch == "arm64"
    gpu_brand, gpu_name, vram_gb = _detect_gpu()
    return Hardware(
        os_name=sysname,
        os_version=platform.release(),
        arch=arch,
        cpu_brand=_cpu_brand(),
        cpu_cores=os.cpu_count() or 0,
        ram_gb=_ram_gb(),
        gpu_brand=gpu_brand,
        gpu_name=gpu_name,
        vram_gb=vram_gb,
        apple_silicon=apple_silicon,
    )


# ─────────────────────────────────────────────────────────────────────
#  Model recommendation
# ─────────────────────────────────────────────────────────────────────
@dataclass
class ModelRec:
    name: str            # Ollama model tag
    label: str           # Human-readable
    pull_size_gb: float
    needs_memory_gb: float
    quality: str         # "basic" | "good" | "great" | "best"
    why: str

# Ordered from smallest to biggest. The picker walks this list and
# returns the biggest model that fits within ~85% of usable memory.
MODEL_LADDER: list[ModelRec] = [
    ModelRec("qwen2.5:3b",         "Qwen 2.5 3B",         2.0,  4,  "basic",
             "tiny but coherent — works on any laptop"),
    ModelRec("llama3.2:3b",        "Llama 3.2 3B",        2.0,  4,  "basic",
             "Meta's small instruction model — solid baseline"),
    ModelRec("llama3.1:8b",        "Llama 3.1 8B",        4.7,  10, "good",
             "the most-used local model — strong quality/size tradeoff"),
    ModelRec("qwen2.5:7b",         "Qwen 2.5 7B",         4.7,  10, "good",
             "good for code + reasoning, slightly faster than Llama 8B"),
    ModelRec("qwen2.5:14b",        "Qwen 2.5 14B",        9.0,  16, "great",
             "noticeably smarter than 7B — needs ~16 GB free"),
    ModelRec("qwen3-coder:30b",    "Qwen3-Coder 30B",     19.0, 32, "best",
             "agentic-friendly, the agent's preferred model"),
    ModelRec("llama3.1:70b",       "Llama 3.1 70B",       40.0, 64, "best",
             "near-frontier quality, only realistic with 64 GB+ unified or NVIDIA pro card"),
]


def recommend_model(hw: Hardware) -> Optional[ModelRec]:
    budget = hw.usable_memory_gb * 0.85   # leave headroom for OS + browser
    fits = [m for m in MODEL_LADDER if m.needs_memory_gb <= budget]
    return fits[-1] if fits else None


# ─────────────────────────────────────────────────────────────────────
#  Ollama install
# ─────────────────────────────────────────────────────────────────────
def has_ollama() -> bool:
    return shutil.which("ollama") is not None


def ollama_running() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def install_ollama_command(os_name: str) -> Optional[list[str] | str]:
    """Return the install command (or a URL string when no good CLI install exists)."""
    if os_name == "Darwin":
        if shutil.which("brew"):
            return ["brew", "install", "--cask", "ollama"]
        return "https://ollama.com/download/Ollama-darwin.zip"
    if os_name == "Linux":
        return "curl -fsSL https://ollama.com/install.sh | sh"
    if os_name == "Windows":
        # Ollama ships a Windows installer; opening the URL is the most
        # reliable path. winget also works on recent Win10/11 boxes.
        if shutil.which("winget"):
            return ["winget", "install", "--id", "Ollama.Ollama", "-e",
                    "--accept-source-agreements", "--accept-package-agreements"]
        return "https://ollama.com/download/OllamaSetup.exe"
    return None


def offer_ollama_install(hw: Hardware, *, auto_yes: bool) -> bool:
    """Returns True if Ollama is now (or already was) installed."""
    if has_ollama():
        print(green("  Ollama is already installed."))
        return True

    cmd = install_ollama_command(hw.os_name)
    if cmd is None:
        print(red(f"  No automatic install path for {hw.os_name}."))
        print(f"  Install it manually from {cyan('https://ollama.com/download')}.")
        return False

    print(yellow("  Ollama is not installed."))
    if isinstance(cmd, list):
        print(f"  Install command: {bold(' '.join(cmd))}")
    else:
        print(f"  Install: {bold(cmd)}")

    if not auto_yes:
        ans = input(f"  Install Ollama now? [{green('y')}/n]: ").strip().lower()
        if ans and ans not in ("y", "yes"):
            print(dim("  Skipped. The agent can still run if you point it at OpenAI / Anthropic."))
            return False

    if isinstance(cmd, list):
        try:
            subprocess.check_call(cmd)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            print(red(f"  Install failed: {exc}"))
            return False
    else:
        # Linux shell-pipe install or a URL we can only suggest.
        if cmd.startswith("http"):
            print(yellow(f"  Open this URL and run the installer:\n    {cmd}"))
            return False
        try:
            subprocess.check_call(cmd, shell=True)
        except subprocess.CalledProcessError as exc:
            print(red(f"  Install failed: {exc}"))
            return False

    return has_ollama()


def pull_model(model: ModelRec, *, auto_yes: bool) -> bool:
    if not has_ollama():
        return False
    if not auto_yes:
        size = f"{model.pull_size_gb:.1f} GB"
        ans = input(f"  Pull {bold(model.name)} ({size})? [{green('y')}/n]: ").strip().lower()
        if ans and ans not in ("y", "yes"):
            print(dim("  Skipped. You can pull it later with `ollama pull " + model.name + "`."))
            return False
    try:
        subprocess.check_call(["ollama", "pull", model.name])
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(red(f"  Pull failed: {exc}"))
        return False


# ─────────────────────────────────────────────────────────────────────
#  .env wiring
# ─────────────────────────────────────────────────────────────────────
def write_env(model: Optional[ModelRec]) -> None:
    """Create config/.env from .env.example, overriding the LLM block."""
    if not ENV_PATH.parent.exists():
        ENV_PATH.parent.mkdir(parents=True, exist_ok=True)

    base = ENV_EXAMPLE.read_text(encoding="utf-8") if ENV_EXAMPLE.exists() else ""
    lines = base.splitlines()

    overrides = {
        "LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": "http://localhost:11434",
    }
    if model:
        overrides["MODEL_NAME"] = model.name

    seen = set()
    new_lines = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in overrides:
                new_lines.append(f"{key}={overrides[key]}")
                seen.add(key)
                continue
        new_lines.append(line)

    # Append any overrides we didn't see in the example file
    for k, v in overrides.items():
        if k not in seen:
            new_lines.append(f"{k}={v}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────
#  Pretty-print + main
# ─────────────────────────────────────────────────────────────────────
def print_hardware(hw: Hardware) -> None:
    print(bold("\nDetected hardware:"))
    print(f"  OS:   {hw.os_name} {hw.os_version} ({hw.arch})")
    print(f"  CPU:  {hw.cpu_brand} ({hw.cpu_cores} cores)")
    print(f"  RAM:  {hw.ram_gb} GB")
    if hw.gpu_brand:
        vram = f"{hw.vram_gb} GB VRAM" if hw.vram_gb else "unified memory"
        print(f"  GPU:  {hw.gpu_brand} {hw.gpu_name} ({vram})")
    else:
        print(dim("  GPU:  none detected — LLM will run on CPU (slower)"))
    print(dim(f"  → usable memory budget for LLM: {hw.usable_memory_gb} GB"))


def print_recommendation(rec: Optional[ModelRec]) -> None:
    print(bold("\nRecommended model:"))
    if rec is None:
        print(red("  No local model fits this machine comfortably."))
        print("  Use a cloud LLM provider (OpenAI / Anthropic) instead.")
        print(dim("  Edit config/.env after setup to set OPENAI_API_KEY etc."))
        return
    print(f"  {green(rec.label)} ({rec.name})")
    print(f"  Quality: {rec.quality} · Pull size: ~{rec.pull_size_gb:.1f} GB · Needs ~{rec.needs_memory_gb} GB free")
    print(dim(f"  Why: {rec.why}"))


def main() -> int:
    # Subcommand dispatch — keep the LLM/hardware wizard as the default,
    # delegate `profile` to profile_wizard.py and `doctor` to doctor.py.
    if len(sys.argv) > 1 and sys.argv[1] == "profile":
        sys.path.insert(0, str(ROOT))
        from profile_wizard import main as profile_main
        return profile_main(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        sys.path.insert(0, str(ROOT))
        from doctor import main as doctor_main
        return doctor_main(sys.argv[2:])

    ap = argparse.ArgumentParser(description="Instaply Agent setup wizard.")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="Skip every confirmation prompt (CI / scripted use).")
    ap.add_argument("--detect-only", action="store_true",
                    help="Print detected hardware + recommendation as JSON, exit 0.")
    args = ap.parse_args()

    print(bold(cyan("\nInstaply Agent setup\n")))
    hw = detect_hardware()

    if args.detect_only:
        rec = recommend_model(hw)
        out = {
            "hardware": hw.__dict__,
            "recommendation": rec.__dict__ if rec else None,
        }
        print(json.dumps(out, indent=2))
        return 0

    print_hardware(hw)
    rec = recommend_model(hw)
    print_recommendation(rec)

    print(bold("\nLLM runtime (Ollama):"))
    have_ollama = offer_ollama_install(hw, auto_yes=args.yes)

    if have_ollama and rec:
        print(bold("\nModel pull:"))
        pull_model(rec, auto_yes=args.yes)

    if ollama_running():
        print(green("\n  Ollama is reachable on http://localhost:11434"))
    elif have_ollama:
        print(yellow("\n  Ollama is installed but not running."))
        print(f"  Start it with {bold('ollama serve')} in another terminal,")
        print(f"  or just run any {bold('ollama run <model>')} once to launch the daemon.")

    print(bold("\nEnvironment file:"))
    write_env(rec)
    print(green(f"  Wrote {ENV_PATH.relative_to(ROOT)}"))
    print(dim("  Open it to add SMTP / portal credentials before running the agent."))

    print(bold(cyan("\nNext steps:")))
    print(f"  1. Run the profile wizard: {bold('python setup.py profile')}")
    print(f"     (Optional: pass {dim('--resume ~/Desktop/your-cv.pdf')} to autopopulate fields)")
    print(f"  2. Sanity-check the install: {bold('python setup.py doctor')}")
    print(f"  3. Start the agent in foreground: {bold('python run.py')}")
    print(f"     Or install as a scheduled task:")
    print(f"       Windows: {bold('powershell -ExecutionPolicy Bypass -File scripts/setup-scheduler.ps1')}")
    print(f"       Mac/Linux: {bold('bash scripts/setup-scheduler.sh')}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
